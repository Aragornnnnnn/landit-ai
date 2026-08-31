# 발음 분석의 병합 순수 로직을 검증하는 unittest 모듈
import unittest

from app.models.pronunciation import PronunciationWordInput
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
        differences = [
            JudgedDifference(word="Nothing.", type="SOUND", user_heard="nuh·ssing")
        ]

        results = _merge(words, differences)

        self.assertEqual(results[0].status.value, "CORRECT")
        self.assertEqual(results[1].status.value, "PHONEME_ERROR")
        self.assertEqual(results[1].userDisplay, "nuh·ssing")


class MergeContractTests(unittest.TestCase):
    """응답은 요청 단어와 개수·order·텍스트가 1:1이어야 한다 — BE는 어긋나면 전건 502를 낸다.

    이 보장은 _merge가 요청의 ordered_words를 그대로 뼈대로 쓰는 구조에서 나온다.
    정렬(wav2vec2) 제거 이후에도 유지됨을 회귀로 고정한다.
    """

    WORDS = ("There's", "nothing", "like", "hiking")

    def assert_one_to_one(self, results):
        words = make_words(*self.WORDS)
        self.assertEqual(len(results), len(words))
        self.assertEqual(
            [result.order for result in results],
            [word.order for word in words],
        )
        self.assertEqual(
            [result.word for result in results],
            [word.word for word in words],
        )

    def test_no_differences_keeps_every_requested_word(self):
        results = _merge(make_words(*self.WORDS), [])

        self.assert_one_to_one(results)

    def test_unknown_detected_word_does_not_change_shape(self):
        differences = [JudgedDifference(word="banana", type="SOUND")]

        results = _merge(make_words(*self.WORDS), differences)

        self.assert_one_to_one(results)
        self.assertEqual({r.status.value for r in results}, {"CORRECT"})

    def test_duplicate_detections_of_same_word_do_not_change_shape(self):
        differences = [
            JudgedDifference(word="nothing", type="SOUND"),
            JudgedDifference(word="nothing", type="STRESS"),
            JudgedDifference(word="nothing", type="SOUND"),
        ]

        results = _merge(make_words(*self.WORDS), differences)

        self.assert_one_to_one(results)
        # 중복 지목은 아직 지목되지 않은 다음 동일 단어에만 붙는다 —
        # 같은 단어가 한 번뿐이면 첫 지목만 반영되고 결과 형태는 불변이다
        self.assertEqual(results[1].status.value, "PHONEME_ERROR")

    def test_more_differences_than_words_do_not_change_shape(self):
        differences = [
            JudgedDifference(word=word, type="SOUND") for word in self.WORDS
        ] + [JudgedDifference(word="extra", type="SOUND")]

        results = _merge(make_words(*self.WORDS), differences)

        self.assert_one_to_one(results)


if __name__ == "__main__":
    unittest.main()
