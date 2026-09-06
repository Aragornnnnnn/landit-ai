# 억양 대조 단어를 양자택일 질문으로 판정하는 모듈
#
# LAN-373 스파이크 근거:
#   - 열린 질문("두 오디오의 차이를 찾아라")으로 억양을 물으면 모델이 오디오를 듣지 않고
#     '유명한 미/영 차이 단어'를 사전 지식으로 찍는다. 같은 억양끼리도 오탐 6/9,
#     문장에 없는 단어(wash)를 지어내기까지 했다. LAN-209가 이미 탈락시킨 환각 모드다.
#   - 같은 모델·오디오·설정에서 선택지를 주고 고르게 하는 게 더 정확했다.
#   "이 오디오에서 water 한 단어만 집중해서 들어라.
#   A) 워러처럼 들리나 (d 같은 소리)
#   B) 워터처럼 들리나 (또렷한 t)
#   오디오만 듣고 답해라: A 또는 B"" 이런 방식
#     schedule(sk/sh), water(flap/clear t), can't(a/ah), tomato(MAY/MAH),
#     advertisement(강세 위치)를 모두 맞혔다.
# 그래서 억양 판정은 일반 대조 판정과 분리해 단어 단위 양자택일로만 수행한다.
import base64
import json
import logging
from dataclasses import dataclass

from openai import OpenAI

from app.core.config import Settings
from app.pronunciation.llm.routing import llm_extra_body, served_by_fallback

logger = logging.getLogger(__name__)

ACCENT_CHECK_PROMPT = """Listen to the audio and focus ONLY on how the speaker
pronounces the word "{word}".

Which does it sound like?
A) {option_a}
B) {option_b}

Judge only from the audio, not from what is typical. If the word is not clearly
audible, answer "UNCLEAR".

Answer with JSON only, no markdown fences:
{"answer": "A", "heard": "<short respelling of just that word>"}"""


@dataclass(frozen=True)
class AccentContrast:
    """한 단어에서 학습 억양이 기대하는 발음과, 그와 대비되는 발음."""

    order: int
    word: str
    expected_option: str
    other_option: str


@dataclass(frozen=True)
class AccentVerdict:
    order: int
    word: str
    matches_expected: bool
    user_heard: str | None


class AccentCheckError(Exception):
    """억양 확인 호출 실패."""


def check_accent(
    client: OpenAI,
    settings: Settings,
    user_wav: bytes,
    contrast: AccentContrast,
) -> AccentVerdict | None:
    """단어 하나의 억양을 확인한다. 판별이 불확실하면 None을 반환해 판정에서 제외한다."""
    # 선택지 순서에 따른 편향을 줄이기 위해 기대 발음을 항상 A에 두지는 않는다.
    expected_is_a = contrast.order % 2 == 1
    option_a = contrast.expected_option if expected_is_a else contrast.other_option
    option_b = contrast.other_option if expected_is_a else contrast.expected_option

    prompt = (
        ACCENT_CHECK_PROMPT.replace("{word}", contrast.word)
        .replace("{option_a}", option_a)
        .replace("{option_b}", option_b)
    )
    data = base64.b64encode(user_wav).decode("ascii")
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
                        {
                            "type": "input_audio",
                            "input_audio": {"data": data, "format": "wav"},
                        },
                    ],
                }
            ],
            extra_body=llm_extra_body(settings),
            timeout=settings.pronunciation_llm_timeout_seconds,
        )
    except Exception as error:  # noqa: BLE001 — SDK 예외 전반을 호출 실패로 취급
        raise AccentCheckError(str(error)) from error

    # 폴백 프로바이더 서빙은 조용한 품질 저하다 (LAN-389) — 발동 사실을 관측한다
    fallback_provider = served_by_fallback(settings, response)
    if fallback_provider is not None:
        logger.warning(
            "accent check served by fallback provider %s", fallback_provider
        )

    raw = (response.choices[0].message.content or "").strip()
    return _parse_verdict(raw, contrast, expected_is_a)


def _parse_verdict(
    raw: str, contrast: AccentContrast, expected_is_a: bool
) -> AccentVerdict | None:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        # 억양 확인은 보조 판정이므로 파싱 실패는 오류 대신 '판정 없음'으로 흘린다
        return None
    answer = payload.get("answer")
    if answer not in ("A", "B"):
        return None

    expected_answer = "A" if expected_is_a else "B"
    heard = payload.get("heard")
    return AccentVerdict(
        order=contrast.order,
        word=contrast.word,
        matches_expected=answer == expected_answer,
        user_heard=heard.strip() if isinstance(heard, str) and heard.strip() else None,
    )
