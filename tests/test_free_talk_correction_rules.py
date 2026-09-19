# 프리톡 턴 교정의 원문 대조 규칙을 검증하는 unittest 모듈
import unittest

from app.free_talk.domain.correction_rules import (
    is_effective_correction,
    is_only_definite_article_swap,
    locate_original_sentence,
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
