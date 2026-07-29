# 프리톡 생성 API의 요청과 응답 모델을 정의하는 모듈
from enum import StrEnum
from typing import Self

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
    targetLocale: str
    baseLocale: str
    topic: FreeTalkTopicContext | None = None

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
    emotion: Emotion

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
            self.emotion,
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
    topic: FreeTalkTopicContext
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

    aiMessage: str
    translatedMessage: str
    emotion: Emotion

    @field_validator("aiMessage", "translatedMessage")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)
