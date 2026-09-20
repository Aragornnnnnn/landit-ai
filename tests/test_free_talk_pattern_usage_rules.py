# 강조 구절과 실수 패턴 사용례의 원문 대조·교정 조정 규칙을 검증하는 unittest 모듈
import unittest

from app.free_talk.domain.correction_rules import locate_span, span_rejection
from app.free_talk.domain.pattern_usage_rules import (
    UsageClaim,
    effective_watch_patterns,
    reconciled_with_correction,
    verified_usage_claims,
    without_dropped_correction,
)

SENTENCE = "I go to gym yesterday with my friend."
SUBMITTED = f"Yeah! {SENTENCE} We watched a movie and I eat popcorn."


class SpanTests(unittest.TestCase):
    def test_unique_span_returns_the_original_slice(self):
        self.assertEqual(locate_span("I GO  to gym.", "go to"), "GO  to")
        self.assertIsNone(span_rejection(SENTENCE, "go"))

    def test_span_must_match_whole_words(self):
        self.assertEqual(span_rejection("I am going home.", "go"), "not_found")
        self.assertEqual(span_rejection("I don't know.", "don"), "not_found")

    def test_span_that_appears_twice_is_ambiguous(self):
        sentence = "I go to gym and go home."
        self.assertEqual(span_rejection(sentence, "go"), "ambiguous")
        self.assertIsNone(locate_span(sentence, "go"))
        self.assertEqual(locate_span(sentence, "go home"), "go home")

    def test_blank_and_regex_metacharacters(self):
        self.assertEqual(span_rejection(SENTENCE, "  "), "blank")
        self.assertEqual(locate_span("It cost $5 (really).", "$5 (really)"), "$5 (really)")


class WatchPatternTests(unittest.TestCase):
    def test_only_countable_patterns_are_watched_in_request_order(self):
        self.assertEqual(
            effective_watch_patterns(["NATURALNESS", "TENSE", "OTHER", "ARTICLE"]),
            ["TENSE", "ARTICLE"],
        )
        self.assertEqual(effective_watch_patterns(["WORD_CHOICE"]), [])


class VerifiedUsageClaimTests(unittest.TestCase):
    def test_keeps_only_watched_claims_found_in_the_submitted_text(self):
        claims = [
            UsageClaim("TENSE", "we WATCHED a movie and I eat popcorn.", "Watched", True),
            UsageClaim("TENSE", "We watched a movie and I eat popcorn.", "eat", False),
            UsageClaim("ARTICLE", SENTENCE, "gym", False),
            UsageClaim("TENSE", "I never said this.", "said", True),
            UsageClaim("TENSE", SENTENCE, "went", False),
            UsageClaim("TENSE", SENTENCE, "", False),
        ]

        verified = verified_usage_claims(claims, ["TENSE"], SUBMITTED)

        self.assertEqual(
            verified,
            [
                UsageClaim("TENSE", "We watched a movie and I eat popcorn.", "watched", True),
                UsageClaim("TENSE", "We watched a movie and I eat popcorn.", "eat", False),
            ],
        )

    def test_duplicate_claims_collapse_to_one(self):
        claims = [UsageClaim("TENSE", SENTENCE, "go", False)] * 2
        self.assertEqual(len(verified_usage_claims(claims, ["TENSE"], SUBMITTED)), 1)


class ReconcileTests(unittest.TestCase):
    def test_correction_on_a_watched_pattern_is_listed_once_as_wrong(self):
        usages = [
            UsageClaim("TENSE", SENTENCE, "I go", True),
            UsageClaim("TENSE", "We watched a movie.", "watched", True),
        ]

        reconciled = reconciled_with_correction(
            usages, ["TENSE"], pattern="TENSE", sentence=SENTENCE, wrong_span="go"
        )

        self.assertEqual(
            reconciled,
            [
                UsageClaim("TENSE", "We watched a movie.", "watched", True),
                UsageClaim("TENSE", SENTENCE, "go", False),
            ],
        )

    def test_unwatched_pattern_or_missing_span_changes_nothing(self):
        usages = [UsageClaim("TENSE", SENTENCE, "go", True)]
        for pattern, span in (("ARTICLE", "gym"), ("TENSE", None)):
            with self.subTest(pattern=pattern, span=span):
                self.assertEqual(
                    reconciled_with_correction(
                        usages, ["TENSE"], pattern=pattern, sentence=SENTENCE, wrong_span=span
                    ),
                    usages,
                )

    def test_dropped_correction_takes_its_wrong_usage_with_it(self):
        gym = "And I am doing stairs at a gym."
        usages = [
            UsageClaim("ARTICLE", gym, "a gym", False),
            UsageClaim("ARTICLE", gym, "stairs", True),
            UsageClaim("ARTICLE", "I bought new phone.", "new phone", False),
        ]

        kept = without_dropped_correction(
            usages, pattern="ARTICLE", sentence=gym, wrong_span="a"
        )

        self.assertEqual(kept, usages[1:])

    def test_dropped_correction_without_a_span_drops_that_pattern_in_the_sentence(self):
        usages = [
            UsageClaim("TENSE", SENTENCE, "go", False),
            UsageClaim("ARTICLE", SENTENCE, "gym", False),
        ]

        kept = without_dropped_correction(
            usages, pattern="TENSE", sentence=SENTENCE, wrong_span=None
        )

        self.assertEqual(kept, usages[1:])


if __name__ == "__main__":
    unittest.main()
