# 대화 생성 API 요청과 응답 DTO를 정의하는 모듈
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _optional_not_blank(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_not_blank(value)


class ScenarioContext(BaseModel):
    scenarioId: int = Field(gt=0)
    title: str
    briefing: str
    conversationGoal: str
    counterpartRole: str
    serviceAudience: str = "KOREAN_LEARNER"

    @field_validator(
        "title",
        "briefing",
        "conversationGoal",
        "counterpartRole",
        "serviceAudience",
    )
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class ConversationHistoryMessage(BaseModel):
    messageId: int = Field(gt=0)
    turnNumber: int = Field(gt=0)
    role: Literal["AI", "USER"]
    content: str
    translatedContent: str | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("translatedContent")
    @classmethod
    def translated_content_must_not_be_blank(cls, value: str | None) -> str | None:
        return _optional_not_blank(value)


class NextFixedQuestion(BaseModel):
    questionId: int = Field(gt=0)
    sequence: int = Field(gt=0)
    questionEn: str
    questionKo: str

    @field_validator("questionEn", "questionKo")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class NextMessageRequest(BaseModel):
    sessionId: int = Field(gt=0)
    submittedMessageId: int = Field(gt=0)
    submittedTurnNumber: int = Field(gt=0)
    scenario: ScenarioContext
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=1)
    nextQuestion: NextFixedQuestion

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


class InnerThoughtType(StrEnum):
    GOOD = "GOOD"
    NORMAL = "NORMAL"
    BAD = "BAD"


class GoalCompletionStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"


class NextMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aiMessage: str
    translatedMessage: str
    innerThought: str
    innerThoughtType: InnerThoughtType
    goalCompletionStatus: GoalCompletionStatus

    @field_validator("aiMessage", "translatedMessage", "innerThought")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)
