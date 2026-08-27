# 참조 오디오 대조 방식의 Gemini 발음 판정 호출 모듈
#
# LAN-209 PoC 확정 설정을 그대로 사용한다:
#   - 원어민 TTS 참조 오디오와 유저 음성을 한 요청에 넣고 오디오끼리 대조
#   - temperature 0, reasoning effort low
#   - 기준 텍스트를 프롬프트에 넣는 판정 모드는 앵커링 환각으로 탈락 — 사용 금지
import base64
import json
import time
from dataclasses import dataclass

from openai import OpenAI

from app.core.config import Settings

# 학습자가 고른 억양이 판정 기준이 되므로 프롬프트에 명시한다
ACCENT_NAMES = {
    "EN_US": "American English",
    "EN_GB": "British English",
    "EN_AU": "Australian English",
}

# PoC 검증본 (scripts/poc_pronunciation_v2.py COMPARE_PROMPT과 동일 판정 규칙)
BASE_COMPARE_PROMPT = """You will hear two audio clips. Audio 1 is a native speaker
of {accent_name} reading a sentence (reference). Audio 2 is a learner attempting
the same sentence.

Compare them word by word, judging ONLY from what you hear in the audio.

Completely ignore: voice, gender, pitch, speed, volume, recording quality,
contractions or linking (e.g. "there is" vs "there's"), and minor accent
coloration. These are NEVER differences.

Report a word ONLY when:
- SOUND: a phoneme is clearly substituted with a different phoneme
  (e.g. "th" pronounced as "s", "r" pronounced as "l"), or
- STRESS: within that word, the emphasized syllable is clearly different
  from the reference.

Typical learners get most words right — expect 0 or 1 flagged words.
If you are not certain, do not flag the word.

Respond with JSON only, no markdown fences:
{"differences": [{"word": "<word>", "type": "SOUND", "note": "<short>"},
                 {"word": "<word>", "type": "STRESS", "note": "<short>"}]}
If there are no clear differences: {"differences": []}"""

# 확장본 (작업 2): 판정 규칙은 검증본과 동일하게 유지하고 flagged 단어에만 추가 필드를 요구한다.
# 골든 셋 회귀에서 24/24·오탐 0이 유지되지 않으면 기본본으로 폴백한다.
EXTENDED_COMPARE_PROMPT = """You will hear two audio clips. Audio 1 is a native
speaker of {accent_name} reading a sentence (reference). Audio 2 is a learner
attempting the same sentence.

Compare them word by word, judging ONLY from what you hear in the audio.

Completely ignore: voice, gender, pitch, speed, volume, recording quality,
contractions or linking (e.g. "there is" vs "there's"), and minor accent
coloration. These are NEVER differences.

Report a word ONLY when:
- SOUND: a phoneme is clearly substituted with a different phoneme
  (e.g. "th" pronounced as "s", "r" pronounced as "l"), or
- STRESS: within that word, the emphasized syllable is clearly different
  from the reference.

Typical learners get most words right — expect 0 or 1 flagged words.
If you are not certain, do not flag the word.

For each flagged word, ALSO report (about the learner's audio only):
- "userHeard": a simple syllable-respelling of how the learner actually said
  the word, syllables joined with "·" (e.g. "nuh·ssing"). Lowercase letters only.
- For SOUND: "targetSpan" = the letters of the reference pronunciation that
  differ (e.g. "th"), "userSpan" = the corresponding letters in your
  "userHeard" respelling (e.g. "ss"). Keep both spans short (1-4 letters).
- For STRESS: "stressIndex" = the 0-based index of the syllable the learner
  emphasized, counting syllables of "userHeard".

Respond with JSON only, no markdown fences:
{"differences": [
  {"word": "<word>", "type": "SOUND", "userHeard": "<respelling>",
   "targetSpan": "<letters>", "userSpan": "<letters>"},
  {"word": "<word>", "type": "STRESS", "userHeard": "<respelling>",
   "stressIndex": <int>}
]}
If there are no clear differences: {"differences": []}"""


class PronunciationJudgmentError(Exception):
    """Gemini 호출 실패."""


class PronunciationJudgmentInvalidError(Exception):
    """Gemini 응답이 지정한 JSON 스키마를 벗어남."""


@dataclass(frozen=True)
class JudgedDifference:
    word: str
    type: str
    user_heard: str | None = None
    target_span: str | None = None
    user_span: str | None = None
    stress_index: int | None = None


def judge_pronunciation(
    client: OpenAI,
    settings: Settings,
    reference_wav: bytes,
    user_wav: bytes,
    accent_locale: str = "EN_US",
    extended: bool = True,
    deadline: float | None = None,
) -> list[JudgedDifference]:
    template = EXTENDED_COMPARE_PROMPT if extended else BASE_COMPARE_PROMPT
    # 프롬프트에 JSON 예시의 중괄호가 있으므로 str.format을 쓰지 않는다
    prompt = template.replace("{accent_name}", ACCENT_NAMES[accent_locale])
    content = [
        {"type": "text", "text": prompt},
        _audio_part(reference_wav),
        _audio_part(user_wav),
    ]
    return _call_with_retry(client, settings, content, deadline)


def _call_with_retry(
    client: OpenAI,
    settings: Settings,
    content: list,
    deadline: float | None = None,
) -> list["JudgedDifference"]:
    # 실측(LAN-373 스파이크)에서 36회 중 1회 스키마 위반이 나왔으므로
    # JSON 파싱뿐 아니라 스키마 검증 실패까지 같은 재시도로 흡수한다.
    # 단, 전체 분석 예산(deadline)이 남아 있을 때만 시도한다.
    last_error: Exception | None = None
    for _ in range(2):
        timeout = settings.pronunciation_llm_timeout_seconds
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            timeout = min(timeout, remaining)
        try:
            response = client.chat.completions.create(
                model=settings.pronunciation_model,
                temperature=0.0,
                max_tokens=4000,
                messages=[{"role": "user", "content": content}],
                extra_body={
                    "reasoning": {"effort": settings.pronunciation_reasoning_effort}
                },
                timeout=timeout,
            )
        except Exception as error:  # noqa: BLE001 — SDK 예외 전반을 생성 실패로 취급
            raise PronunciationJudgmentError(str(error)) from error
        raw = (response.choices[0].message.content or "").strip()
        try:
            return _parse_differences(raw)
        except (
            json.JSONDecodeError,
            ValueError,
            PronunciationJudgmentInvalidError,
        ) as error:
            last_error = error
    if last_error is None:
        raise PronunciationJudgmentError(
            "analysis budget exhausted before judgment"
        )
    raise PronunciationJudgmentInvalidError(
        "judgment response did not match the expected schema"
    ) from last_error


def _parse_differences(raw: str) -> list[JudgedDifference]:
    payload = json.loads(_strip_fences(raw))
    differences = payload.get("differences")
    if not isinstance(differences, list):
        raise PronunciationJudgmentInvalidError("differences must be a list")
    parsed: list[JudgedDifference] = []
    for item in differences:
        if not isinstance(item, dict):
            raise PronunciationJudgmentInvalidError("difference item must be an object")
        word = item.get("word")
        type_ = item.get("type")
        if not isinstance(word, str) or type_ not in ("SOUND", "STRESS"):
            raise PronunciationJudgmentInvalidError("difference item is malformed")
        stress_index = item.get("stressIndex")
        parsed.append(
            JudgedDifference(
                word=word,
                type=type_,
                user_heard=_optional_str(item.get("userHeard")),
                target_span=_optional_str(item.get("targetSpan")),
                user_span=_optional_str(item.get("userSpan")),
                stress_index=stress_index if isinstance(stress_index, int) else None,
            )
        )
    return parsed


def _optional_str(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _strip_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    return cleaned


def _audio_part(wav: bytes) -> dict:
    data = base64.b64encode(wav).decode("ascii")
    return {"type": "input_audio", "input_audio": {"data": data, "format": "wav"}}
