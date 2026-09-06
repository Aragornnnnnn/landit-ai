# 발음 데이터 스크립트(build_tts_source·prune_accent_contrasts)를 검증하는 unittest 모듈
#
# 코드래빗 리뷰 반영: locale 간 단어 목록 불일치 시 생성 중단, 프루닝의 위치 기반 매칭.
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_tts_source import build
from scripts.prune_accent_contrasts import prune

CONTRAST = {"expected": "a clear t", "other": "a flap", "errorType": "PHONEME"}


def reference_entry(expression_id, locale, words):
    return {
        "expressionId": expression_id,
        "accentLocale": locale,
        "sentenceText": " ".join(w["word"] for w in words),
        "words": words,
    }


def write_references(directory, entries_by_locale):
    for locale, entries in entries_by_locale.items():
        (directory / f"reference_{locale}.json").write_text(
            json.dumps(entries, ensure_ascii=False), encoding="utf-8"
        )


class BuildTtsSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.expressions = self.dir / "expressions.json"
        self.expressions.write_text(
            json.dumps(
                [{"expressionId": 1, "sentenceText": "I like water.",
                  "expressionText": "like water"}]
            ),
            encoding="utf-8",
        )
        self.addCleanup(self._tmp.cleanup)

    def words(self, *names):
        return [{"order": i + 1, "word": w} for i, w in enumerate(names)]

    def test_matching_locales_build(self):
        words = self.words("I", "like", "water")
        write_references(
            self.dir,
            {
                "EN_US": [reference_entry(1, "EN_US", words)],
                "EN_GB": [reference_entry(1, "EN_GB", words)],
                "EN_AU": [reference_entry(1, "EN_AU", words)],
            },
        )

        source = build(self.expressions, self.dir, None)

        self.assertEqual(len(source["expressions"]), 1)

    def test_mismatched_locale_word_list_aborts(self):
        write_references(
            self.dir,
            {
                "EN_US": [reference_entry(1, "EN_US", self.words("I", "like", "water"))],
                "EN_GB": [reference_entry(1, "EN_GB", self.words("I", "love", "water"))],
                "EN_AU": [reference_entry(1, "EN_AU", self.words("I", "like", "water"))],
            },
        )

        with self.assertRaisesRegex(ValueError, "1.*EN_GB"):
            build(self.expressions, self.dir, None)


class PruneAccentContrastsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_gb(self, words):
        write_references(
            self.dir, {"EN_GB": [reference_entry(930, "EN_GB", words)]}
        )

    def problems(self, *lines):
        path = self.dir / "problems.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def load_gb_words(self):
        entries = json.loads(
            (self.dir / "reference_EN_GB.json").read_text(encoding="utf-8")
        )
        return entries[0]["words"]

    def test_word_problem_removes_only_that_order(self):
        # 같은 단어가 2번 나와도 word-N 문제는 해당 order만 제거한다
        self.write_gb(
            [
                {"order": 1, "word": "can't", "accentContrast": dict(CONTRAST)},
                {"order": 2, "word": "stop", "accentContrast": dict(CONTRAST)},
                {"order": 3, "word": "can't", "accentContrast": dict(CONTRAST)},
            ]
        )

        prune(
            self.problems("930/EN_GB/word-1: 'Can't' sounded like kant"), self.dir
        )

        words = self.load_gb_words()
        self.assertNotIn("accentContrast", words[0])
        self.assertIn("accentContrast", words[1])
        self.assertIn("accentContrast", words[2])

    def test_word_problem_with_mismatched_text_fails(self):
        self.write_gb(
            [{"order": 1, "word": "water", "accentContrast": dict(CONTRAST)}]
        )

        with self.assertRaises(ValueError):
            prune(
                self.problems("930/EN_GB/word-1: 'Can't' sounded like kant"),
                self.dir,
            )

    def test_sentence_problem_removes_unique_word(self):
        self.write_gb(
            [
                {"order": 1, "word": "better", "accentContrast": dict(CONTRAST)},
                {"order": 2, "word": "water", "accentContrast": dict(CONTRAST)},
            ]
        )

        prune(
            self.problems("930/EN_GB/sentence: 'better' sounded like bedder"),
            self.dir,
        )

        words = self.load_gb_words()
        self.assertNotIn("accentContrast", words[0])
        self.assertIn("accentContrast", words[1])

    def test_sentence_problem_with_duplicate_word_is_ambiguous(self):
        self.write_gb(
            [
                {"order": 1, "word": "can't", "accentContrast": dict(CONTRAST)},
                {"order": 2, "word": "can't", "accentContrast": dict(CONTRAST)},
            ]
        )

        with self.assertRaisesRegex(ValueError, "ambiguous|모호"):
            prune(
                self.problems("930/EN_GB/sentence: 'Can't' sounded like kant"),
                self.dir,
            )


class GoldenDetectionGateTests(unittest.TestCase):
    """주기 드리프트 감시 게이트 (LAN-389) — 오류 검출 소실만 잡는다."""

    @staticmethod
    def rows(label, misses_per_run):
        return [
            {"label": label, "missed": missed, "falsePositives": []}
            for missed in misses_per_run
        ]

    def test_majority_miss_fails_gate(self):
        from scripts.eval_pronunciation_golden import _detection_gate_passes

        rows = self.rows("s3_stress", [["yesterday:STRESS"]] * 3 + [[]] * 2)

        self.assertFalse(_detection_gate_passes(rows))

    def test_minority_miss_passes_gate(self):
        from scripts.eval_pronunciation_golden import _detection_gate_passes

        rows = self.rows("s1_stress", [["hiking:STRESS"]] * 2 + [[]] * 3)

        self.assertTrue(_detection_gate_passes(rows))

    def test_measurement_errors_count_as_misses(self):
        from scripts.eval_pronunciation_golden import _detection_gate_passes

        rows = self.rows("s3_stress", [[]] * 2) + [
            {"label": "s3_stress", "error": "boom"} for _ in range(3)
        ]

        self.assertFalse(_detection_gate_passes(rows))

    def test_false_positives_do_not_fail_gate(self):
        from scripts.eval_pronunciation_golden import _detection_gate_passes

        # 오탐(diner류)은 허용 기준이 기획 미정이라 게이트가 아닌 리포트로 관측한다
        rows = [
            {"label": "s2_correct", "missed": [], "falsePositives": ["diner:SOUND"]}
            for _ in range(5)
        ]

        self.assertTrue(_detection_gate_passes(rows))


if __name__ == "__main__":
    unittest.main()
