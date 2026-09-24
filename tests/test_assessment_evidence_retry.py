# 수준 평가 재시도에 검증 사유를 전달하고 원문 인용 계약을 계속 지키는지 검증한다.
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from app.conversation.application import next_message_service as service
from app.main import create_app
from app.models.conversation import SessionFeedbackRequest
from tests.test_conversation_api import (
    FakeOpenAI,
    make_client,
    make_settings,
    valid_assessment_messages,
    valid_level_assessment,
    valid_session_feedback_payload,
)


class AssessmentEvidenceRetryTests(unittest.TestCase):
    def setUp(self):
        self.payload = valid_session_feedback_payload()
        self.payload["assessmentMessages"] = valid_assessment_messages()
        self.settings = make_settings(openrouter_api_key="test", openrouter_model="test")

    def _request(self, *responses):
        fake = FakeOpenAI(contents=[json.dumps(value) for value in responses])
        with patch("app.core.openai_client.OpenAI", return_value=fake):
            response = make_client(create_app(self.settings)).post(
                "/api/v1/conversation/session-level-assessment", json=self.payload,
            )
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["levelAssessment"], fake.completions.calls

    def test_retry_receives_mismatched_field_and_preserves_valid_core(self):
        for domain in valid_level_assessment()["core"]["messages"][0]["domains"]:
            with self.subTest(domain=domain):
                invalid = valid_level_assessment()
                invalid["core"]["messages"][0]["domains"][domain]["evidenceExcerpt"] = (
                    "I like pizza ... spicy."
                )
                valid = valid_level_assessment()
                result, calls = self._request(
                    {"sessionId": 100, "levelAssessment": invalid},
                    {"levelAssessment": {"core": valid["core"]}},
                )
                self.assertEqual(result["core"], valid["core"])
                self.assertIsNone(result["details"])
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0]["messages"][1], calls[1]["messages"][1])
                prompt = calls[1]["messages"][0]["content"]
                self.assertIn("assessment_evidence_mismatch", prompt)
                self.assertIn(f"core.messages.[].domains.{domain}.evidenceExcerpt", prompt)
                self.assertIn("exact contiguous span", prompt)
                self.assertIn("combine separate spans, or insert ellipses", prompt)
                self.assertNotIn("I like pizza ... spicy.", prompt)
                self.assertNotIn("Server validation JSON", calls[0]["messages"][0]["content"])

    def test_retry_still_rejects_fabricated_or_other_message_evidence(self):
        for quote in ("I like pizza ... spicy.", "I ate pasta yesterday.", "invented answer"):
            with self.subTest(quote=quote):
                invalid = valid_level_assessment()
                invalid["core"]["messages"][0]["domains"]["grammar"]["evidenceExcerpt"] = quote
                result, calls = self._request(
                    {"sessionId": 100, "levelAssessment": invalid},
                    {"levelAssessment": invalid},
                )
                self.assertIsNone(result)
                self.assertEqual(len(calls), 2)

    def test_successful_initial_result_is_unchanged_and_not_retried(self):
        valid = valid_level_assessment()
        result, calls = self._request({"sessionId": 100, "levelAssessment": valid})
        self.assertEqual(result, valid)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Server validation JSON", calls[0]["messages"][0]["content"])

    def test_schema_retry_contains_field_and_type_but_no_invalid_output(self):
        invalid = valid_level_assessment()
        invalid["core"]["messages"][0]["domains"]["grammar"]["level"] = "private-response"
        valid = valid_level_assessment()
        result, calls = self._request(
            {"sessionId": 100, "levelAssessment": invalid},
            {"levelAssessment": {"core": valid["core"]}},
        )
        self.assertEqual(result["core"], valid["core"])
        prompt = calls[1]["messages"][0]["content"]
        self.assertIn("assessment_core_schema", prompt)
        self.assertIn("domains.grammar.level", prompt)
        self.assertNotIn("private-response", prompt)
        self.assertNotIn("An evidenceExcerpt was not found", prompt)

    def test_combined_feedback_path_also_passes_validation_failure_to_retry(self):
        request = SessionFeedbackRequest.model_validate(self.payload)
        valid = valid_level_assessment()
        invalid = deepcopy(valid)
        invalid["core"]["messages"][0]["domains"]["grammar"]["evidenceExcerpt"] = "bad quote"
        entries = [
            SimpleNamespace(feedback=SimpleNamespace(messageId=m["messageId"]),
                            user_message=m["userMessage"])
            for m in self.payload["assessmentMessages"]
        ]
        fake = FakeOpenAI(contents=[
            json.dumps({"sessionId": 100, "levelAssessment": invalid}),
            json.dumps({"levelAssessment": {"core": valid["core"]}}),
        ])
        with patch("app.core.openai_client.OpenAI", return_value=fake):
            _, assessment = service._request_session_feedback_with_level_assessment(
                self.settings, request, entries, "system", "user",
            )
        self.assertEqual(assessment.core.model_dump(mode="json"), valid["core"])
        self.assertEqual(len(fake.completions.calls), 2)
        self.assertIn("assessment_evidence_mismatch",
                      fake.completions.calls[1]["messages"][0]["content"])

    def test_untrusted_exception_message_and_field_names_do_not_enter_system_prompt(self):
        failure = service.AssessmentValidationError("private-exception", "private-field")
        prompt = service._session_level_assessment_retry_system_prompt(failure)
        self.assertNotIn("private-", prompt)
        self.assertIn("<field>", prompt)
