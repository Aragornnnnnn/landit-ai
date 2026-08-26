# 발음 분석 파이프라인을 오케스트레이션하는 서비스 모듈
#
# 흐름: 오디오 디코드 → [참조 다운로드 → Gemini 판정] ∥ [wav2vec2 강제 정렬] → order 병합.
# BE 타임아웃(20초)보다 먼저 실패를 반환하도록 각 단계에 자체 타임아웃을 둔다.
import re
from concurrent.futures import ThreadPoolExecutor
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


class ReferenceAudioUnavailableError(Exception):
    """참조 오디오 다운로드 실패."""


_STATUS_BY_DIFFERENCE_TYPE = {
    "SOUND": PronunciationWordStatus.PHONEME_ERROR,
    "STRESS": PronunciationWordStatus.STRESS_ERROR,
}


def analyze_pronunciation(
    payload: PronunciationAnalyzeRequest,
    settings: Settings,
) -> PronunciationAnalyzeResponse:
    decoded = decode_user_audio(
        payload.decoded_user_audio(), payload.userAudioFormat.value
    )
    ordered_words = sorted(payload.words, key=lambda word: word.order)
    word_texts = [word.word for word in ordered_words]

    contrasts = _accent_contrasts(ordered_words)
    with ThreadPoolExecutor(max_workers=2 + len(contrasts)) as executor:
        judgment_future = executor.submit(
            _judge,
            payload.referenceAudioUrl,
            decoded.judgment_wav,
            payload.accentLocale.value,
            settings,
        )
        alignment_future = executor.submit(
            align_words, decoded.alignment_wav, word_texts
        )
        # 억양 확인은 단어 단위 양자택일이라 서로 독립이므로 본 판정과 함께 병렬로 던진다
        accent_futures = [
            executor.submit(_check_accent, decoded.judgment_wav, contrast, settings)
            for contrast in contrasts
        ]
        differences, reference_wav = judgment_future.result()
        spans = alignment_future.result()
        verdicts = [future.result() for future in accent_futures]

    differences = _describe(
        differences, reference_wav, decoded.judgment_wav, settings
    )
    results = _merge(ordered_words, spans, differences)
    _apply_accent_verdicts(results, ordered_words, verdicts)
    return PronunciationAnalyzeResponse(words=results)


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
) -> tuple[list[JudgedDifference], bytes]:
    reference_wav = _download_reference(reference_audio_url, settings)
    client = create_openai_client(settings)
    # 탐지는 PoC 검증본(24/24·오탐 0) 프롬프트로만 한다. 묘사는 _describe에서 따로 채운다.
    differences = judge_pronunciation(
        client,
        settings,
        reference_wav=reference_wav,
        user_wav=user_wav,
        accent_locale=accent_locale,
        extended=False,
    )
    return differences, reference_wav


def _describe(
    differences: list[JudgedDifference],
    reference_wav: bytes,
    user_wav: bytes,
    settings: Settings,
) -> list[JudgedDifference]:
    """오류로 확정된 단어에만 묘사 호출을 붙인다. 오류가 없으면 호출하지 않는다."""
    if not differences or not settings.pronunciation_describe_errors:
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


def _download_reference(url: str, settings: Settings) -> bytes:
    try:
        response = httpx.get(
            url,
            timeout=settings.pronunciation_reference_download_timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ReferenceAudioUnavailableError(str(error)) from error

    suffix = urlparse(url).path.rsplit(".", 1)
    source_format = suffix[1].lower() if len(suffix) == 2 else "mp3"
    if source_format == "wav":
        return response.content
    return convert_to_wav(response.content, source_format)


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
