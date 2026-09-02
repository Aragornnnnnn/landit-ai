# 시나리오와 프리톡의 속마음 응답 검증 및 fallback 정책을 정의하는 모듈
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError, field_validator

from app.models.conversation import (
    AnswerCoverage,
    InnerThoughtType,
    RelationshipTone,
)


logger = logging.getLogger(__name__)

SAFE_INNER_THOUGHT = "상대의 말을 받아들이고 있다."
_PROHIBITED_INNER_THOUGHT_PATTERN = re.compile(
    r"문법|자연스러(?:움|운)|점수|교정|피드백|"
    r"grammar|naturalness|score|correction|feedback",
    re.IGNORECASE,
)


class InnerThoughtContractError(ValueError):
    def __init__(self, reason: str, invalid_fields: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.invalid_fields = invalid_fields


class _InnerThoughtCandidate(BaseModel):
    innerThought: str
    answerCoverage: AnswerCoverage
    relationshipTone: RelationshipTone
    directedAttack: bool

    @field_validator("innerThought")
    @classmethod
    def inner_thought_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("innerThought must not be blank")
        return value.strip()


@dataclass(frozen=True)
class InnerThoughtResult:
    inner_thought: str
    inner_thought_type: InnerThoughtType


def parse_inner_thought(data: dict[str, object]) -> InnerThoughtResult:
    candidate_data = dict(data)
    directed_attack = _normalized_directed_attack(candidate_data)
    if directed_attack is not None:
        candidate_data["directedAttack"] = directed_attack
    elif "directedAttack" in candidate_data:
        candidate_data["directedAttack"] = object()
    try:
        candidate = _InnerThoughtCandidate.model_validate(candidate_data)
    except ValidationError as exc:
        invalid_fields = tuple(
            sorted({str(error["loc"][0]) for error in exc.errors()})
        )
        raise InnerThoughtContractError("contract_validation", invalid_fields) from exc
    if _PROHIBITED_INNER_THOUGHT_PATTERN.search(candidate.innerThought) is not None:
        raise InnerThoughtContractError(
            "prohibited_feedback_language",
            ("innerThought",),
        )
    return InnerThoughtResult(
        inner_thought=candidate.innerThought,
        inner_thought_type=derive_inner_thought_type(
            candidate.answerCoverage,
            candidate.relationshipTone,
            candidate.directedAttack,
        ),
    )


def fallback_inner_thought(data: dict[str, object] | None) -> InnerThoughtResult:
    value = data.get("innerThought") if data is not None else None
    inner_thought = (
        value.strip()
        if isinstance(value, str) and value.strip()
        else SAFE_INNER_THOUGHT
    )
    return InnerThoughtResult(
        inner_thought=inner_thought,
        inner_thought_type=InnerThoughtType.NORMAL,
    )


def report_inner_thought_fallback(
    *,
    workflow: str,
    session_id: int,
    message_id: int,
    reason: str,
    invalid_fields: tuple[str, ...] = (),
) -> None:
    logger.error(
        "AI inner thought contract fallback. "
        "workflow=%s attempt=repair reason=%s sessionId=%s messageId=%s fields=%s",
        workflow,
        reason,
        session_id,
        message_id,
        ",".join(invalid_fields) or "none",
    )


def derive_inner_thought_type(
    answer_coverage: AnswerCoverage,
    relationship_tone: RelationshipTone,
    directed_attack: bool,
) -> InnerThoughtType:
    if (
        directed_attack
        or relationship_tone == RelationshipTone.HOSTILE
        or answer_coverage == AnswerCoverage.UNRELATED
    ):
        return InnerThoughtType.BAD
    if (
        answer_coverage in {AnswerCoverage.PARTIAL, AnswerCoverage.DECLINED}
        or relationship_tone == RelationshipTone.BLUNT
    ):
        return InnerThoughtType.NORMAL
    return InnerThoughtType.GOOD


def _normalized_directed_attack(data: dict[str, object]) -> bool | None:
    if "directedAttack" not in data:
        return None
    value = data["directedAttack"]
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in {"", "none", "no attack", "없음", "null", "not applicable"}:
        return False
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None
