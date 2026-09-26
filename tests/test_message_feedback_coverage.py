# 메시지 피드백의 근거 스키마와 한 번의 근거 복구 동작을 검증한다.
import copy
import json
import unittest
from unittest.mock import patch

from app.conversation.application import next_message_service as service
from app.core.structured_output import json_schema_response_format
from app.main import create_app
from tests.test_conversation_api import (
    FakeOpenAI,
    good_message_feedback,
    make_client,
    make_settings,
    message_feedback_candidate_with_evidence,
    valid_message_feedback_payload,
)


class MessageFeedbackCoverageTests(unittest.TestCase):
    def setUp(self):
        service.clear_message_feedback_cache()
        self.client = make_client(create_app(make_settings(
            openrouter_api_key="test", openrouter_model="test",
            message_feedback_review_enabled=False,
        )))

    def test_provider_schema_pairs_status_with_answer_type(self):
        schema = json_schema_response_format(
            service._MessageFeedbackStructuredOutput, name="feedback",
        )["json_schema"]["schema"]
        variants = schema["properties"]["coverageEvidence"]["items"]["anyOf"]
        self.assertEqual(len(variants), 2)
        pairs = {}
        for variant in variants:
            branch = schema["$defs"][variant["$ref"].split("/")[-1]]
            properties = branch["properties"]
            pairs[properties["status"]["const"]] = properties["answerExcerpt"]["type"]
            self.assertEqual(set(branch["required"]), set(properties))
            self.assertFalse(branch["additionalProperties"])
        self.assertEqual(pairs, {"ANSWERED": "string", "MISSING": "null"})

    def test_invalid_answer_evidence_is_repaired_once_without_changing_scores(self):
        for invalid_excerpt in (None, "I gave you my number", "why"):
            with self.subTest(invalid_excerpt=invalid_excerpt):
                service.clear_message_feedback_cache()
                payload = valid_message_feedback_payload()
                payload["userMessage"] = "why, why do you wanna know that?"
                valid = message_feedback_candidate_with_evidence(
                    good_message_feedback(1001),
                    coverage_evidence=[{
                        "requestExcerpt": payload["evaluationContext"]["content"],
                        "answerExcerpt": payload["userMessage"],
                        "status": "ANSWERED",
                    }],
                )
                valid["detectedPatterns"] = []
                invalid = copy.deepcopy(valid)
                invalid["coverageEvidence"][0]["answerExcerpt"] = invalid_excerpt
                fake = FakeOpenAI(contents=[json.dumps(invalid), json.dumps(valid)])
                with patch("app.core.openai_client.OpenAI", return_value=fake):
                    response = self.client.post(
                        "/api/v1/conversation/message-feedback", json=payload,
                    )
                self.assertEqual(response.status_code, 202)
                data = response.json()["data"]
                self.assertEqual(data["feedbackStatus"], "PREPARING")
                completed = data["completedFeedback"]
                self.assertTrue(completed["candidateWasRepaired"])
                self.assertEqual(completed["scoreEvidence"], valid["scoreEvidence"])
                self.assertEqual(
                    completed["adjudicationEvidence"]["coverageEvidence"],
                    valid["coverageEvidence"],
                )
                self.assertEqual(len(fake.completions.calls), 2)
                repair_prompt = fake.completions.calls[1]["messages"][1]["content"]
                expected = ("ANSWERED coverage requires answerExcerpt"
                            if invalid_excerpt is None else "exactly once")
                self.assertIn(expected, repair_prompt)
                for call in fake.completions.calls:
                    self.assertTrue(call["response_format"]["json_schema"]["strict"])

    def test_null_answer_after_repair_still_fails_without_cache(self):
        invalid = message_feedback_candidate_with_evidence(good_message_feedback(1001))
        invalid["detectedPatterns"] = []
        invalid["coverageEvidence"][0]["answerExcerpt"] = None
        fake = FakeOpenAI(contents=[json.dumps(invalid), json.dumps(invalid)])
        with patch("app.core.openai_client.OpenAI", return_value=fake):
            response = self.client.post(
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
            )
        self.assertEqual(response.json()["data"]["feedbackStatus"], "FAILED")
        self.assertEqual(len(fake.completions.calls), 2)
        self.assertIsNone(service.get_cached_message_feedback(100, 1001))

    def test_answer_repair_preserves_judgment_and_requires_unique_original_span(self):
        instruction = service._message_feedback_repair_instruction(
            service.AiResponseInvalidError("message_feedback_answer_evidence"),
        )
        for requirement in (
            "one contiguous span", "User utterance", "exactly once",
            "include surrounding words", "full user utterance is allowed",
            "do not change ANSWERED to MISSING",
        ):
            self.assertIn(requirement, instruction)
