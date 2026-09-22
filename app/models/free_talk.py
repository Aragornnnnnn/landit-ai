# 프리톡 생성 API의 요청과 응답 모델을 정의하는 모듈
import math
from datetime import datetime
from enum import StrEnum
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.conversation import (
    ConversationHistoryMessage,
    InnerThoughtType,
)


def _validate_not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class Emotion(StrEnum):
    NEUTRAL = "NEUTRAL"
    HAPPY = "HAPPY"
    SURPRISED = "SURPRISED"
    SAD = "SAD"
    ANGRY = "ANGRY"


class FreeTalkResponseMode(StrEnum):
    NORMAL = "NORMAL"
    CONTINUE_AFTER_EXIT_DECLINED = "CONTINUE_AFTER_EXIT_DECLINED"


class FreeTalkClosingReason(StrEnum):
    USER_CONFIRMED = "USER_CONFIRMED"
    TIME_LIMIT_REACHED = "TIME_LIMIT_REACHED"


class FreeTalkCharacter(StrEnum):
    CHLOE = "chloe"
    MARCO = "marco"
    TEDDY = "teddy"


class MemoryType(StrEnum):
    PROFILE = "PROFILE"
    EVENT = "EVENT"
    EPISODE = "EPISODE"


class MemoryOperation(StrEnum):
    ADD = "ADD"
    SUPERSEDE = "SUPERSEDE"
    IGNORE = "IGNORE"


class FollowUpTriggerType(StrEnum):
    """다음 스몰톡 후속 질문의 계기. 선언 순서가 곧 선택 우선순위이며 NONE은 질문 없음이다."""

    CUT_OFF = "CUT_OFF"
    PAST_EVENT = "PAST_EVENT"
    CONCERN = "CONCERN"
    GOAL = "GOAL"
    MOOD = "MOOD"
    HOBBY = "HOBBY"
    NONE = "NONE"


class FreeTalkMistakePattern(StrEnum):
    """턴별 교정에서 고른 문장의 대표 실수 유형. 세션을 가로질러 비교하므로 고정 목록이다."""

    TENSE = "TENSE"
    SUBJECT_VERB_AGREEMENT = "SUBJECT_VERB_AGREEMENT"
    VERB_FORM = "VERB_FORM"
    ARTICLE = "ARTICLE"
    PLURAL = "PLURAL"
    PRONOUN = "PRONOUN"
    PREPOSITION = "PREPOSITION"
    NEGATION = "NEGATION"
    QUESTION_FORM = "QUESTION_FORM"
    WORD_ORDER = "WORD_ORDER"
    MISSING_WORD = "MISSING_WORD"
    REDUNDANCY = "REDUNDANCY"
    WORD_CHOICE = "WORD_CHOICE"
    LITERAL_TRANSLATION = "LITERAL_TRANSLATION"
    REGISTER = "REGISTER"
    NATURALNESS = "NATURALNESS"
    OTHER = "OTHER"


def _validate_timezone_aware(value: datetime) -> datetime:
    """기억 시각은 사용자 시간대 해석을 위해 명시적 오프셋을 포함해야 한다."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value


def _validate_unique_positive_ids(value: list[int]) -> list[int]:
    """기억 참조 ID는 저장 계약상 양수이며 중복될 수 없다."""
    if any(identifier <= 0 for identifier in value):
        raise ValueError("ids must be positive")
    if len(value) != len(set(value)):
        raise ValueError("ids must be unique")
    return value


def _validate_finite_embedding(value: list[float]) -> list[float]:
    """벡터 검색에 사용할 임베딩은 유한한 실수로만 구성되어야 한다."""
    if any(not math.isfinite(number) for number in value):
        raise ValueError("embedding values must be finite numbers")
    return value


def _strip_string(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class MemoryConversationHistoryMessage(ConversationHistoryMessage):
    model_config = ConfigDict(extra="forbid")

    occurredAt: datetime

    @field_validator("occurredAt")
    @classmethod
    def occurred_at_must_include_timezone(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)


class MemoryCandidatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: int = Field(gt=0)
    characterId: FreeTalkCharacter
    targetLocale: str
    baseLocale: str
    timezone: str
    conversationHistory: list[MemoryConversationHistoryMessage] = Field(min_length=1)
    # 아래 셋은 후속 질문 생성에만 쓰고 후보 추출·중복 판단에는 쓰지 않는다
    existingMemories: list["MemoryContext"] = Field(default_factory=list, max_length=20)
    askedMemoryIds: list[int] = Field(default_factory=list)
    sessionEndedBy: FreeTalkClosingReason | None = None

    @field_validator("targetLocale", "baseLocale", "timezone")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_supported(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a supported IANA timezone") from exc
        return value

    @field_validator("askedMemoryIds")
    @classmethod
    def asked_memory_ids_must_be_unique(cls, value: list[int]) -> list[int]:
        return _validate_unique_positive_ids(value)

    @model_validator(mode="after")
    def history_must_contain_user_message(self) -> Self:
        """후보 추출의 계보를 보장하려면 USER 원문이 하나 이상 필요하다."""
        if all(message.role != "USER" for message in self.conversationHistory):
            raise ValueError("conversation history requires at least one user message")
        return self


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidateIndex: int = Field(ge=0)
    memoryType: MemoryType
    content: str = Field(max_length=500)
    contentLocale: str
    sourceMessageIds: list[int] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    validFrom: datetime | None = None
    validTo: datetime | None = None
    embeddingModel: str
    embedding: list[float] = Field(min_length=1536, max_length=1536)

    @field_validator("content", mode="before")
    @classmethod
    def content_must_be_trimmed(cls, value: object) -> object:
        return _strip_string(value)

    @field_validator("content", "contentLocale", "embeddingModel")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("sourceMessageIds")
    @classmethod
    def source_ids_must_be_unique(cls, value: list[int]) -> list[int]:
        return _validate_unique_positive_ids(value)

    @field_validator("validFrom", "validTo")
    @classmethod
    def validity_times_must_include_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        return _validate_timezone_aware(value)

    @field_validator("embedding")
    @classmethod
    def embedding_values_must_be_finite(cls, value: list[float]) -> list[float]:
        return _validate_finite_embedding(value)

    @model_validator(mode="after")
    def validity_range_must_be_ordered(self) -> Self:
        """기억의 유효 종료 시각은 시작 시각보다 앞설 수 없다."""
        if (
            self.validFrom is not None
            and self.validTo is not None
            and self.validTo < self.validFrom
        ):
            raise ValueError("validTo must not be earlier than validFrom")
        return self


class FollowUpQuestion(BaseModel):
    """다음 스몰톡에서 캐릭터가 이어 물을 질문. 근거는 기존 기억이나 이번 후보 중 하나뿐이다."""

    model_config = ConfigDict(extra="forbid")

    memoryId: int | None = Field(default=None, gt=0)
    candidateIndex: int | None = Field(default=None, ge=0)
    triggerType: FollowUpTriggerType
    question: str
    invite: str

    @field_validator("question", "invite")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @model_validator(mode="after")
    def source_must_match_trigger(self) -> Self:
        has_memory = self.memoryId is not None
        has_candidate = self.candidateIndex is not None
        if self.triggerType == FollowUpTriggerType.NONE:
            if has_memory or has_candidate:
                raise ValueError("NONE follow-up must not reference a memory")
        elif has_memory == has_candidate:
            raise ValueError("follow-up requires exactly one of memoryId and candidateIndex")
        return self


class MemoryCandidatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extractorVersion: str
    candidates: list[MemoryCandidate] = Field(max_length=5)
    followUpQuestion: FollowUpQuestion

    @field_validator("extractorVersion")
    @classmethod
    def extractor_version_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class MemoryCandidateForResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidateIndex: int = Field(ge=0)
    content: str = Field(max_length=500)
    memoryType: MemoryType
    sourceMessageIds: list[int] = Field(min_length=1)
    sourceMessages: list[MemoryConversationHistoryMessage] = Field(default_factory=list)
    observedAt: datetime
    comparableMemories: list["ComparableMemory"] = Field(max_length=3)

    @field_validator("content", mode="before")
    @classmethod
    def content_must_be_trimmed(cls, value: object) -> object:
        return _strip_string(value)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("sourceMessageIds")
    @classmethod
    def source_ids_must_be_unique(cls, value: list[int]) -> list[int]:
        return _validate_unique_positive_ids(value)

    @field_validator("observedAt")
    @classmethod
    def observed_at_must_include_timezone(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)


class ComparableMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memoryId: int = Field(gt=0)
    content: str = Field(max_length=500)
    validFrom: datetime | None = None
    validTo: datetime | None = None
    observedAt: datetime

    @field_validator("content", mode="before")
    @classmethod
    def content_must_be_trimmed(cls, value: object) -> object:
        return _strip_string(value)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("validFrom", "validTo", "observedAt")
    @classmethod
    def times_must_include_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _validate_timezone_aware(value)

    @model_validator(mode="after")
    def validity_range_must_be_ordered(self) -> Self:
        """비교 기억의 유효 종료 시각은 시작 시각보다 앞설 수 없다."""
        if (
            self.validFrom is not None
            and self.validTo is not None
            and self.validTo < self.validFrom
        ):
            raise ValueError("validTo must not be earlier than validFrom")
        return self


class MemoryResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[MemoryCandidateForResolution] = Field(min_length=1, max_length=5)


class MemoryResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidateIndex: int = Field(ge=0)
    operation: MemoryOperation
    supersededMemoryIds: list[int] = Field(default_factory=list)

    @field_validator("supersededMemoryIds")
    @classmethod
    def superseded_ids_must_be_unique(cls, value: list[int]) -> list[int]:
        return _validate_unique_positive_ids(value)

    @model_validator(mode="after")
    def superseded_ids_must_match_operation(self) -> Self:
        """기존 기억을 참조하는 ID는 SUPERSEDE 연산에서만 허용한다."""
        if self.operation == MemoryOperation.SUPERSEDE:
            if not self.supersededMemoryIds:
                raise ValueError("SUPERSEDE requires superseded memory IDs")
        elif self.supersededMemoryIds:
            raise ValueError("only SUPERSEDE may contain superseded memory IDs")
        return self


class MemoryResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolutions: list[MemoryResolution] = Field(min_length=1, max_length=5)


class MemoryQueryEmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(max_length=2000)

    @field_validator("query", mode="before")
    @classmethod
    def query_must_be_trimmed(cls, value: object) -> object:
        return _strip_string(value)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class MemoryQueryEmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embeddingModel: str
    embedding: list[float] = Field(min_length=1536, max_length=1536)

    @field_validator("embeddingModel")
    @classmethod
    def embedding_model_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("embedding")
    @classmethod
    def embedding_values_must_be_finite(cls, value: list[float]) -> list[float]:
        return _validate_finite_embedding(value)


class FreeTalkTopicContext(BaseModel):
    topicId: int | None = Field(default=None, gt=0)
    title: str
    promptDescription: str | None = None

    @field_validator("title", "promptDescription")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_not_blank(value)


class FreeTalkContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: int = Field(gt=0)
    characterId: FreeTalkCharacter
    targetLocale: str
    baseLocale: str
    timezone: str = "Asia/Seoul"
    topic: FreeTalkTopicContext | None = None

    @field_validator("topic", mode="before")
    @classmethod
    def all_null_topic_must_be_treated_as_absent(cls, value: object) -> object:
        topic_fields = {"topicId", "title", "promptDescription"}
        if (
            isinstance(value, dict)
            and set(value).issubset(topic_fields)
            and all(value.get(field) is None for field in topic_fields)
        ):
            return None
        return value

    @field_validator(
        "targetLocale",
        "baseLocale",
    )
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_supported(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a supported IANA timezone") from exc
        return value


class MemoryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memoryId: int = Field(gt=0)
    memoryType: MemoryType
    content: str = Field(max_length=500)
    validFrom: datetime | None = None
    validTo: datetime | None = None
    observedAt: datetime | None = None

    @field_validator("content", mode="before")
    @classmethod
    def content_must_be_trimmed(cls, value: object) -> object:
        return _strip_string(value)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class PendingFollowUp(BaseModel):
    """지난 스몰톡이 끝날 때 만들어 두고 아직 묻지 않은 후속 질문."""

    model_config = ConfigDict(extra="forbid")

    followUpId: int = Field(gt=0)
    memoryId: int | None = Field(default=None, gt=0)
    triggerType: FollowUpTriggerType
    question: str

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("triggerType")
    @classmethod
    def trigger_type_must_be_askable(cls, value: FollowUpTriggerType) -> FollowUpTriggerType:
        if value == FollowUpTriggerType.NONE:
            raise ValueError("pending follow-up requires an askable trigger type")
        return value


class FreeTalkOpeningRequest(FreeTalkContext):
    memoryContext: list["MemoryContext"] = Field(default_factory=list, max_length=3)
    pendingFollowUp: PendingFollowUp | None = None

    @model_validator(mode="after")
    def topic_must_be_complete(self) -> Self:
        if (
            self.topic is None
            or self.topic.topicId is None
            or self.topic.promptDescription is None
        ):
            raise ValueError("opening request requires a complete topic")
        return self


class FreeTalkOpeningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aiMessage: str
    translatedMessage: str
    emotion: Emotion | None
    usedMemoryIds: list[int] = Field(default_factory=list, max_length=3)
    followUpAsked: bool = False
    followUpId: int | None = Field(default=None, gt=0)

    @field_validator("usedMemoryIds")
    @classmethod
    def used_memory_ids_must_be_unique(cls, value: list[int]) -> list[int]:
        return _validate_unique_positive_ids(value)

    @field_validator("aiMessage", "translatedMessage")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class FreeTalkTurnRequest(FreeTalkContext):
    submittedMessageId: int = Field(gt=0)
    submittedTurnNumber: int = Field(gt=0)
    responseMode: FreeTalkResponseMode
    isFirstUserTurn: bool
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=1)
    memoryContext: list["MemoryContext"] = Field(default_factory=list, max_length=3)
    pendingFollowUp: PendingFollowUp | None = None

    @model_validator(mode="after")
    def submitted_message_must_match_latest_history(self) -> Self:
        latest_message = self.conversationHistory[-1]
        if (
            latest_message.role != "USER"
            or latest_message.messageId != self.submittedMessageId
            or latest_message.turnNumber != self.submittedTurnNumber
        ):
            raise ValueError("submitted message must match latest user history")
        return self

    @model_validator(mode="after")
    def pending_follow_up_requires_first_user_turn(self) -> Self:
        """오프닝이 없는 USER_FIRST 세션의 첫 턴만 후속 질문을 꺼낼 수 있다."""
        if self.pendingFollowUp is not None and not self.isFirstUserTurn:
            raise ValueError("pending follow-up is only allowed on the first user turn")
        return self


class FreeTalkTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    userExitIntentDetected: bool
    inferredTitle: str | None
    aiMessage: str | None
    translatedMessage: str | None
    emotion: Emotion | None
    usedMemoryIds: list[int] = Field(default_factory=list, max_length=3)
    followUpAsked: bool = False
    followUpId: int | None = Field(default=None, gt=0)

    @field_validator("inferredTitle", "aiMessage", "translatedMessage")
    @classmethod
    def optional_text_fields_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_not_blank(value)

    @model_validator(mode="after")
    def conditional_fields_must_match_exit_intent(self) -> Self:
        generated_fields = (
            self.aiMessage,
            self.translatedMessage,
        )
        if self.userExitIntentDetected:
            if any(field is not None for field in generated_fields):
                raise ValueError("exit intent response must not contain generated fields")
        elif any(field is None for field in generated_fields):
            raise ValueError("normal response requires generated fields")
        return self


class FreeTalkInnerThoughtRequest(FreeTalkContext):
    submittedMessageId: int = Field(gt=0)
    submittedTurnNumber: int = Field(gt=0)
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=1)
    # 턴 교정의 근거로만 쓰고 속마음 판정에는 넘기지 않는다
    memoryContext: list["MemoryContext"] = Field(default_factory=list, max_length=3)
    # 직전 세션에서 교정받은 실수 패턴. 턴 교정 호출에만 넘기고, 비어 있으면 그 호출은 기존과 같다
    watchPatterns: list[FreeTalkMistakePattern] = Field(default_factory=list, max_length=3)

    @field_validator("watchPatterns")
    @classmethod
    def watch_patterns_must_be_unique(
        cls, value: list[FreeTalkMistakePattern]
    ) -> list[FreeTalkMistakePattern]:
        if len(value) != len(set(value)):
            raise ValueError("watchPatterns must be unique")
        return value

    @model_validator(mode="after")
    def submitted_message_must_match_latest_history(self) -> Self:
        latest_message = self.conversationHistory[-1]
        if (
            latest_message.role != "USER"
            or latest_message.messageId != self.submittedMessageId
            or latest_message.turnNumber != self.submittedTurnNumber
        ):
            raise ValueError("submitted message must match latest user history")
        return self


class FreeTalkCorrection(BaseModel):
    """사용자 턴에서 고른 한 문장의 교정. originalSentence는 제출 메시지 원문의 일부여야 한다."""

    model_config = ConfigDict(extra="forbid")

    originalSentence: str
    betterSentence: str
    reason: str
    mistakePattern: FreeTalkMistakePattern
    # 장기기억이 정답을 바꾼 교정일 때만 그 memoryContext의 기억 ID
    usedMemoryId: int | None = Field(default=None, gt=0)
    # usedMemoryId가 있을 때만. 그 기억이 가리키는 대상을 기준 언어(baseLocale)의 짧은 명사구로.
    # 날짜와 "스몰톡에서 말한" 같은 틀 문구는 백엔드가 붙인다.
    memoryLabel: str | None = None
    # 화면에서 색칠할 구절. 각 문장 안에 단어 경계 기준으로 정확히 한 번 나오는 부분 문자열이다.
    # 빠진 단어를 채운 교정은 wrongSpan이, 단어를 지운 교정은 betterSpan이 null이다.
    wrongSpan: str | None = None
    betterSpan: str | None = None

    @field_validator("originalSentence", "betterSentence", "reason")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class FreeTalkPatternUsage(BaseModel):
    """지켜볼 실수 패턴이 이번 턴에 등장한 사용례 하나. span은 sentence의, sentence는 제출 메시지의 일부다."""

    model_config = ConfigDict(extra="forbid")

    pattern: FreeTalkMistakePattern
    sentence: str
    span: str
    correct: bool


class FreeTalkInnerThoughtResponse(BaseModel):
    """속마음과 함께 턴 교정 판정을 담는다.

    reactedToPartner와 correction은 교정 판정이 실패·타임아웃하면 둘 다 null이다.
    고칠 게 없을 때는 correction만 null이고 reactedToPartner는 채워진다.
    patternUsages는 지켜볼 패턴이 없거나 판정이 실패하면 null이고, 판정했는데 등장하지 않았으면 빈 목록이다.
    """

    model_config = ConfigDict(extra="forbid")

    innerThought: str
    innerThoughtType: InnerThoughtType
    reactedToPartner: bool | None
    correction: FreeTalkCorrection | None
    patternUsages: list[FreeTalkPatternUsage] | None

    @field_validator("innerThought")
    @classmethod
    def inner_thought_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class FreeTalkClosingRequest(FreeTalkContext):
    submittedMessageId: int = Field(gt=0)
    submittedTurnNumber: int = Field(gt=0)
    closingReason: FreeTalkClosingReason
    titleGenerationRequired: bool = False
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=1)

    @model_validator(mode="after")
    def submitted_message_must_match_latest_history(self) -> Self:
        latest_message = self.conversationHistory[-1]
        if (
            latest_message.role != "USER"
            or latest_message.messageId != self.submittedMessageId
            or latest_message.turnNumber != self.submittedTurnNumber
        ):
            raise ValueError("submitted message must match latest user history")
        return self


class FreeTalkClosingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inferredTitle: str | None = None
    aiMessage: str
    translatedMessage: str
    emotion: Emotion | None

    @field_validator("inferredTitle", "aiMessage", "translatedMessage")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_not_blank(value)


class ExistingExpression(BaseModel):
    expressionId: int = Field(gt=0)
    targetExpressionText: str
    baseExpressionMeaningText: str
    usageSummary: str

    @field_validator(
        "targetExpressionText",
        "baseExpressionMeaningText",
        "usageSummary",
    )
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class LearnedExpression(BaseModel):
    """백엔드가 추린, 사용자가 이전에 학습 완료한 표현 후보."""

    model_config = ConfigDict(extra="forbid")

    expressionId: int = Field(gt=0)
    targetExpressionText: str
    baseExpressionMeaningText: str

    @field_validator("targetExpressionText", "baseExpressionMeaningText")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class ExpressionRecommendationsRequest(BaseModel):
    sessionId: int = Field(gt=0)
    targetLocale: str
    baseLocale: str
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=1)
    existingExpressions: list[ExistingExpression]
    learnedExpressions: list[LearnedExpression] = Field(default_factory=list, max_length=50)

    @field_validator("targetLocale", "baseLocale")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("learnedExpressions")
    @classmethod
    def learned_expression_ids_must_be_unique(
        cls,
        value: list[LearnedExpression],
    ) -> list[LearnedExpression]:
        _validate_unique_positive_ids([expression.expressionId for expression in value])
        return value


class ExpressionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayOrder: int = Field(gt=0)
    existingExpressionId: int = Field(gt=0)
    targetExpressionText: str
    baseExpressionMeaningText: str
    usageSummary: str

    @field_validator(
        "targetExpressionText",
        "baseExpressionMeaningText",
        "usageSummary",
    )
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

class UsedExpression(BaseModel):
    """이번 대화에서 실제로 쓴 학습 표현. matchedText는 해당 USER 메시지 원문의 일부여야 한다."""

    model_config = ConfigDict(extra="forbid")

    expressionId: int = Field(gt=0)
    messageId: int = Field(gt=0)
    matchedText: str

    @field_validator("matchedText")
    @classmethod
    def matched_text_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class ExpressionRecommendationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[ExpressionRecommendation] = Field(min_length=1, max_length=3)
    usedExpressions: list[UsedExpression] = Field(default_factory=list)


class ConversationEmbeddingsRequest(BaseModel):
    sessionId: int = Field(gt=0)
    targetLocale: str
    baseLocale: str
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=1)

    @field_validator("targetLocale", "baseLocale")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @model_validator(mode="after")
    def history_must_contain_user_message(self) -> Self:
        if all(message.role != "USER" for message in self.conversationHistory):
            raise ValueError("conversation history requires at least one user message")
        return self


class ConversationExcerpt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    excerptText: str
    embedding: list[float] = Field(min_length=1536, max_length=1536)

    @field_validator("excerptText")
    @classmethod
    def excerpt_text_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class ConversationEmbeddingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    excerpts: list[ConversationExcerpt] = Field(min_length=1, max_length=4)
