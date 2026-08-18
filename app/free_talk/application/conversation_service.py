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
    FreeTalkCharacter,
    FreeTalkClosingRequest,
    FreeTalkClosingResponse,
    FreeTalkInnerThoughtRequest,
    FreeTalkInnerThoughtResponse,
    FreeTalkOpeningRequest,
    FreeTalkOpeningResponse,
    FreeTalkResponseMode,
    FreeTalkTurnRequest,
    FreeTalkTurnResponse,
)


_KOREAN_TITLE_PATTERN = re.compile(r"[가-힣0-9\s·-]+$")
_KOREAN_CHARACTER_PATTERN = re.compile(r"[가-힣]")
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


class _OpeningCandidate(BaseModel):
    aiMessage: str
    translatedMessage: str
    emotion: object | None = None


class _TurnCandidate(BaseModel):
    userExitIntentDetected: bool | None = None
    inferredTitle: str | None = None
    aiMessage: str | None = None
    translatedMessage: str | None = None
    emotion: object | None = None


class _TurnExitIntentCandidate(BaseModel):
    userExitIntentDetected: bool | None = None


class _ClosingCandidate(BaseModel):
    aiMessage: str
    translatedMessage: str
    emotion: object | None = None


class _InnerThoughtCandidate(BaseModel):
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
        system_prompt=_opening_system_prompt(payload.characterId),
        user_prompt=_opening_user_prompt(payload),
    )
    try:
        candidate = _OpeningCandidate.model_validate(data)
        return FreeTalkOpeningResponse(
            aiMessage=candidate.aiMessage,
            translatedMessage=candidate.translatedMessage,
            emotion=None,
        )
    except ValidationError as exc:
        raise AiResponseInvalidError from exc


def generate_turn(
    payload: FreeTalkTurnRequest,
    settings: Settings,
) -> FreeTalkTurnResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_turn_system_prompt(payload.responseMode, payload.characterId),
        user_prompt=_turn_user_prompt(payload),
    )
    try:
        candidate_data = dict(data)
        if not payload.isFirstUserTurn:
            candidate_data["inferredTitle"] = None
        if payload.responseMode == FreeTalkResponseMode.NORMAL:
            exit_candidate = _TurnExitIntentCandidate.model_validate(data)
            if exit_candidate.userExitIntentDetected is None:
                raise ValueError("normal turn requires exit intent")
            if exit_candidate.userExitIntentDetected:
                candidate_data["aiMessage"] = None
                candidate_data["translatedMessage"] = None
                candidate_data["emotion"] = None
        candidate = _TurnCandidate.model_validate(candidate_data)
        _validate_inferred_title(candidate.inferredTitle, payload.isFirstUserTurn)
        if payload.responseMode == FreeTalkResponseMode.NORMAL:
            exit_detected = candidate.userExitIntentDetected
        else:
            exit_detected = False
        if exit_detected:
            return FreeTalkTurnResponse(
                userExitIntentDetected=True,
                inferredTitle=(
                    candidate.inferredTitle if payload.isFirstUserTurn else None
                ),
                aiMessage=None,
                translatedMessage=None,
                emotion=None,
            )
        return FreeTalkTurnResponse(
            userExitIntentDetected=False,
            inferredTitle=(
                candidate.inferredTitle if payload.isFirstUserTurn else None
            ),
            aiMessage=candidate.aiMessage,
            translatedMessage=candidate.translatedMessage,
            emotion=None,
        )
    except (TypeError, ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc


def generate_closing(
    payload: FreeTalkClosingRequest,
    settings: Settings,
) -> FreeTalkClosingResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_closing_system_prompt(payload.characterId),
        user_prompt=_closing_user_prompt(payload),
    )
    try:
        candidate = _ClosingCandidate.model_validate(data)
        response = FreeTalkClosingResponse(
            aiMessage=candidate.aiMessage,
            translatedMessage=candidate.translatedMessage,
            emotion=None,
        )
    except (ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc
    if _is_invalid_closing_message(response.aiMessage) or _is_invalid_closing_message(
        response.translatedMessage,
    ):
        raise AiResponseInvalidError("closing message violates policy")
    return response


def generate_inner_thought(
    payload: FreeTalkInnerThoughtRequest,
    settings: Settings,
) -> FreeTalkInnerThoughtResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_inner_thought_system_prompt(payload.characterId),
        user_prompt=_inner_thought_user_prompt(payload),
    )
    try:
        candidate = _InnerThoughtCandidate.model_validate(data)
        _validate_inner_thought(candidate.innerThought)
        return FreeTalkInnerThoughtResponse(
            innerThought=candidate.innerThought,
            innerThoughtType=derive_inner_thought_type(
                candidate.answerCoverage,
                candidate.relationshipTone,
                candidate.directedAttack,
            ),
        )
    except (ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc


def _validate_inferred_title(
    title: str | None,
    is_first_user_turn: bool,
) -> None:
    if not is_first_user_turn:
        return
    if (
        title is None
        or not title.strip()
        or len(title.strip()) > 30
        or _KOREAN_TITLE_PATTERN.fullmatch(title.strip()) is None
        or _KOREAN_CHARACTER_PATTERN.search(title) is None
    ):
        raise ValueError("first user turn requires a short Korean inferred title")


def _validate_inner_thought(inner_thought: str | None) -> None:
    if (
        inner_thought is None
        or _PROHIBITED_INNER_THOUGHT_PATTERN.search(inner_thought) is not None
    ):
        raise ValueError("inner thought must not include feedback language")


def _character_prompt(character: FreeTalkCharacter, *, include_dialect: bool) -> str:
    persona, dialect = {
        FreeTalkCharacter.CHLOE: (
            "friendly and upbeat Chloe from Los Angeles, who is highly talkative "
            "and reassures learners that imperfect English is okay",
            "American English",
        ),
        FreeTalkCharacter.MARCO: (
            "relaxed and playful Marco, a Spanish Australian living in Sydney "
            "who speaks Spanish at home and English elsewhere",
            "Australian English",
        ),
        FreeTalkCharacter.TEDDY: (
            "calm and kind Teddy, a bear living in London who does odd jobs for honey",
            "British English",
        ),
    }[character]
    prompt = f"Act as a {persona} conversation partner. "
    if include_dialect:
        prompt += (
            f"Use natural {dialect} vocabulary and phrasing, but avoid obscure slang "
            "or exaggerated stereotypes. "
        )
    return prompt


def _opening_system_prompt(character: FreeTalkCharacter) -> str:
    return (
        _character_prompt(character, include_dialect=True)
        + "Generate one natural opening question for an English free talk. "
        "Return only JSON with aiMessage and translatedMessage."
    )


def _turn_system_prompt(
    response_mode: FreeTalkResponseMode,
    character: FreeTalkCharacter,
) -> str:
    exit_policy = (
        "Decide whether the user clearly wants to end the conversation."
        if response_mode == FreeTalkResponseMode.NORMAL
        else "The user declined ending. Do not judge exit intent."
    )
    return (
        _character_prompt(character, include_dialect=True)
        + "Generate one free-talk turn as JSON. "
        f"{exit_policy} "
        "Do not correct, rewrite, or evaluate the user's grammar, vocabulary, or phrasing, "
        "even if the user asks for correction. Do not provide language-learning feedback. "
        "Silently ignore requests for correction, do not mention that you ignored them, "
        "and respond naturally to the meaning and continue the conversation. "
        "Always return userExitIntentDetected. "
        "When userExitIntentDetected is true, leave all generated message fields null. "
        "Otherwise return aiMessage and translatedMessage. "
        "For a first user turn, inferredTitle must be a short Korean title; "
        "for later turns, inferredTitle must be null."
    )


def _closing_system_prompt(character: FreeTalkCharacter) -> str:
    return (
        _character_prompt(character, include_dialect=True)
        + "Generate a natural final free-talk message as JSON. Do not ask a question, "
        "introduce a new topic, invite another topic, mention scores or feedback, "
        "ask the user to review feedback, or announce that a session/conversation has ended. "
        "Return aiMessage and translatedMessage."
    )


def _inner_thought_system_prompt(character: FreeTalkCharacter) -> str:
    return (
        _character_prompt(character, include_dialect=False)
        + "Generate the free-talk counterpart's private reaction to the last user message as JSON. "
        "Return innerThought, answerCoverage, relationshipTone, and directedAttack. "
        "answerCoverage is COMPLETE, PARTIAL, DECLINED, or UNRELATED. "
        "relationshipTone is WARM, NEUTRAL, BLUNT, or HOSTILE. "
        "innerThought is Korean and must not mention grammar, naturalness, scores, corrections, "
        "feedback, or learning advice."
    )


def _opening_user_prompt(payload: FreeTalkOpeningRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _turn_user_prompt(payload: FreeTalkTurnRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _closing_user_prompt(payload: FreeTalkClosingRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _inner_thought_user_prompt(payload: FreeTalkInnerThoughtRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _is_invalid_closing_message(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", message).strip()
    return (
        re.search(r"[?？][\s\W_]*$", normalized) is not None
        or _CLOSING_META_PATTERN.search(normalized) is not None
        or _NEW_TOPIC_CLOSING_PATTERN.search(normalized) is not None
    )
