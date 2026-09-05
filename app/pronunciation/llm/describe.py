# 이미 오류로 판정된 단어를 묘사하는 모듈 (respelling·오류 구간·강세 위치)
#
# LAN-373 골든 셋 A/B 근거:
#   - 대조 판정 프롬프트에 확장 필드까지 요구하면 정확일치 22/24, 오탐 2 run으로 떨어진다.
#     지적한 단어를 묘사하라는 요구가 모델을 '묘사할 거리를 찾는' 방향으로 밀어
#     정상 발음(diner)을 그럴듯하게 오류로 지어냈다.
#   - 같은 골든 셋을 PoC 검증본 프롬프트로 돌리면 24/24, 오탐 0이 그대로 재현된다.
# 그래서 탐지(대조 판정)와 묘사(이 모듈)를 분리한다. 이 호출은 이미 오류로 확정된
# 단어에만 수행하므로 탐지 결과를 바꾸지 못한다.
import base64
import json
import logging
import time
from dataclasses import dataclass

from openai import OpenAI

from app.core.config import Settings
from app.pronunciation.llm.routing import llm_extra_body, served_by_fallback

logger = logging.getLogger(__name__)

_SOUND_INSTRUCTION = """Also report which letters differ:
- "targetSpan": the letters of the reference pronunciation that differ (e.g. "th")
- "userSpan": the matching letters in your respelling (e.g. "ss")
Keep both spans short (1-4 letters)."""

_STRESS_INSTRUCTION = """Also report "stressIndex": the 0-based index of the
syllable the learner emphasized, counting the syllables of your respelling."""

DESCRIBE_PROMPT = """You will hear two audio clips of the same sentence. Audio 1
is a native speaker (reference), Audio 2 is a learner.

The learner's pronunciation of the word "{word}" has already been determined to
differ from the reference. Do not re-judge whether it differs — it does.

Describe ONLY how the learner said that one word:
- "userHeard": a simple syllable-respelling of how the learner actually said it,
  syllables joined with "·" (e.g. "nuh·ssing"). Lowercase letters only.
{extra_instruction}

Answer with JSON only, no markdown fences:
{"userHeard": "<respelling>"{extra_keys}}"""


@dataclass(frozen=True)
class ErrorDescription:
    user_heard: str | None
    target_span: str | None
    user_span: str | None
    stress_index: int | None


def describe_error(
    client: OpenAI,
    settings: Settings,
    reference_wav: bytes,
    user_wav: bytes,
    word: str,
    error_type: str,
    deadline: float | None = None,
) -> ErrorDescription | None:
    """오류 단어 하나를 묘사한다. 실패하면 None을 반환해 필드를 비운 채 응답한다."""
    timeout = settings.pronunciation_llm_timeout_seconds
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # 전체 분석 예산 소진 — 묘사는 보조 정보이므로 호출 없이 비운다
            return None
        timeout = min(timeout, remaining)
    is_stress = error_type == "STRESS"
    prompt = (
        DESCRIBE_PROMPT.replace("{word}", word)
        .replace(
            "{extra_instruction}",
            _STRESS_INSTRUCTION if is_stress else _SOUND_INSTRUCTION,
        )
        .replace(
            "{extra_keys}",
            ', "stressIndex": 0'
            if is_stress
            else ', "targetSpan": "<letters>", "userSpan": "<letters>"',
        )
    )
    try:
        response = client.chat.completions.create(
            model=settings.pronunciation_model,
            temperature=0.0,
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        _audio_part(reference_wav),
                        _audio_part(user_wav),
                    ],
                }
            ],
            extra_body=llm_extra_body(settings),
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 — 묘사는 보조 정보이므로 실패해도 판정은 유지한다
        return None

    # 폴백 프로바이더 서빙은 조용한 품질 저하다 (LAN-389) — 발동 사실을 관측한다
    fallback_provider = served_by_fallback(settings, response)
    if fallback_provider is not None:
        logger.warning(
            "error description served by fallback provider %s", fallback_provider
        )

    raw = (response.choices[0].message.content or "").strip()
    return _parse(raw, is_stress)


def _parse(raw: str, is_stress: bool) -> ErrorDescription | None:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    user_heard = _text(payload.get("userHeard"))
    return ErrorDescription(
        user_heard=user_heard,
        target_span=None if is_stress else _text(payload.get("targetSpan")),
        user_span=None if is_stress else _text(payload.get("userSpan")),
        stress_index=_valid_stress_index(payload.get("stressIndex"), user_heard)
        if is_stress
        else None,
    )


def _valid_stress_index(value, user_heard: str | None) -> int | None:
    """stressIndex는 userHeard respelling의 음절 인덱스일 때만 유효하다.

    FE가 이 값을 음절 배열 인덱스로 쓰므로 범위 밖 값이 나가면 안 된다.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if user_heard is None:
        logger.warning(
            "describe stressIndex %d dropped: no userHeard respelling", value
        )
        return None
    syllable_count = len(user_heard.split("·"))
    if not 0 <= value < syllable_count:
        logger.warning(
            "describe stressIndex %d dropped: out of range for %d syllables",
            value,
            syllable_count,
        )
        return None
    return value


def _text(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _audio_part(wav: bytes) -> dict:
    data = base64.b64encode(wav).decode("ascii")
    return {"type": "input_audio", "input_audio": {"data": data, "format": "wav"}}
