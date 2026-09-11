# 기억 품질 평가가 문맥 누락과 동등한 날짜·번역 표현을 구분하는지 검사한다.
import unittest
from types import SimpleNamespace

from scripts.evaluate_memory_quality import acceptance_errors


class MemoryQualityEvaluationTests(unittest.TestCase):
    def check_candidates(self, contents, **criteria):
        candidates = [SimpleNamespace(content=text, memoryType=SimpleNamespace(value="EVENT"))
                      for text in contents]
        return acceptance_errors({"min": 1, "max": 3, "types": ["EVENT"], **criteria}, candidates)

    def test_context_must_be_present_in_the_same_memory(self):
        criteria = {"requiredTogether": [["스페인어", "앱"]]}
        self.assertEqual(self.check_candidates(
            ["스페인어 시험을 준비한다", "앱으로 공부한다"], **criteria,
        ), ["missing_self_contained_detail"])
        self.assertEqual(self.check_candidates(["스페인어 시험을 앱으로 준비한다"], **criteria), [])

    def test_equivalent_dates_and_translations_are_accepted(self):
        self.assertEqual(self.check_candidates(
            ["2026년 9월 7일 하이킹을 했다"],
            eventRequired=["2026-09-07"], requiredAny=[["등산", "하이킹"]],
        ), [])
        self.assertIn("event_detail", self.check_candidates(
            ["2026년 9월 8일 하이킹을 했다"], eventRequired=["2026-09-07"],
        ))
