# 학습 표현 재사용 판정 결과를 요청 원문과 대조하는 순수 규칙 모듈
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.free_talk.domain.correction_rules import locate_original_sentence


@dataclass(frozen=True)
class ReuseClaim:
    """모델이 주장한 재사용 한 건. 검증 전이라 어떤 값도 믿지 않는다."""

    expression_id: int
    message_id: int
    matched_text: str


def verified_reuse_claims(
    claims: Iterable[ReuseClaim],
    learned_expression_ids: set[int],
    user_message_contents: Mapping[int, str],
) -> list[ReuseClaim]:
    """목록 안 표현을 USER 메시지 원문에서 실제로 찾은 주장만 남긴다.

    matched_text는 원문의 정확한 조각으로 교체하고, 같은 표현·같은 메시지는 한 건만 남긴다.
    """
    verified: list[ReuseClaim] = []
    seen: set[tuple[int, int]] = set()
    for claim in claims:
        key = (claim.expression_id, claim.message_id)
        content = user_message_contents.get(claim.message_id)
        if claim.expression_id not in learned_expression_ids or content is None or key in seen:
            continue
        matched = locate_original_sentence(content, claim.matched_text)
        if matched is None:
            continue
        seen.add(key)
        verified.append(ReuseClaim(claim.expression_id, claim.message_id, matched))
    return verified
