# 프리톡 대화 생성 요청을 LLM JSON 응답으로 변환하는 유스케이스 모듈
import json
import re

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.free_talk.domain.rules import derive_inner_thought_type
from app.free_talk.llm.json_completion import (
    AiGenerationFailedError,
    AiResponseInvalidError,
    request_json_completion,
)
from app.models.conversation import AnswerCoverage, RelationshipTone
from app.models.free_talk import (
    Emotion,
    FreeTalkClosingRequest,
    FreeTalkClosingResponse,
    FreeTalkOpeningRequest,
    FreeTalkOpeningResponse,
    FreeTalkResponseMode,
    FreeTalkTurnRequest,
    FreeTalkTurnResponse,
)


_KOREAN_TITLE_PATTERN = re.compile(r"[가-힣0-9\s·-]+$")
_PROHIBITED_INNER_THOUGHT_PATTERN = re.compile(
    r"문법|자연스러(?:움|운)|점수|교정|피드백|"
    r"grammar|naturalness|score|correction|feedback",
    re.IGNORECASE,
)
_CLOSING_META_PATTERN = re.compile(
    r"\b(?:feedback|scores?)\b|"
    r"\b(?:this|the|our)\s+(?:session|conversation)\s+"
    r"(?:has\s+)?(?:ended|ends|is\s+ending|finished|is\s+over)\b|"
    r"(?:피드백|점수)|(?:세션|대화).*(?:종료|끝(?:났|나|낼)|마무리)",
    re.IGNORECASE,
)
_NEW_TOPIC_CLOSING_PATTERN = re.compile(
    r"\b(?:let's|let us|we can|we should)\s+"
    r"(?:talk|chat|discuss|learn)\s+about\b|"
    r"\b(?:new|another)\s+topic\b|"
    r"(?:그런데|참|다음(?:에|에는)).*(?:얘기|이야기|대화|주제).*(?:하자|해|할)|"
    r"(?:새|다른)\s*주제",
    re.IGNORECASE,
)


class _TurnCandidate(BaseModel):
    userExitIntentDetected: bool | None = None
    inferredTitle: str | None = None
    aiMessage: str | None = None
    translatedMessage: str | None = None
    emotion: Emotion | None = None
    innerThought: str | None = None
    innerThoughtType: object | None = None
    answerCoverage: AnswerCoverage | None = None
    relationshipTone: RelationshipTone | None = None
    directedAttack: bool | None = None


class _ClosingCandidate(BaseModel):
    aiMessage: str
    translatedMessage: str
    emotion: Emotion
    innerThought: str
    answerCoverage: AnswerCoverage
    relationshipTone: RelationshipTone
    directedAttack: bool


def generate_opening(
    payload: FreeTalkOpeningRequest,
    settings: Settings,
) -> FreeTalkOpeningResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_opening_system_prompt(),
        user_prompt=_opening_user_prompt(payload),
    )
    try:
        return FreeTalkOpeningResponse.model_validate(data)
    except ValidationError as exc:
        raise AiResponseInvalidError from exc


def generate_turn(
    payload: FreeTalkTurnRequest,
    settings: Settings,
) -> FreeTalkTurnResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_turn_system_prompt(payload.responseMode),
        user_prompt=_turn_user_prompt(payload),
    )
    try:
        candidate = _TurnCandidate.model_validate(data)
        _validate_inferred_title(candidate.inferredTitle, payload.isFirstUserTurn)
        if payload.responseMode == FreeTalkResponseMode.NORMAL:
            if candidate.userExitIntentDetected is None:
                raise ValueError("normal turn requires exit intent")
            exit_detected = candidate.userExitIntentDetected
        else:
            exit_detected = False
        if exit_detected:
            return FreeTalkTurnResponse(
                userExitIntentDetected=True,
                inferredTitle=(
                    candidate.inferredTitle if payload.isFirstUserTurn else None
                ),
                aiMessage=candidate.aiMessage,
                translatedMessage=candidate.translatedMessage,
                emotion=candidate.emotion,
                innerThought=candidate.innerThought,
                innerThoughtType=candidate.innerThoughtType,
            )
        _validate_inner_thought(candidate.innerThought)
        return FreeTalkTurnResponse(
            userExitIntentDetected=False,
            inferredTitle=(
                candidate.inferredTitle if payload.isFirstUserTurn else None
            ),
            aiMessage=candidate.aiMessage,
            translatedMessage=candidate.translatedMessage,
            emotion=candidate.emotion,
            innerThought=candidate.innerThought,
            innerThoughtType=derive_inner_thought_type(
                _required_evidence(candidate.answerCoverage),
                _required_evidence(candidate.relationshipTone),
                _required_evidence(candidate.directedAttack),
            ),
        )
    except (TypeError, ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc


def generate_closing(
    payload: FreeTalkClosingRequest,
    settings: Settings,
) -> FreeTalkClosingResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_closing_system_prompt(),
        user_prompt=_closing_user_prompt(payload),
    )
    try:
        candidate = _ClosingCandidate.model_validate(data)
        response = FreeTalkClosingResponse(
            aiMessage=candidate.aiMessage,
            translatedMessage=candidate.translatedMessage,
            emotion=candidate.emotion,
            innerThought=candidate.innerThought,
            innerThoughtType=derive_inner_thought_type(
                candidate.answerCoverage,
                candidate.relationshipTone,
                candidate.directedAttack,
            ),
        )
    except ValidationError as exc:
        raise AiResponseInvalidError from exc
    if _is_invalid_closing_message(response.aiMessage) or _is_invalid_closing_message(
        response.translatedMessage,
    ):
        raise AiResponseInvalidError("closing message violates policy")
    return response


def _required_evidence(value: object) -> object:
    if value is None:
        raise ValueError("normal turn requires evaluation evidence")
    return value


def _validate_inferred_title(
    title: str | None,
    is_first_user_turn: bool,
) -> None:
    if not is_first_user_turn:
        if title is not None:
            raise ValueError("only the first user turn may infer a title")
        return
    if (
        title is None
        or not title.strip()
        or len(title.strip()) > 30
        or _KOREAN_TITLE_PATTERN.fullmatch(title.strip()) is None
    ):
        raise ValueError("first user turn requires a short Korean inferred title")


def _validate_inner_thought(inner_thought: str | None) -> None:
    if (
        inner_thought is None
        or _PROHIBITED_INNER_THOUGHT_PATTERN.search(inner_thought) is not None
    ):
        raise ValueError("inner thought must not include feedback language")


def _opening_system_prompt() -> str:
    return (
        "Generate one natural opening question for an English free talk. "
        "Return only JSON with aiMessage, translatedMessage, and emotion. "
        "emotion must be NEUTRAL, HAPPY, SURPRISED, SAD, or ANGRY."
    )


def _turn_system_prompt(response_mode: FreeTalkResponseMode) -> str:
    exit_policy = (
        "Decide whether the user clearly wants to end the conversation."
        if response_mode == FreeTalkResponseMode.NORMAL
        else "The user declined ending. Do not judge exit intent."
    )
    return (
        "Generate one free-talk turn as JSON. "
        f"{exit_policy} "
        "When userExitIntentDetected is true, leave all generated message fields null. "
        "Otherwise return aiMessage, translatedMessage, emotion, innerThought, "
        "answerCoverage, relationshipTone, and directedAttack. "
        "For a first user turn, inferredTitle must be a short Korean title; "
        "for later turns, inferredTitle must be null. "
        "answerCoverage is COMPLETE, PARTIAL, DECLINED, or UNRELATED. "
        "relationshipTone is WARM, NEUTRAL, BLUNT, or HOSTILE. "
        "innerThought is a private reaction only. Do not mention grammar, naturalness, "
        "scores, corrections, feedback, or learning advice."
    )


def _closing_system_prompt() -> str:
    return (
        "Generate a natural final free-talk message as JSON. Do not ask a question, "
        "introduce a new topic, invite another topic, mention scores or feedback, "
        "ask the user to review feedback, or announce that a session/conversation has ended. "
        "Return aiMessage, translatedMessage, emotion, innerThought, answerCoverage, "
        "relationshipTone, and directedAttack."
    )


def _opening_user_prompt(payload: FreeTalkOpeningRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _turn_user_prompt(payload: FreeTalkTurnRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _closing_user_prompt(payload: FreeTalkClosingRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _is_invalid_closing_message(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", message).strip()
    return (
        normalized.endswith(("?", "？"))
        or _CLOSING_META_PATTERN.search(normalized) is not None
        or _NEW_TOPIC_CLOSING_PATTERN.search(normalized) is not None
    )
