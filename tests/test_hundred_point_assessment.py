# 100점 평가의 숫자·근거 계약과 학습 레벨 변환 경계를 검증한다.
import json
import unittest

from pydantic import ValidationError

from app.conversation.application.next_message_service import _session_feedback_system_prompt
from app.models.conversation import SessionAssessmentDomain
from scripts.evaluate_onboarding_level_blind import be_policy
from test_conversation_api import valid_level_assessment


class HundredPointAssessmentTests(unittest.TestCase):
    """100점 스키마와 20점 구간 학습 레벨의 경계 계약을 검증한다."""
    def test_every_integer_score_is_valid_and_preserved(self):
        """1부터 100까지 모든 정수를 환산 없이 보존하고 구버전 level 필드를 내보내지 않는다."""
        for score in range(1, 101):
            with self.subTest(score=score):
                domain = SessionAssessmentDomain.model_validate({
                    "score": score, "evidenceStatus": "OBSERVED", "evidenceExcerpt": "answer",
                })
                self.assertEqual(domain.model_dump()["score"], score)
                self.assertNotIn("level", domain.model_dump())

    def test_invalid_scores_and_legacy_level_are_rejected(self):
        """범위 밖 값, 비정수 타입과 구버전 level 입력을 거부한다."""
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
        """미관찰 점수와 인용 없는 관찰 점수를 모두 거부한다."""
        for status in ("NOT_OBSERVED", "INSUFFICIENT_EVIDENCE"):
            self.assertIsNone(SessionAssessmentDomain(evidenceStatus=status).score)
            with self.assertRaises(ValidationError):
                SessionAssessmentDomain(score=50, evidenceStatus=status)
        with self.assertRaises(ValidationError):
            SessionAssessmentDomain(score=50, evidenceStatus="OBSERVED")

    def test_evaluation_runner_matches_twenty_point_learning_level_bands(self):
        """평가 도구의 종합 점수와 학습 레벨이 각 20점 구간 양 끝에서 일치한다."""
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

    def test_combined_feedback_schema_preserves_scores_without_highlight(self):
        """총평의 강조 문구 제거와 100점 영역 계약이 평가 포함 여부와 무관하게 공존한다."""
        for include_assessment in (False, True):
            with self.subTest(include_assessment=include_assessment):
                prompt = _session_feedback_system_prompt(include_assessment)
                schema_text = prompt.split("Output Schema:", 1)[1]
                example, _ = json.JSONDecoder().raw_decode(schema_text[schema_text.index("{"):])
                expected = {"sessionId", "summaryMessage", "growthFeedback", "usedExpressions"}
                if include_assessment:
                    expected.add("levelAssessment")
                self.assertEqual(set(example), expected)
                self.assertNotIn("highlightMessage", prompt)
                if include_assessment:
                    domains = example["levelAssessment"]["core"]["messages"][0]["domains"]
                    self.assertEqual(len(domains), 5)
                    for domain in domains.values():
                        self.assertIsNotNone(SessionAssessmentDomain.model_validate(domain).score)
