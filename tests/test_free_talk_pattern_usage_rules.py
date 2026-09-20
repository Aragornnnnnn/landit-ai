# 강조 구절과 실수 패턴 사용례의 원문 대조·교정 조정 규칙을 검증하는 unittest 모듈
import unittest

from app.free_talk.domain.correction_rules import (
    locate_span,
    span_rejection,
    word_after_insertion,
)
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

    def test_part_of_a_curly_apostrophe_contraction_is_not_a_span(self):
        # iOS 키보드는 기본으로 둥근 아포스트로피(’)를 넣는다
        cases = (
            ("I don’t like it.", "don"),
            ("It’s my friend’s car.", "It"),
            ("It’s my friend’s car.", "friend"),
            ("I don't like it.", "don"),
        )
        for sentence, part in cases:
            with self.subTest(sentence=sentence, part=part):
                self.assertEqual(span_rejection(sentence, part), "not_found")

    def test_whole_contraction_is_a_span_with_either_apostrophe(self):
        # 모델이 옮겨 적으며 아포스트로피 모양을 바꿔도 원문 조각 그대로 돌려준다
        self.assertEqual(locate_span("I don’t like it.", "don’t"), "don’t")
        self.assertEqual(locate_span("I don’t like it.", "don't"), "don’t")
        self.assertEqual(locate_span("I don't like it.", "don’t"), "don't")

    def test_mixed_apostrophes_in_one_sentence_behave_the_same(self):
        sentence = "I don’t know why it isn't working."
        self.assertEqual(locate_span(sentence, "isn’t"), "isn't")
        self.assertEqual(locate_span(sentence, "don't know"), "don’t know")
        self.assertEqual(span_rejection(sentence, "isn"), "not_found")
        self.assertEqual(span_rejection("I don’t and you don't.", "don't"), "ambiguous")

    def test_insertion_next_to_curly_quotes_points_at_the_bare_word(self):
        self.assertEqual(
            word_after_insertion("She said “go home” now.", "She said “go back home” now."),
            "home",
        )

    def test_words_that_differ_only_in_case_are_different_spans(self):
        sentence = "They stayed late, so I bought they coffee."
        self.assertEqual(locate_span(sentence, "they"), "they")
        self.assertEqual(locate_span(sentence, "They"), "They")
        # 대소문자까지 같은 자리가 없을 때만 대소문자를 무시하고, 그때 둘 이상이면 모호하다
        self.assertEqual(span_rejection(sentence, "THEY"), "ambiguous")
        self.assertEqual(span_rejection("I go and go.", "go"), "ambiguous")

    def test_blank_and_regex_metacharacters(self):
        self.assertEqual(span_rejection(SENTENCE, "  "), "blank")
        self.assertEqual(locate_span("It cost $5 (really).", "$5 (really)"), "$5 (really)")


class WordAfterInsertionTests(unittest.TestCase):
    def test_single_insertion_points_at_the_next_word(self):
        self.assertEqual(
            word_after_insertion("I bought new laptop.", "I bought a new laptop."), "new"
        )
        self.assertEqual(word_after_insertion("Went home early.", "I went home early."), "Went")

    def test_anything_but_one_clean_insertion_gives_nothing(self):
        cases = {
            "replacement": ("I go home.", "I went home."),
            "two_insertions": ("I bought laptop at store.", "I bought a laptop at the store."),
            "insertion_at_the_end": ("I listen to", "I listen to music"),
            "next_word_not_unique": ("I saw dog and dog ran.", "I saw a dog and dog ran."),
        }
        for name, (original, better) in cases.items():
            with self.subTest(name):
                self.assertIsNone(word_after_insertion(original, better))


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

    def test_correct_pronoun_usage_must_show_a_third_person_pronoun(self):
        submitted = "My sister is a nurse. She works nights and I see her often. I met he once."
        first = "My sister is a nurse."
        second = "She works nights and I see her often."
        claims = [
            UsageClaim("PRONOUN", first, "My sister", True),
            UsageClaim("PRONOUN", second, "I", True),
            UsageClaim("PRONOUN", second, "She", True),
            UsageClaim("PRONOUN", second, "see her", True),
            UsageClaim("PRONOUN", "I met he once.", "met he", False),
        ]
        self.assertEqual(verified_usage_claims(claims, ["PRONOUN"], submitted), claims[2:])

    def test_correct_verb_form_usage_must_show_the_verb_chain(self):
        submitted = "He owns a cafe. I want to run and I enjoy carving wood."
        second = "I want to run and I enjoy carving wood."
        claims = [
            UsageClaim("VERB_FORM", "He owns a cafe.", "owns", True),
            UsageClaim("VERB_FORM", second, "to run", True),
            UsageClaim("VERB_FORM", second, "carving", True),
            UsageClaim("VERB_FORM", "He owns a cafe.", "owns", False),
        ]
        self.assertEqual(verified_usage_claims(claims, ["VERB_FORM"], submitted), claims[1:])

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

    def test_watched_correction_without_a_place_needs_an_agreeing_usage(self):
        agreeing = [UsageClaim("TENSE", SENTENCE, "go", False)]
        disagreeing = [UsageClaim("TENSE", SENTENCE, "go", True)]
        kwargs = dict(pattern="TENSE", sentence=SENTENCE, wrong_span=None)

        self.assertEqual(
            reconciled_with_correction(agreeing, ["TENSE"], SUBMITTED, **kwargs), agreeing
        )
        # 교정은 틀렸다는데 목록은 맞았다거나 아무 말이 없으면 목록을 믿을 수 없다
        self.assertIsNone(reconciled_with_correction(disagreeing, ["TENSE"], SUBMITTED, **kwargs))
        self.assertIsNone(reconciled_with_correction([], ["TENSE"], SUBMITTED, **kwargs))

    def test_unwatched_pattern_elsewhere_or_missing_span_changes_nothing(self):
        usages = [UsageClaim("TENSE", SENTENCE, "go", True)]
        for pattern, span in (("ARTICLE", "gym"), ("ARTICLE", None)):
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
