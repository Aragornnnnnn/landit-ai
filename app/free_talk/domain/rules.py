# 프리톡 생성 결과의 순수 계약 검증 규칙을 정의하는 모듈
from app.models.conversation import (
    AnswerCoverage,
    InnerThoughtType,
    RelationshipTone,
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
