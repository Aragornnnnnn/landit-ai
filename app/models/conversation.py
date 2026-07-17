# 대화 생성 API 요청과 응답 DTO를 정의하는 모듈
import re
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_CORRECTION_EXPRESSION_PLACEHOLDER_PATTERN = re.compile(
    r"\[([^\[\]]+)\]",
)
_CORRECTION_EXPRESSION_PLACEHOLDER_LINE_BREAK_PATTERN = re.compile(
    r"[ \t]*[\r\n]+[ \t]*",
)
CORRECTION_EXPRESSION_PLACEHOLDER_PROMPT_RULE = (
    "Use [your <specific label>] placeholders only. "
    "A placeholder label must be non-empty and cannot contain brackets or line breaks. "
    "Hyphens, uppercase letters, and numbers are allowed."
)


def _validate_not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _optional_not_blank(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_not_blank(value)


def correction_expression_placeholder_labels(value: str) -> list[str]:
    return _CORRECTION_EXPRESSION_PLACEHOLDER_PATTERN.findall(value)


def normalize_correction_expression_placeholders(value: str) -> str:
    def normalize_placeholder(match: re.Match[str]) -> str:
        label = _CORRECTION_EXPRESSION_PLACEHOLDER_LINE_BREAK_PATTERN.sub(
            " ",
            match.group(1),
        ).strip()
        if label.startswith("your "):
            return f"[{label}]"
        return f"[your {label}]"

    return _CORRECTION_EXPRESSION_PLACEHOLDER_PATTERN.sub(
        normalize_placeholder,
        value,
    )


def has_supported_correction_expression_placeholders(value: str) -> bool:
    labels = correction_expression_placeholder_labels(value)
    unparsed_value = _CORRECTION_EXPRESSION_PLACEHOLDER_PATTERN.sub("", value)
    return (
        "[" not in unparsed_value
        and "]" not in unparsed_value
        and all(
            label.startswith("your ") and label.removeprefix("your ").strip()
            and "\r" not in label
            and "\n" not in label
            for label in labels
        )
    )


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


class AnswerCoverage(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DECLINED = "DECLINED"
    UNRELATED = "UNRELATED"


class RelationshipTone(StrEnum):
    WARM = "WARM"
    NEUTRAL = "NEUTRAL"
    BLUNT = "BLUNT"
    HOSTILE = "HOSTILE"


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
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FeedbackType(StrEnum):
    GOOD = "GOOD"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"


class EvaluationContextType(StrEnum):
    AI_MESSAGE = "AI_MESSAGE"
    SCENARIO_OPENING_INSTRUCTION = "SCENARIO_OPENING_INSTRUCTION"


class NextMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aiMessage: str
    translatedMessage: str
    goalCompletionStatus: GoalCompletionStatus

    @field_validator("aiMessage", "translatedMessage")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class InnerThoughtRequest(BaseModel):
    sessionId: int = Field(gt=0)
    submittedMessageId: int = Field(gt=0)
    submittedTurnNumber: int = Field(gt=0)
    scenario: ScenarioContext
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


class InnerThoughtData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    innerThought: str
    innerThoughtType: InnerThoughtType

    @field_validator("innerThought")
    @classmethod
    def inner_thought_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class InnerThoughtCandidate(InnerThoughtData):
    answerCoverage: AnswerCoverage
    relationshipTone: RelationshipTone
    directedAttack: bool


class InnerThoughtResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: int = Field(gt=0)
    messageId: int = Field(gt=0)
    innerThought: str
    innerThoughtType: InnerThoughtType

    @field_validator("innerThought")
    @classmethod
    def inner_thought_must_not_be_blank(cls, value: str) -> str:
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
        "한국어로는",
        "한국어로도",
    )
    for prefix in framing_prefixes:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].lstrip(" ,，:：")
    return stripped


class EvaluationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EvaluationContextType
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


class MessageFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: int = Field(gt=0)
    messageId: int = Field(gt=0)
    turnNumber: int = Field(gt=0)
    messageSequence: int = Field(gt=0)
    scenario: ScenarioContext
    evaluationContext: EvaluationContext
    userMessage: str

    @field_validator("userMessage")
    @classmethod
    def user_message_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)

    @model_validator(mode="after")
    def opening_instruction_fields_must_be_valid(self) -> Self:
        if (
            self.evaluationContext.type
            != EvaluationContextType.SCENARIO_OPENING_INSTRUCTION
        ):
            return self
        if self.turnNumber != 1:
            raise ValueError("opening instruction requires turnNumber 1")
        if self.evaluationContext.translatedContent is not None:
            raise ValueError("opening instruction translatedContent must be null")
        return self


class MessageFeedbackResponse(BaseModel):
    sessionId: int = Field(gt=0)
    messageId: int = Field(gt=0)
    feedbackStatus: FeedbackStatus


class MessageFeedbackContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

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

    @field_validator("correctionExpression")
    @classmethod
    def correction_expression_placeholders_must_use_supported_format(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        if not has_supported_correction_expression_placeholders(value):
            raise ValueError("correctionExpression placeholders must use [your ...] format")
        return value

    @field_validator("correctionReason")
    @classmethod
    def correction_reason_must_not_expose_internal_policy(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None and any(
            marker in value
            for marker in ("없는 사실", "사실을 만들지", "임의로 추측")
        ):
            raise ValueError(
                "correctionReason must not expose internal generation policy",
            )
        return value


class MessageFeedbackData(MessageFeedbackContent):
    messageId: int = Field(gt=0)
    feedbackType: FeedbackType

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


class MessageFeedbackScoreEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contextFit: int = Field(strict=True, ge=0, le=2)
    clarity: int = Field(strict=True, ge=0, le=2)
    languageAccuracy: int = Field(strict=True, ge=0, le=2)


class MessageFeedbackCandidate(MessageFeedbackContent):
    scoreEvidence: MessageFeedbackScoreEvidence


class SessionFeedbackRequest(BaseModel):
    sessionId: int = Field(gt=0)
    scenario: ScenarioContext
    expectedMessageIds: list[int]

    @field_validator("expectedMessageIds")
    @classmethod
    def expected_message_ids_must_be_valid(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("expectedMessageIds must not be empty")
        if any(message_id <= 0 for message_id in value):
            raise ValueError("expectedMessageIds must contain positive ids")
        if len(value) != len(set(value)):
            raise ValueError("expectedMessageIds must not contain duplicates")
        return value


class SessionFeedbackSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sessionId: int = Field(gt=0)
    highlightMessage: str
    summaryMessage: str

    @field_validator("highlightMessage", "summaryMessage")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class SessionFeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: int = Field(gt=0)
    nativeScore: int = Field(ge=0, le=100)
    starRating: float
    highlightMessage: str
    summaryMessage: str
    messageFeedbacks: list[MessageFeedbackData]

    @field_validator("starRating")
    @classmethod
    def star_rating_must_be_supported_value(cls, value: float) -> float:
        if value not in {1.0, 1.5, 2.0, 2.5, 3.0}:
            raise ValueError("starRating must be one of 1.0, 1.5, 2.0, 2.5, 3.0")
        return value

    @field_validator("highlightMessage", "summaryMessage")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)
