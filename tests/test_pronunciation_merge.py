# 발음 분석의 병합·컷 규칙 순수 로직을 검증하는 unittest 모듈
import unittest

from app.models.pronunciation import PronunciationWordInput
from app.pronunciation.alignment.forced_align import WordSpan, _apply_cut_rule
from app.pronunciation.application.analysis_service import (
    _find_word_index,
    _merge,
    _normalize_word,
)
from app.pronunciation.llm.compare import JudgedDifference


def make_words(*texts):
    return [
        PronunciationWordInput(order=index + 1, word=text)
        for index, text in enumerate(texts)
    ]


class CutRuleTests(unittest.TestCase):
    def test_padding_is_applied(self):
        spans = _apply_cut_rule(["a", "b"], [(100.0, 400.0), (700.0, 900.0)])

        self.assertEqual(spans[0], WordSpan(word="a", start_ms=70, end_ms=450))
        self.assertEqual(spans[1], WordSpan(word="b", start_ms=670, end_ms=950))

    def test_end_is_capped_by_next_word_start(self):
        spans = _apply_cut_rule(["a", "b"], [(100.0, 400.0), (420.0, 700.0)])

        # end+50 = 450 이지만 다음 단어 start−10 = 410 로 잘린다
        self.assertEqual(spans[0].end_ms, 410)

    def test_start_never_goes_negative(self):
        spans = _apply_cut_rule(["a"], [(10.0, 200.0)])

        self.assertEqual(spans[0].start_ms, 0)


class WordMatchingTests(unittest.TestCase):
    def test_normalization_strips_case_and_punctuation(self):
        self.assertEqual(_normalize_word("There's,"), "there's")
        self.assertEqual(_normalize_word("Head."), "head")

    def test_duplicate_words_match_in_order(self):
        words = make_words("like", "really", "like")

        first = _find_word_index(words, "like", set())
        second = _find_word_index(words, "like", {first})

        self.assertEqual(first, 0)
        self.assertEqual(second, 2)

    def test_merge_maps_differences_to_orders(self):
        words = make_words("There's", "nothing")
        spans = [
            WordSpan(word="There's", start_ms=0, end_ms=400),
            WordSpan(word="nothing", start_ms=410, end_ms=900),
        ]
        differences = [
            JudgedDifference(word="Nothing.", type="SOUND", user_heard="nuh·ssing")
        ]

        results = _merge(words, spans, differences)

        self.assertEqual(results[0].status.value, "CORRECT")
        self.assertEqual(results[1].status.value, "PHONEME_ERROR")
        self.assertEqual(results[1].userDisplay, "nuh·ssing")
        self.assertEqual(results[1].startMs, 410)


if __name__ == "__main__":
    unittest.main()
