# 발음 분석 파이프라인을 오케스트레이션하는 서비스 모듈
#
# 흐름: 오디오 디코드 → [참조 다운로드 → Gemini 판정] ∥ [wav2vec2 강제 정렬] → order 병합.
# 전체 wall-clock 예산(기본 17초)을 진입점에서 잡고 모든 단계(ffmpeg·다운로드·LLM·정렬·
# 묘사)의 타임아웃을 남은 예산과 min으로 묶어, 어떤 조합에서도 BE 타임아웃(20초)보다
# 먼저 반환한다. 필수 단계(판정·정렬)가 예산을 넘기면 503, 보조 단계(억양 확인·묘사)는
# 결과에서 비운 채 판정만 반환한다.
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import replace
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.openai_client import create_openai_client
from app.models.pronunciation import (
    PronunciationAccentErrorType,
    PronunciationAnalyzeRequest,
    PronunciationAnalyzeResponse,
    PronunciationWordResult,
    PronunciationWordStatus,
)
from app.pronunciation.alignment.forced_align import WordSpan, align_words
from app.pronunciation.audio import convert_to_wav, decode_user_audio
from app.pronunciation.llm.accent_check import (
    AccentCheckError,
    AccentContrast,
    AccentVerdict,
    check_accent,
)
from app.pronunciation.llm.compare import JudgedDifference, judge_pronunciation
from app.pronunciation.llm.describe import ErrorDescription, describe_error
from app.pronunciation.numbers import spell_out


class ReferenceAudioUnavailableError(Exception):
    """참조 오디오 다운로드 실패."""


class AnalysisBudgetExceededError(Exception):
    """전체 wall-clock 예산 안에 필수 단계(판정·정렬)가 끝나지 못함."""


_STATUS_BY_DIFFERENCE_TYPE = {
    "SOUND": PronunciationWordStatus.PHONEME_ERROR,
    "STRESS": PronunciationWordStatus.STRESS_ERROR,
}

# 남은 예산이 이보다 적으면 묘사 호출을 건너뛰고 판정만 반환한다
_DESCRIBE_MIN_REMAINING_SECONDS = 1.0
# 참조 오디오 다운로드 크기 상한 (문장 TTS mp3는 수백 KB 수준)
_MAX_REFERENCE_AUDIO_BYTES = 10_000_000


def is_reference_url_allowed(url: str, settings: Settings) -> bool:
    """참조 URL의 origin이 설정된 allowlist에 있는지 검사한다 (SSRF 차단)."""
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return False
    origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    allowed = {
        entry.strip().lower().rstrip("/")
        for entry in settings.pronunciation_reference_allowed_origins.split(",")
        if entry.strip()
    }
    return origin in allowed


def analyze_pronunciation(
    payload: PronunciationAnalyzeRequest,
    settings: Settings,
) -> PronunciationAnalyzeResponse:
    deadline = time.monotonic() + settings.pronunciation_total_budget_seconds
    decoded = decode_user_audio(
        payload.decoded_user_audio(), payload.userAudioFormat.value, deadline
    )
    ordered_words = sorted(payload.words, key=lambda word: word.order)
    # 숫자 단어("9")는 발화 철자("nine")로 정렬해야 타임스탬프가 맞는다
    word_texts = [
        spell_out(word.word) or word.word for word in ordered_words
    ]

    contrasts = _accent_contrasts(ordered_words)
    # with(=shutdown(wait=True))를 쓰면 예산을 넘긴 스레드를 기다리게 되므로
    # 대기 없이 닫고 결과 수거에만 남은 예산을 적용한다
    executor = ThreadPoolExecutor(max_workers=2 + len(contrasts))
    try:
        judgment_future = executor.submit(
            _judge,
            payload.referenceAudioUrl,
            decoded.judgment_wav,
            payload.accentLocale.value,
            settings,
            deadline,
        )
        alignment_future = executor.submit(
            align_words, decoded.alignment_wav, word_texts
        )
        # 억양 확인은 단어 단위 양자택일이라 서로 독립이므로 본 판정과 함께 병렬로 던진다
        accent_futures = [
            executor.submit(_check_accent, decoded.judgment_wav, contrast, settings)
            for contrast in contrasts
        ]
        differences, reference_wav = _required_result(judgment_future, deadline)
        spans = _required_result(alignment_future, deadline)
        # 억양 확인은 보조 판정 — 예산을 넘기면 없는 것으로 친다
        verdicts = [_auxiliary_result(future, deadline) for future in accent_futures]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    differences = _describe(
        differences, reference_wav, decoded.judgment_wav, settings, deadline
    )
    results = _merge(ordered_words, spans, differences)
    _apply_accent_verdicts(results, ordered_words, verdicts)
    return PronunciationAnalyzeResponse(words=results)


def _required_result(future, deadline: float):
    try:
        return future.result(timeout=max(0.0, deadline - time.monotonic()))
    except FuturesTimeoutError as error:
        raise AnalysisBudgetExceededError(
            "analysis exceeded the total wall-clock budget"
        ) from error


def _auxiliary_result(future, deadline: float):
    try:
        return future.result(timeout=max(0.0, deadline - time.monotonic()))
    except FuturesTimeoutError:
        return None


def _accent_contrasts(ordered_words) -> list[AccentContrast]:
    return [
        AccentContrast(
            order=word.order,
            word=word.word,
            expected_option=word.accentContrast.expected,
            other_option=word.accentContrast.other,
        )
        for word in ordered_words
        if word.accentContrast is not None
    ]


def _check_accent(
    user_wav: bytes, contrast: AccentContrast, settings: Settings
) -> AccentVerdict | None:
    client = create_openai_client(settings)
    try:
        return check_accent(client, settings, user_wav, contrast)
    except AccentCheckError:
        # 보조 판정이므로 실패해도 본 판정 결과는 그대로 반환한다
        return None


def _apply_accent_verdicts(
    results: list[PronunciationWordResult],
    ordered_words,
    verdicts: list[AccentVerdict | None],
) -> None:
    by_order = {result.order: result for result in results}
    contrast_by_order = {
        word.order: word.accentContrast
        for word in ordered_words
        if word.accentContrast is not None
    }
    for verdict in verdicts:
        if verdict is None or verdict.matches_expected:
            continue
        result = by_order.get(verdict.order)
        # 본 판정이 이미 오류로 본 단어는 그 판정을 유지한다
        if result is None or result.status is not PronunciationWordStatus.CORRECT:
            continue
        contrast = contrast_by_order[verdict.order]
        result.status = (
            PronunciationWordStatus.STRESS_ERROR
            if contrast.errorType is PronunciationAccentErrorType.STRESS
            else PronunciationWordStatus.PHONEME_ERROR
        )
        result.userDisplay = verdict.user_heard


def _judge(
    reference_audio_url: str,
    user_wav: bytes,
    accent_locale: str,
    settings: Settings,
    deadline: float | None = None,
) -> tuple[list[JudgedDifference], bytes]:
    reference_wav = _download_reference(reference_audio_url, settings, deadline)
    client = create_openai_client(settings)
    # 탐지는 PoC 검증본(24/24·오탐 0) 프롬프트로만 한다. 묘사는 _describe에서 따로 채운다.
    differences = judge_pronunciation(
        client,
        settings,
        reference_wav=reference_wav,
        user_wav=user_wav,
        accent_locale=accent_locale,
        extended=False,
        deadline=deadline,
    )
    return differences, reference_wav


def _describe(
    differences: list[JudgedDifference],
    reference_wav: bytes,
    user_wav: bytes,
    settings: Settings,
    deadline: float | None = None,
) -> list[JudgedDifference]:
    """오류로 확정된 단어에만 묘사 호출을 붙인다. 오류가 없으면 호출하지 않는다.

    묘사는 보조 정보라 남은 예산이 부족하면 통째로 건너뛰고 판정만 반환한다.
    """
    if not differences or not settings.pronunciation_describe_errors:
        return differences
    if (
        deadline is not None
        and deadline - time.monotonic() < _DESCRIBE_MIN_REMAINING_SECONDS
    ):
        return differences

    client = create_openai_client(settings)
    with ThreadPoolExecutor(max_workers=len(differences)) as executor:
        described = executor.map(
            lambda difference: _with_description(
                difference,
                describe_error(
                    client,
                    settings,
                    reference_wav=reference_wav,
                    user_wav=user_wav,
                    word=difference.word,
                    error_type=difference.type,
                    deadline=deadline,
                ),
            ),
            differences,
        )
        return list(described)


def _with_description(
    difference: JudgedDifference, description: ErrorDescription | None
) -> JudgedDifference:
    if description is None:
        return difference
    return replace(
        difference,
        user_heard=description.user_heard,
        target_span=description.target_span,
        user_span=description.user_span,
        stress_index=description.stress_index,
    )


def _download_reference(
    url: str, settings: Settings, deadline: float | None = None
) -> bytes:
    # 라우트에서 이미 거른 조건이지만 서비스 단독 호출에 대비해 재검증한다 (SSRF 차단)
    if not is_reference_url_allowed(url, settings):
        raise ReferenceAudioUnavailableError("reference url origin is not allowed")

    timeout = settings.pronunciation_reference_download_timeout_seconds
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReferenceAudioUnavailableError("analysis budget exhausted")
        timeout = min(timeout, remaining)

    content = bytearray()
    try:
        # 자산 URL에 리다이렉트는 없어야 정상이므로 따라가지 않는다 (SSRF 우회 차단)
        with httpx.stream(
            "GET", url, timeout=timeout, follow_redirects=False
        ) as response:
            if not response.is_success:
                raise ReferenceAudioUnavailableError(
                    f"reference download failed: HTTP {response.status_code}"
                )
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_REFERENCE_AUDIO_BYTES:
                    raise ReferenceAudioUnavailableError(
                        "reference audio is larger than the allowed size"
                    )
    except httpx.HTTPError as error:
        raise ReferenceAudioUnavailableError(str(error)) from error

    suffix = urlparse(url).path.rsplit(".", 1)
    source_format = suffix[1].lower() if len(suffix) == 2 else "mp3"
    if source_format == "wav":
        return bytes(content)
    return convert_to_wav(bytes(content), source_format, deadline)


def _merge(
    ordered_words,
    spans: list[WordSpan],
    differences: list[JudgedDifference],
) -> list[PronunciationWordResult]:
    results = [
        PronunciationWordResult(
            order=word.order,
            word=word.word,
            status=PronunciationWordStatus.CORRECT,
            startMs=span.start_ms,
            endMs=span.end_ms,
        )
        for word, span in zip(ordered_words, spans)
    ]
    flagged_indexes: set[int] = set()
    for difference in differences:
        index = _find_word_index(ordered_words, difference.word, flagged_indexes)
        if index is None:
            continue
        flagged_indexes.add(index)
        result = results[index]
        result.status = _STATUS_BY_DIFFERENCE_TYPE[difference.type]
        result.userDisplay = difference.user_heard
        if result.status is PronunciationWordStatus.PHONEME_ERROR:
            result.errorTargetSpan = difference.target_span
            result.errorUserSpan = difference.user_span
        else:
            result.userStressIndex = difference.stress_index
    return results


def _find_word_index(
    ordered_words, detected_word: str, flagged_indexes: set[int]
) -> int | None:
    normalized = _normalize_word(detected_word)
    for index, word in enumerate(ordered_words):
        if index in flagged_indexes:
            continue
        if _normalize_word(word.word) == normalized:
            return index
    return None


def _normalize_word(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower())
