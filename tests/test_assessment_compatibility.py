# 구형 BE와 신형 BE의 평가 계약을 동일 AI 인스턴스에서 검증한다.
import json
import unittest
from unittest.mock import patch

from app.main import create_app
from app.models.conversation import LegacySessionLevelAssessmentCandidate
from tests.test_conversation_api import (
    FakeOpenAI, make_client, make_settings, valid_assessment_messages,
    valid_level_assessment, valid_session_feedback_payload,
)


LEGACY = "text-level-v1.3"
SCORE = "text-score-v2.0"


def legacy_assessment():
    """환산 결과가 아닌 구형 모델의 독립적인 4단계 관찰 fixture다."""
    assessment = valid_level_assessment()
    for message in assessment["core"]["messages"]:
        for domain in message["domains"].values():
            domain["level"] = 4 if domain.pop("score") is not None else None
    return assessment


class AssessmentCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.client = make_client(create_app(make_settings(
            openrouter_api_key="local-test", openrouter_model="test",
        )))
        self.payload = valid_session_feedback_payload()
        self.payload["assessmentMessages"] = valid_assessment_messages()

    def request(self, assessment, version=None, retry=None):
        contents = [json.dumps({"sessionId": 100, "levelAssessment": assessment})]
        if retry is not None:
            contents.append(json.dumps({"levelAssessment": retry}))
        fake = FakeOpenAI(contents=contents)
        headers = {} if version is None else {"X-Landit-Assessment-Version": version}
        with patch("app.core.openai_client.OpenAI", return_value=fake):
            response = self.client.post(
                "/api/v1/conversation/session-level-assessment",
                json=self.payload, headers=headers,
            )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"], fake.completions.calls

    def test_default_and_explicit_legacy_preserve_level_and_single_call(self):
        for version in (None, LEGACY):
            with self.subTest(version=version):
                data, calls = self.request(legacy_assessment(), version)
                self.assertEqual(data["assessmentVersion"], LEGACY)
                self.assertEqual(data["levelAssessment"], legacy_assessment())
                self.assertEqual(len(calls), 1)
                prompt = calls[0]["messages"][0]["content"]
                self.assertIn("integer level 1 through 5", prompt)
                self.assertNotIn("1 through 100", prompt)
                schema = json.dumps(calls[0]["response_format"])
                self.assertIn('"level"', schema)
                self.assertNotIn('"score"', schema)

    def test_v2_and_v1_requests_on_same_instance_do_not_change_each_other(self):
        for version, assessment in ((SCORE, valid_level_assessment()),
                                    (LEGACY, legacy_assessment()),
                                    (SCORE, valid_level_assessment())):
            with self.subTest(version=version):
                data, calls = self.request(assessment, version)
                self.assertEqual(data["levelAssessment"], assessment)
                self.assertEqual(data["assessmentVersion"], version)
                self.assertEqual(len(calls), 1)

    def test_legacy_retry_keeps_schema_rubric_and_original_value(self):
        invalid = legacy_assessment()
        invalid["core"]["messages"][0]["domains"]["grammar"]["level"] = 90
        data, calls = self.request(invalid, retry=legacy_assessment())
        self.assertEqual(data["levelAssessment"], legacy_assessment())
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIn("integer level 1 through 5", call["messages"][0]["content"])
            self.assertNotIn('"score"', json.dumps(call["response_format"]))

    def test_unobserved_and_non_latin_legacy_domains_keep_level_null(self):
        for message in self.payload["assessmentMessages"]:
            message["userMessage"] = "잘 모르겠어요."
        assessment = legacy_assessment()
        for message in assessment["core"]["messages"]:
            for domain in message["domains"].values():
                domain["evidenceExcerpt"] = "잘 모르겠어요."
        data, calls = self.request(assessment)
        self.assertIsNone(data["levelAssessment"]["details"])
        self.assertEqual(len(calls), 1)
        for message in data["levelAssessment"]["core"]["messages"]:
            for domain in message["domains"].values():
                self.assertEqual(domain, {"level": None, "evidenceStatus": "NOT_OBSERVED",
                                          "evidenceExcerpt": None})

    def test_invalid_version_is_rejected_before_llm_call(self):
        with patch("app.core.openai_client.OpenAI") as factory:
            response = self.client.post(
                "/api/v1/conversation/session-level-assessment", json=self.payload,
                headers={"X-Landit-Assessment-Version": "unknown"},
            )
        self.assertEqual(response.status_code, 400)
        factory.assert_not_called()

    def test_legacy_rejects_score_alias_mixed_fields_and_non_integer_values(self):
        from pydantic import ValidationError
        for value in (0, 6, 4.0, True, "4"):
            assessment = legacy_assessment()
            assessment["core"]["messages"][0]["domains"]["grammar"]["level"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                LegacySessionLevelAssessmentCandidate.model_validate(assessment)
        for mixed in (False, True):
            assessment = legacy_assessment()
            domain = assessment["core"]["messages"][0]["domains"]["grammar"]
            domain["score"] = 4
            if not mixed:
                del domain["level"]
            with self.subTest(mixed=mixed), self.assertRaises(ValidationError):
                LegacySessionLevelAssessmentCandidate.model_validate(assessment)

    def test_openapi_documents_default_version_and_both_numeric_contracts(self):
        schema = self.client.get("/openapi.json").json()
        operation = schema["paths"]["/api/v1/conversation/session-level-assessment"]["post"]
        header = next(p for p in operation["parameters"] if p["name"] == "X-Landit-Assessment-Version")
        self.assertEqual(header["schema"]["default"], LEGACY)
        models = schema["components"]["schemas"]
        legacy = models["LegacySessionAssessmentDomain"]["properties"]["level"]
        score = models["SessionAssessmentDomain"]["properties"]["score"]
        self.assertEqual(legacy["anyOf"][0]["maximum"], 5)
        self.assertEqual(score["anyOf"][0]["maximum"], 100)
        feedback = models["SessionFeedbackResponse"]["properties"]["highlightMessage"]
        self.assertTrue(feedback["deprecated"])
