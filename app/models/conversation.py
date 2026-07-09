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


class ClosingReason(StrEnum):
    GOAL_COMPLETED = "GOAL_COMPLETED"
    MAX_TURNS_REACHED = "MAX_TURNS_REACHED"
    USER_ENDED = "USER_ENDED"
    TIME_LIMIT_REACHED = "TIME_LIMIT_REACHED"


class FeedbackStatus(StrEnum):
    PREPARING = "PREPARING"
    READY = "READY"
    FAILED = "FAILED"


class FeedbackType(StrEnum):
    GOOD = "GOOD"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"


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


class ClosingMessageRequest(BaseModel):
    sessionId: int = Field(gt=0)
    submittedMessageId: int = Field(gt=0)
    submittedTurnNumber: int = Field(gt=0)
    scenario: ScenarioContext
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=2)
    closingReason: ClosingReason
    goalCompletionStatus: GoalCompletionStatus

    @model_validator(mode="after")
    def submitted_message_must_match_latest_turn(self) -> Self:
        latest_message = self.conversationHistory[-1]
        previous_message = self.conversationHistory[-2]
        if (
            latest_message.role != "USER"
            or latest_message.messageId != self.submittedMessageId
            or latest_message.turnNumber != self.submittedTurnNumber
            or previous_message.role != "AI"
        ):
            raise ValueError("closing turn must end with submitted user message after AI message")
        return self


class ClosingMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aiMessage: str
    translatedMessage: str
    innerThought: str
    innerThoughtType: InnerThoughtType

    @field_validator("aiMessage", "translatedMessage", "innerThought")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


def _strip_base_locale_analogy_framing(value: str) -> str:
    stripped = value.strip()
    framing_prefixes = (
        "한국어로 비유하자면",
        "한국어로 비유하면",
        "한국어로 치면",
    )
    for prefix in framing_prefixes:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].lstrip(" ,，:：")
    return stripped


class MessageContext(BaseModel):
    aiMessage: str
    aiMessageTranslation: str | None = None
    userMessage: str

    @field_validator("aiMessage", "userMessage")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @field_validator("aiMessageTranslation")
    @classmethod
    def translated_message_must_not_be_blank(cls, value: str | None) -> str | None:
        return _optional_not_blank(value)


class MessageFeedbackRequest(BaseModel):
    sessionId: int = Field(gt=0)
    messageId: int = Field(gt=0)
    turnNumber: int = Field(gt=0)
    messageSequence: int = Field(gt=0)
    scenario: ScenarioContext
    messageContext: MessageContext


class MessageFeedbackResponse(BaseModel):
    sessionId: int = Field(gt=0)
    messageId: int = Field(gt=0)
    feedbackStatus: FeedbackStatus


class MessageFeedbackData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messageId: int = Field(gt=0)
    feedbackType: FeedbackType
    baseLocaleAnalogy: str
    positiveFeedback: str | None = None
    feedbackDetail: str | None = None
    correctionExpression: str | None = None
    correctionReason: str | None = None
    benchmarkMessage: str | None = None

    @field_validator("baseLocaleAnalogy")
    @classmethod
    def base_locale_analogy_must_not_be_blank_or_framed(cls, value: str) -> str:
        return _validate_not_blank(_strip_base_locale_analogy_framing(value))

    @field_validator(
        "positiveFeedback",
        "feedbackDetail",
        "correctionExpression",
        "correctionReason",
        "benchmarkMessage",
    )
    @classmethod
    def optional_text_fields_must_not_be_blank(cls, value: str | None) -> str | None:
        return _optional_not_blank(value)

    @model_validator(mode="after")
    def feedback_fields_must_match_type(self) -> Self:
        if self.feedbackType == FeedbackType.NEEDS_IMPROVEMENT:
            if self.positiveFeedback is None:
                raise ValueError("positiveFeedback is required for NEEDS_IMPROVEMENT")
            if self.feedbackDetail is not None:
                raise ValueError("feedbackDetail must be null for NEEDS_IMPROVEMENT")
            if self.correctionExpression is None:
                raise ValueError("correctionExpression is required for NEEDS_IMPROVEMENT")
            if self.correctionReason is None:
                raise ValueError("correctionReason is required for NEEDS_IMPROVEMENT")
            if self.benchmarkMessage is not None:
                raise ValueError("benchmarkMessage must be null for NEEDS_IMPROVEMENT")
            return self

        if self.positiveFeedback is not None:
            raise ValueError("positiveFeedback must be null for GOOD")
        if self.feedbackDetail is None:
            raise ValueError("feedbackDetail is required for GOOD")
        if self.correctionExpression is not None:
            raise ValueError("correctionExpression must be null for GOOD")
        if self.correctionReason is not None:
            raise ValueError("correctionReason must be null for GOOD")
        return self
