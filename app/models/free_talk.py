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


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value


def _validate_unique_positive_ids(value: list[int]) -> list[int]:
    if any(identifier <= 0 for identifier in value):
        raise ValueError("ids must be positive")
    if len(value) != len(set(value)):
        raise ValueError("ids must be unique")
    return value


def _validate_finite_embedding(value: list[float]) -> list[float]:
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

    @model_validator(mode="after")
    def history_must_contain_user_message(self) -> Self:
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
        if (
            self.validFrom is not None
            and self.validTo is not None
            and self.validTo < self.validFrom
        ):
            raise ValueError("validTo must not be earlier than validFrom")
        return self


class MemoryCandidatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extractorVersion: str
    candidates: list[MemoryCandidate] = Field(max_length=5)

    @field_validator("extractorVersion")
    @classmethod
    def extractor_version_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


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


class FreeTalkOpeningRequest(FreeTalkContext):
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


class FreeTalkTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    userExitIntentDetected: bool
    inferredTitle: str | None
    aiMessage: str | None
    translatedMessage: str | None
    emotion: Emotion | None

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


class FreeTalkInnerThoughtResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    innerThought: str
    innerThoughtType: InnerThoughtType

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


class ExpressionRecommendationsRequest(BaseModel):
    sessionId: int = Field(gt=0)
    targetLocale: str
    baseLocale: str
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=1)
    existingExpressions: list[ExistingExpression]

    @field_validator("targetLocale", "baseLocale")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


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

class ExpressionRecommendationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[ExpressionRecommendation] = Field(min_length=1, max_length=3)


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
