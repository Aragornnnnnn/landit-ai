# 발음 기준 데이터 생성(음절 분리·IPA 파싱)을 검증하는 unittest 모듈
#
# espeak-ng 실행 없이 순수 함수만 검증한다. IPA 문자열은 espeak-ng 1.52 실측 출력이다.
import unittest

from app.pronunciation.reference.espeak import parse_ipa, respell
from app.pronunciation.reference.respelling import build_pronunciation
from app.pronunciation.reference.syllables import split_syllables


class SyllableSplitTests(unittest.TestCase):
    def test_monosyllable_keeps_spelling(self):
        self.assertEqual(split_syllables("like", 1), ["like"])

    def test_digraph_is_not_split(self):
        # "not·hing"처럼 th가 갈라지면 읽을 수 없다
        self.assertEqual(split_syllables("nothing", 2), ["no", "thing"])

    def test_four_syllable_word(self):
        self.assertEqual(split_syllables("american", 4), ["a", "me", "ri", "can"])

    def test_mismatched_count_returns_none(self):
        # 철자 모음 덩어리 수와 발음 음절 수가 다르면 검수 대상이다
        self.assertIsNone(split_syllables("advertisement", 4))

    def test_final_e_is_kept_when_it_sounds(self):
        # "maybe"의 e는 소리 나고 "circle"의 le는 음절이다
        self.assertEqual(split_syllables("maybe", 2), ["may", "be"])
        self.assertEqual(split_syllables("circle", 2), ["circ", "le"])

    def test_silent_e_in_es_ed_suffix_is_absorbed(self):
        self.assertEqual(split_syllables("survives", 2), ["sur", "vives"])
        self.assertEqual(split_syllables("minutes", 2), ["mi", "nutes"])

    def test_ing_after_vowel_becomes_its_own_syllable(self):
        self.assertEqual(split_syllables("doing", 2), ["do", "ing"])
        self.assertEqual(split_syllables("staying", 2), ["stay", "ing"])


class IpaParseTests(unittest.TestCase):
    # espeak-ng 실측 출력 기반
    CASES = {
        "wˈɔːtə": ("waw·tuh", 2, 0),  # water en-gb
        "wˈɔːɾɚ": ("waw·der", 2, 0),  # water en-us (flap t)
        "təmˈɑːtəʊ": ("tuh·mah·toh", 3, 1),  # tomato en-gb
        "ˌædvɚtˈaɪzmənt": ("ad·ver·teyez·muhnt", 4, 2),  # advertisement en-us
        "ɐdvˈɜːtɪsmənt": ("uhd·ver·tihs·muhnt", 4, 1),  # advertisement en-gb
        "ʃˈɛdjuːl": ("shehd·yool", 2, 0),  # schedule en-gb
        "kˈɑːnt": ("kahnt", 1, 0),  # can't en-gb
    }

    def test_real_espeak_outputs_parse_correctly(self):
        for ipa, (spelling, count, stress) in self.CASES.items():
            parsed = parse_ipa(ipa)
            self.assertIsNotNone(parsed, ipa)
            self.assertEqual("·".join(parsed.syllable_respellings), spelling, ipa)
            self.assertEqual(parsed.syllable_count, count, ipa)
            self.assertEqual(parsed.stress_index, stress, ipa)

    def test_respell_joins_syllables(self):
        self.assertEqual(respell("wˈɔːtə"), "waw·tuh")

    def test_unknown_symbol_returns_none(self):
        self.assertIsNone(parse_ipa("w§t"))

    def test_no_vowel_returns_none(self):
        self.assertIsNone(parse_ipa("st"))


class BuildPronunciationTests(unittest.TestCase):
    def test_stress_comes_from_arpabet_digits(self):
        built = build_pronunciation(
            word="hiking",
            phonemes=["HH", "AY1", "K", "IH0", "NG"],
            syllables=["hik", "ing"],
        )
        self.assertEqual(built.stress_index, 0)
        self.assertEqual(built.native_display, "hik·ing")
        self.assertIsNone(built.review_reason)

    def test_function_word_gets_minus_one(self):
        built = build_pronunciation(
            word="to", phonemes=["T", "UW1"], syllables=["to"], function_word=True
        )
        self.assertEqual(built.stress_index, -1)

    def test_syllable_count_mismatch_is_flagged(self):
        built = build_pronunciation(
            word="american",
            phonemes=["AH0", "M", "EH1", "R", "AH0", "K", "AH0", "N"],
            syllables=["amer", "i", "can"],
        )
        self.assertIsNotNone(built.review_reason)


if __name__ == "__main__":
    unittest.main()
