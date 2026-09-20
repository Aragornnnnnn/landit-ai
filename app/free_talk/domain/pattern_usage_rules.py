# 지켜볼 실수 패턴의 사용례 판정을 제출 원문·교정 결과와 대조하는 순수 규칙 모듈
from collections.abc import Iterable
from dataclasses import dataclass

from app.free_talk.domain.correction_rules import (
    locate_original_sentence,
    locate_span,
    span_range_in,
)


# "몇 번 맞게 썼다"를 셀 수 있는, 형태가 단어로 드러나는 패턴만 지켜본다.
# 단어 선택·자연스러움처럼 모든 문장이 사용례가 되는 패턴은 횟수가 정의되지 않는다.
WATCHABLE_PATTERNS = frozenset(
    {
        "TENSE",
        "SUBJECT_VERB_AGREEMENT",
        "VERB_FORM",
        "ARTICLE",
        "PLURAL",
        "PRONOUN",
        "PREPOSITION",
        "NEGATION",
        "QUESTION_FORM",
    }
)


@dataclass(frozen=True)
class UsageClaim:
    """모델이 주장한 사용례 한 건. 검증 전이라 어떤 값도 믿지 않는다."""

    pattern: str
    sentence: str
    span: str
    correct: bool


def effective_watch_patterns(patterns: Iterable[str]) -> list[str]:
    """요청 순서를 지키면서 셀 수 있는 패턴만 남긴다."""
    return [str(pattern) for pattern in patterns if pattern in WATCHABLE_PATTERNS]


def verified_usage_claims(
    claims: Iterable[UsageClaim],
    watch_patterns: Iterable[str],
    submitted: str,
) -> list[UsageClaim]:
    """지켜볼 패턴이고 문장·구절을 원문에서 실제로 찾은 주장만 남긴다.

    sentence와 span은 원문의 정확한 조각으로 교체하고, 같은 (패턴, 문장, 구절)은 한 건만 남긴다.
    """
    watched = set(watch_patterns)
    verified: list[UsageClaim] = []
    seen: set[tuple[str, str, str]] = set()
    for claim in claims:
        if claim.pattern not in watched:
            continue
        sentence = locate_original_sentence(submitted, claim.sentence)
        if sentence is None:
            continue
        span = locate_span(sentence, claim.span)
        key = (claim.pattern, sentence, span or "")
        if span is None or key in seen:
            continue
        seen.add(key)
        verified.append(UsageClaim(claim.pattern, sentence, span, claim.correct))
    return verified


def _overlaps(usage: UsageClaim, sentence: str, span: str) -> bool:
    if usage.sentence != sentence:
        return False
    usage_range = span_range_in(sentence, usage.span)
    span_range = span_range_in(sentence, span)
    if usage_range is None or span_range is None:
        return False
    return usage_range[0] < span_range[1] and span_range[0] < usage_range[1]


def reconciled_with_correction(
    usages: Iterable[UsageClaim],
    watch_patterns: Iterable[str],
    *,
    pattern: str,
    sentence: str,
    wrong_span: str | None,
) -> list[UsageClaim]:
    """내려가는 교정이 지켜볼 패턴이면 그 틀린 구절이 틀린 사용례로 한 번 들어가게 맞춘다.

    같은 자리를 맞았다고 하거나 다른 구절 범위로 또 틀렸다고 한 주장은 교정과 어긋나므로 뺀다.
    """
    usages = list(usages)
    if wrong_span is None or pattern not in set(watch_patterns):
        return usages
    kept = [
        usage
        for usage in usages
        if not (usage.pattern == pattern and _overlaps(usage, sentence, wrong_span))
    ]
    kept.append(UsageClaim(pattern, sentence, wrong_span, False))
    return kept


def without_dropped_correction(
    usages: Iterable[UsageClaim],
    *,
    pattern: str,
    sentence: str,
    wrong_span: str | None,
) -> list[UsageClaim]:
    """서버 규칙으로 버린 교정과 같은 자리의 틀린 사용례를 함께 버린다.

    남겨 두면 버린 교정을 근거로 "오늘도 틀렸어요"가 나간다. 구절을 모르면 그 문장의 같은 패턴을 버린다.
    """
    kept: list[UsageClaim] = []
    for usage in usages:
        if usage.correct or usage.sentence != sentence:
            kept.append(usage)
        elif wrong_span is None:
            if usage.pattern != pattern:
                kept.append(usage)
        elif not _overlaps(usage, sentence, wrong_span):
            kept.append(usage)
    return kept
