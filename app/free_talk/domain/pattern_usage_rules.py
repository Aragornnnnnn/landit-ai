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


_ARTICLES = frozenset({"a", "an", "the"})


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


def place_in(submitted: str, sentence: str, span: str | None) -> tuple[int, int] | None:
    """구절이 제출 원문에서 차지하는 [시작, 끝) 위치. 구절이 없으면 문장 전체의 위치다.

    모델은 같은 문장을 마침표를 빼거나 앞말을 떼고 옮기기도 한다. 문장 문자열이 아니라
    원문 위치로 비교해야 같은 자리를 같은 자리로 알아본다.
    """
    sentence_start = submitted.find(sentence)
    if sentence_start < 0:
        return None
    if span is None:
        return sentence_start, sentence_start + len(sentence)
    span_range = span_range_in(sentence, span)
    if span_range is None:
        return None
    return sentence_start + span_range[0], sentence_start + span_range[1]


def _overlap(first: tuple[int, int] | None, second: tuple[int, int] | None) -> bool:
    if first is None or second is None:
        return False
    return first[0] < second[1] and second[0] < first[1]


def _shows_the_form(claim: "UsageClaim", span: str) -> bool:
    """맞게 쓴 관사는 구절 안에 관사가 보여야 한다.

    모델이 my boss처럼 관사가 필요 없는 명사를 "맞게 쓴 관사"로 세는 일이 실측에서 남았고, 이런 오판은
    카드의 "세 번 다 맞았어요"를 부풀린다. 틀린 쪽은 관사가 빠진 자리라 구절에 관사가 없는 것이 정상이다.
    """
    if claim.pattern != "ARTICLE" or not claim.correct:
        return True
    return any(word.lower() in _ARTICLES for word in span.split())


def verified_usage_claims(
    claims: Iterable[UsageClaim],
    watch_patterns: Iterable[str],
    submitted: str,
) -> list[UsageClaim]:
    """지켜볼 패턴이고 문장·구절을 원문에서 실제로 찾은 주장만 남긴다.

    sentence와 span은 원문의 정확한 조각으로 교체한다. 같은 패턴으로 같은 자리를 두 번 짚으면 한 건만
    남기고, 한쪽은 맞았다 한쪽은 틀렸다 하면 어느 쪽도 믿을 수 없으므로 둘 다 버린다.
    """
    watched = set(watch_patterns)
    verified: list[tuple[UsageClaim, tuple[int, int]]] = []
    conflicted: set[int] = set()
    for claim in claims:
        if claim.pattern not in watched:
            continue
        sentence = locate_original_sentence(submitted, claim.sentence)
        span = locate_span(sentence, claim.span) if sentence is not None else None
        if sentence is None or span is None or not _shows_the_form(claim, span):
            continue
        place = place_in(submitted, sentence, span)
        same_place = next(
            (
                index
                for index, (kept, kept_place) in enumerate(verified)
                if kept.pattern == claim.pattern and _overlap(kept_place, place)
            ),
            None,
        )
        if same_place is None:
            verified.append((UsageClaim(claim.pattern, sentence, span, claim.correct), place))
        elif verified[same_place][0].correct != claim.correct:
            conflicted.add(same_place)
    return [claim for index, (claim, _) in enumerate(verified) if index not in conflicted]


def reconciled_with_correction(
    usages: Iterable[UsageClaim],
    watch_patterns: Iterable[str],
    submitted: str,
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
    place = place_in(submitted, sentence, wrong_span)
    kept = [
        usage
        for usage in usages
        if not (
            usage.pattern == pattern
            and _overlap(place_in(submitted, usage.sentence, usage.span), place)
        )
    ]
    kept.append(UsageClaim(pattern, sentence, wrong_span, False))
    return kept


def without_dropped_correction(
    usages: Iterable[UsageClaim],
    submitted: str,
    *,
    pattern: str,
    sentence: str,
    wrong_span: str | None,
) -> list[UsageClaim]:
    """서버 규칙으로 버린 교정과 같은 자리의 틀린 사용례를 함께 버린다.

    남겨 두면 버린 교정을 근거로 "오늘도 틀렸어요"가 나간다. 같은 자리란 같은 구절이거나, 같은 패턴으로
    겹치는 구절이다. 다른 패턴이 겹치기만 한 주장(a gym 위의 복수형)은 다른 이야기라 남긴다.
    교정의 구절을 모르면 그 문장 안의 같은 패턴을 버린다.
    """
    place = place_in(submitted, sentence, wrong_span)
    kept: list[UsageClaim] = []
    for usage in usages:
        usage_place = place_in(submitted, usage.sentence, usage.span)
        same_place = usage_place == place if wrong_span is not None else False
        same_pattern_overlap = usage.pattern == pattern and _overlap(usage_place, place)
        if usage.correct or not (same_place or same_pattern_overlap):
            kept.append(usage)
    return kept
