# 발음 분석 API의 요청과 응답 모델을 정의하는 모듈
import base64
import binascii
import re
from enum import StrEnum

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# base64 인코딩 기준 최대 크기 (원본 약 10MB)
_MAX_USER_AUDIO_BASE64_LENGTH = 14_000_000


def _validate_not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _word_tokens(text: str) -> list[str]:
    # PoC 채점과 동일한 단어 정규화에 숫자를 더한다. 숫자 단어("9")는 판정 없이
    # 통과 처리하지만 words 목록과 정렬에는 포함돼야 한다.
    return re.findall(r"[a-z0-9']+", text.lower())


class PronunciationAudioFormat(StrEnum):
    M4A = "m4a"
    WAV = "wav"
    MP3 = "mp3"


class PronunciationAccentLocale(StrEnum):
    EN_US = "EN_US"
    EN_GB = "EN_GB"
    EN_AU = "EN_AU"


class PronunciationWordStatus(StrEnum):
    CORRECT = "CORRECT"
    PHONEME_ERROR = "PHONEME_ERROR"
    STRESS_ERROR = "STRESS_ERROR"


class PronunciationAccentErrorType(StrEnum):
    """억양 대조가 어긋났을 때 어떤 오류로 볼지. 대부분 음소 차이다."""

    PHONEME = "PHONEME"
    STRESS = "STRESS"


class PronunciationAccentContrast(BaseModel):
    """학습 억양이 기대하는 발음과 그와 대비되는 발음.

    문장이 고정 콘텐츠이므로 BE가 accentLocale 기준으로 풀어서 보낸다.
    예) EN_GB 학습자의 "water" → expected="a clear t (WAW-tuh)",
        other="a d-like flap (WAH-der)"
    """

    model_config = ConfigDict(extra="forbid")

    expected: str
    other: str
    errorType: PronunciationAccentErrorType = PronunciationAccentErrorType.PHONEME

    @field_validator("expected", "other")
    @classmethod
    def options_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class PronunciationWordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(gt=0)
    word: str
    accentContrast: PronunciationAccentContrast | None = None

    @field_validator("word")
    @classmethod
    def word_must_not_be_blank(cls, value: str) -> str:
        value = _validate_not_blank(value)
        # 숫자 단어는 정렬 시 철자로 변환하는데 0~99만 지원한다
        if value.strip().isdigit() and int(value.strip()) > 99:
            raise ValueError("numeric words above 99 are not supported")
        return value


class PronunciationAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 유저 음성 원본은 로그·Sentry에 노출되면 안 되므로 repr에서 제외한다
    userAudio: str = Field(repr=False, max_length=_MAX_USER_AUDIO_BASE64_LENGTH)
    userAudioFormat: PronunciationAudioFormat
    sentenceText: str
    referenceAudioUrl: str
    accentLocale: PronunciationAccentLocale
    words: list[PronunciationWordInput] = Field(min_length=1)

    @field_validator("sentenceText", "referenceAudioUrl")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("userAudio")
    @classmethod
    def user_audio_must_be_base64(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        try:
            base64.b64decode(stripped, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("must be valid base64") from error
        return stripped

    @model_validator(mode="after")
    def word_orders_must_be_unique(self) -> Self:
        orders = [word.order for word in self.words]
        if len(orders) != len(set(orders)):
            raise ValueError("word orders must be unique")
        return self

    @model_validator(mode="after")
    def words_must_match_sentence(self) -> Self:
        # BE의 sentenceText(representative_sentence 스냅샷)와 words_payload가
        # 어긋난 요청을 조용히 처리하지 않도록 토큰 일치를 검증한다.
        sentence_tokens = _word_tokens(self.sentenceText)
        payload_tokens = [
            _word_tokens(word.word)[0] if _word_tokens(word.word) else ""
            for word in sorted(self.words, key=lambda word: word.order)
        ]
        if sentence_tokens != payload_tokens:
            raise ValueError("words do not match sentenceText")
        return self

    def decoded_user_audio(self) -> bytes:
        return base64.b64decode(self.userAudio, validate=True)


class PronunciationWordResult(BaseModel):
    order: int
    word: str
    status: PronunciationWordStatus
    startMs: int
    endMs: int
    userDisplay: str | None = None
    errorTargetSpan: str | None = None
    errorUserSpan: str | None = None
    userStressIndex: int | None = None


class PronunciationAnalyzeResponse(BaseModel):
    words: list[PronunciationWordResult]
