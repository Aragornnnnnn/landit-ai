# 100점 평가의 숫자·근거 계약과 학습 레벨 변환 경계를 검증한다.
import unittest

from pydantic import ValidationError

from app.models.conversation import SessionAssessmentDomain
from scripts.evaluate_onboarding_level_blind import be_policy
from test_conversation_api import valid_level_assessment


class HundredPointAssessmentTests(unittest.TestCase):
    def test_every_integer_score_is_valid_and_preserved(self):
        for score in range(1, 101):
            with self.subTest(score=score):
                domain = SessionAssessmentDomain.model_validate({
                    "score": score, "evidenceStatus": "OBSERVED", "evidenceExcerpt": "answer",
                })
                self.assertEqual(domain.model_dump()["score"], score)
                self.assertNotIn("level", domain.model_dump())

    def test_invalid_scores_and_legacy_level_are_rejected(self):
        for score in (0, 101, -1, 50.5, "50", True, None):
            with self.subTest(score=score), self.assertRaises(ValidationError):
                SessionAssessmentDomain.model_validate({
                    "score": score, "evidenceStatus": "OBSERVED", "evidenceExcerpt": "answer",
                })
        with self.assertRaises(ValidationError):
            SessionAssessmentDomain.model_validate({
                "level": 5, "evidenceStatus": "OBSERVED", "evidenceExcerpt": "answer",
            })

    def test_unobserved_domains_do_not_invent_scores(self):
        for status in ("NOT_OBSERVED", "INSUFFICIENT_EVIDENCE"):
            self.assertIsNone(SessionAssessmentDomain(evidenceStatus=status).score)
            with self.assertRaises(ValidationError):
                SessionAssessmentDomain(score=50, evidenceStatus=status)
        with self.assertRaises(ValidationError):
            SessionAssessmentDomain(score=50, evidenceStatus="OBSERVED")

    def test_evaluation_runner_matches_twenty_point_learning_level_bands(self):
        for score, expected in ((1, 1), (20, 1), (21, 2), (40, 2), (41, 3),
                                (60, 3), (61, 4), (80, 4), (81, 5), (100, 5)):
            with self.subTest(score=score):
                assessment = valid_level_assessment()
                messages = assessment["core"]["messages"]
                assessment["core"]["messages"] = messages * 2
                for message in assessment["core"]["messages"]:
                    for domain in message["domains"].values():
                        domain["score"] = score
                result = be_policy(assessment)
                self.assertEqual(result["overallScore"], f"{score:.2f}")
                self.assertEqual(result["assessedLevel"], expected)
                self.assertEqual(result["appliedLevel"], expected)
