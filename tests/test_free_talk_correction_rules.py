# 프리톡 턴 교정의 원문 대조 규칙을 검증하는 unittest 모듈
import unittest

from app.free_talk.domain.correction_rules import (
    is_effective_correction,
    MEMORY_LABEL_MAX_LENGTH,
    is_only_definite_article_swap,
    locate_original_sentence,
    memory_label_rejection,
)


class ArticleSwapApostropheTests(unittest.TestCase):
    def test_apostrophe_shape_does_not_hide_an_article_swap(self):
        self.assertTrue(
            is_only_definite_article_swap("I saw a dog’s tail", "I saw the dog's tail")
        )


class LocateOriginalSentenceTests(unittest.TestCase):
    def test_exact_substring_is_returned_as_is(self):
        content = "Yes. I go to gym yesterday with my friend. It was fun."
        self.assertEqual(
            locate_original_sentence(content, "I go to gym yesterday with my friend."),
            "I go to gym yesterday with my friend.",
        )

    def test_case_and_whitespace_differences_return_the_original_slice(self):
        content = "Yes.  I go to  gym yesterday with my friend."
        self.assertEqual(
            locate_original_sentence(content, "i go to gym YESTERDAY with my friend."),
            "I go to  gym yesterday with my friend.",
        )

    def test_apostrophe_shape_does_not_matter_and_the_original_slice_is_returned(self):
        content = "Yeah. I don’t like it. It’s too sweet."
        self.assertEqual(
            locate_original_sentence(content, "I don't like it."), "I don’t like it."
        )

    def test_missing_sentence_returns_none(self):
        content = "I went to the gym yesterday."
        self.assertIsNone(locate_original_sentence(content, "I go to gym yesterday."))

    def test_blank_candidate_returns_none(self):
        self.assertIsNone(locate_original_sentence("I go to gym.", "   "))

    def test_regex_metacharacters_in_candidate_are_escaped(self):
        content = "What? (I mean) really? Yes."
        self.assertEqual(
            locate_original_sentence(content, "what?   (i mean) really?"),
            "What? (I mean) really?",
        )


class IsEffectiveCorrectionTests(unittest.TestCase):
    def test_identical_sentences_are_not_a_correction(self):
        self.assertFalse(is_effective_correction("I went home.", " I went home. "))

    def test_different_sentences_are_a_correction(self):
        self.assertTrue(is_effective_correction("I go home yesterday.", "I went home yesterday."))



class DefiniteArticleSwapTests(unittest.TestCase):
    def test_only_swapping_a_or_an_for_the_is_a_swap(self):
        swaps = [
            ("And I am doing stairs at a gym.", "And I am doing stairs at the gym."),
            ("I ate an apple at a cafe.", "I ate the apple at the cafe."),
            ("at A gym", "At the gym!"),
        ]
        for original, better in swaps:
            with self.subTest(original=original):
                self.assertTrue(is_only_definite_article_swap(original, better))

    def test_any_other_change_is_not_a_swap(self):
        others = [
            ("I go to gym yesterday.", "I go to the gym yesterday."),
            ("I went to a gym.", "I went to the gym yesterday."),
            ("I go to a gym.", "I went to the gym."),
            ("I like the gym.", "I like a gym."),
            ("I am at a gym.", "I am at a gym."),
            ("I am at a gym.", "I am at my gym."),
        ]
        for original, better in others:
            with self.subTest(original=original):
                self.assertFalse(is_only_definite_article_swap(original, better))



class MemoryLabelRejectionTests(unittest.TestCase):
    def test_short_noun_phrases_are_accepted(self):
        for label in ("헬스장", "집 앞 수영장", "강아지 초코", "다음 주 면접", "  단골 빵집  ", "카페 1984"):
            with self.subTest(label=label):
                self.assertIsNone(memory_label_rejection(label))

    def test_date_notations_written_with_digits_are_rejected(self):
        for label in ("9/13 헬스장", "9월 13일 헬스장", "2026-09-13 헬스장", "13일 면접", "9 월 면접"):
            with self.subTest(label=label):
                self.assertEqual(memory_label_rejection(label), "contains_date")

    def test_sentence_marks_and_line_breaks_are_rejected(self):
        for label in ("헬스장에 다닌다.", "헬스장!", "어느 헬스장?", "헬스장\n수영장", "헬스장。"):
            with self.subTest(label=label):
                self.assertEqual(memory_label_rejection(label), "invalid_chars")

    def test_blank_labels_are_rejected(self):
        for label in ("", "   ", "\n"):
            with self.subTest(label=repr(label)):
                self.assertEqual(memory_label_rejection(label), "blank")

    def test_length_limit_counts_the_trimmed_label(self):
        at_limit = "가" * MEMORY_LABEL_MAX_LENGTH

        self.assertIsNone(memory_label_rejection(at_limit))
        self.assertIsNone(memory_label_rejection(f"  {at_limit}  "))
        self.assertEqual(memory_label_rejection(at_limit + "가"), "too_long")
