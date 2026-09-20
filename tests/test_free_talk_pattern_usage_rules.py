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

    def test_half_of_a_hyphenated_word_is_not_a_span(self):
        self.assertEqual(span_rejection("She is a well-known chef.", "well"), "not_found")
        self.assertIsNone(span_rejection("She is a well-known chef.", "well-known"))

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

    def test_correct_article_usage_must_show_an_article(self):
        submitted = "My boss bought a desk. I took taxi."
        claims = [
            UsageClaim("ARTICLE", "My boss bought a desk.", "My boss", True),
            UsageClaim("ARTICLE", "My boss bought a desk.", "a desk", True),
            UsageClaim("ARTICLE", "I took taxi.", "taxi", False),
        ]
        self.assertEqual(verified_usage_claims(claims, ["ARTICLE"], submitted), claims[1:])

    def test_same_place_claimed_twice_collapses_to_one(self):
        claims = [
            UsageClaim("TENSE", SENTENCE, "go", False),
            UsageClaim("TENSE", SENTENCE.rstrip("."), "I go", False),
        ]
        self.assertEqual(
            verified_usage_claims(claims, ["TENSE"], SUBMITTED),
            [UsageClaim("TENSE", SENTENCE, "go", False)],
        )

    def test_same_place_claimed_right_and_wrong_is_dropped_entirely(self):
        claims = [
            UsageClaim("TENSE", SENTENCE, "go", False),
            UsageClaim("TENSE", SENTENCE, "I go", True),
            UsageClaim("TENSE", "We watched a movie and I eat popcorn.", "watched", True),
        ]
        self.assertEqual(
            verified_usage_claims(claims, ["TENSE"], SUBMITTED),
            [UsageClaim("TENSE", "We watched a movie and I eat popcorn.", "watched", True)],
        )


class ReconcileTests(unittest.TestCase):
    def test_correction_on_a_watched_pattern_is_listed_once_as_wrong(self):
        usages = [
            UsageClaim("TENSE", SENTENCE, "I go", True),
            UsageClaim("TENSE", "We watched a movie.", "watched", True),
        ]

        reconciled = reconciled_with_correction(
            usages, ["TENSE"], SUBMITTED, pattern="TENSE", sentence=SENTENCE, wrong_span="go"
        )

        self.assertEqual(
            reconciled,
            [
                UsageClaim("TENSE", "We watched a movie.", "watched", True),
                UsageClaim("TENSE", SENTENCE, "go", False),
            ],
        )

    def test_mistake_of_another_pattern_is_not_a_wrong_usage_of_the_watched_one(self):
        sentence = "She cook every evening."
        usages = [
            UsageClaim("TENSE", sentence, "cook", False),
            UsageClaim("TENSE", "It was tiring.", "was", True),
        ]

        reconciled = reconciled_with_correction(
            usages,
            ["TENSE"],
            f"{sentence} It was tiring.",
            pattern="SUBJECT_VERB_AGREEMENT",
            sentence=sentence,
            wrong_span="cook",
        )

        self.assertEqual(reconciled, usages[1:])

    def test_unwatched_pattern_elsewhere_or_missing_span_changes_nothing(self):
        usages = [UsageClaim("TENSE", SENTENCE, "go", True)]
        for pattern, span in (("ARTICLE", "gym"), ("TENSE", None)):
            with self.subTest(pattern=pattern, span=span):
                self.assertEqual(
                    reconciled_with_correction(
                        usages, ["TENSE"], SUBMITTED, pattern=pattern, sentence=SENTENCE, wrong_span=span
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

        submitted = f"Yes. {gym} I bought new phone."

        kept = without_dropped_correction(
            usages, submitted, pattern="ARTICLE", sentence=gym, wrong_span="a"
        )

        self.assertEqual(kept, usages[1:])

    def test_same_place_is_recognized_when_the_sentence_slices_differ(self):
        # 모델은 같은 문장을 마침표를 빼거나 앞말을 떼고 옮기기도 한다
        gym = "And I am doing stairs at a gym."
        submitted = f"Yes. {gym}"
        trimmed = [UsageClaim("ARTICLE", "I am doing stairs at a gym", "a", False)]

        kept = without_dropped_correction(
            trimmed, submitted, pattern="ARTICLE", sentence=gym, wrong_span="a gym"
        )
        reconciled = reconciled_with_correction(
            [UsageClaim("TENSE", SENTENCE.rstrip("."), "go", True)],
            ["TENSE"],
            SUBMITTED,
            pattern="TENSE",
            sentence=SENTENCE,
            wrong_span="go",
        )

        self.assertEqual(kept, [])
        self.assertEqual(reconciled, [UsageClaim("TENSE", SENTENCE, "go", False)])

    def test_dropped_correction_keeps_another_pattern_that_only_overlaps(self):
        gym = "And I am doing stairs at a gym."
        usages = [UsageClaim("PLURAL", gym, "stairs at a gym", False)]

        kept = without_dropped_correction(
            usages, gym, pattern="ARTICLE", sentence=gym, wrong_span="a gym"
        )

        self.assertEqual(kept, usages)

    def test_dropped_correction_without_a_span_drops_that_pattern_in_the_sentence(self):
        usages = [
            UsageClaim("TENSE", SENTENCE, "go", False),
            UsageClaim("ARTICLE", SENTENCE, "gym", False),
        ]

        kept = without_dropped_correction(
            usages, SUBMITTED, pattern="TENSE", sentence=SENTENCE, wrong_span=None
        )

        self.assertEqual(kept, usages[1:])


if __name__ == "__main__":
    unittest.main()
