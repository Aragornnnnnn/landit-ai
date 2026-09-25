# 수준 평가 출력 잘림, 최초 실패 보존과 원문 없는 호출 진단을 검증한다.
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tiktoken

from app.conversation.application import next_message_service as service
from app.conversation.llm.assessment_budget import assessment_output_budget
from app.conversation.llm.assessment_observation import completion_metadata
from app.models.conversation import SessionLevelAssessmentRequest
from tests.test_conversation_api import (
    make_settings, valid_assessment_messages, valid_level_assessment,
    valid_session_feedback_payload,
)


def assessment_request():
    payload = valid_session_feedback_payload()
    return SessionLevelAssessmentRequest(
        sessionId=100, scenario=payload["scenario"], expectedMessageIds=[1001, 1003],
        assessmentMessages=valid_assessment_messages(),
    )


def completion(content, finish="stop", **kwargs):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)],
        **kwargs,
    )


class AssessmentOutputBudgetTests(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(openrouter_api_key="private-secret", openrouter_model="test")
        self.valid = {"sessionId": 100, "levelAssessment": valid_level_assessment()}

    def run_responses(self, *responses):
        client = Mock()
        client.chat.completions.create.side_effect = responses
        with patch.object(service, "create_openai_client", return_value=client), self.assertLogs(
            "app.conversation.llm.assessment_observation", level="INFO",
        ) as logs:
            result = service.generate_session_level_assessment(assessment_request(), self.settings)
        diagnostic = json.loads(logs.records[-1].getMessage().split("assessment_diagnostics ", 1)[1])
        return result, client.chat.completions.create.call_args_list, diagnostic

    def test_output_limit_rejects_even_parseable_json_and_retries_once(self):
        for content in ("", '{"levelAssessment":', json.dumps(self.valid)):
            with self.subTest(content=content[:20]):
                result, calls, diagnostic = self.run_responses(
                    completion(content, "length"), completion(json.dumps(self.valid)),
                )
                self.assertIsNotNone(result.levelAssessment)
                self.assertEqual(len(calls), 2)
                self.assertGreaterEqual(calls[0].kwargs["max_tokens"], 2048)
                self.assertEqual(calls[0].kwargs["max_tokens"], calls[1].kwargs["max_tokens"])
                self.assertEqual(diagnostic["validations"][0]["validation_reason"], "completion_output_limit")
                self.assertIn("completion_output_limit", calls[1].kwargs["messages"][0]["content"])

    def test_initial_validation_and_final_truncation_are_both_preserved(self):
        invalid = deepcopy(self.valid)
        invalid["levelAssessment"]["core"]["messages"][0]["domains"]["grammar"]["evidenceExcerpt"] = "private-source"
        usage = SimpleNamespace(
            prompt_tokens=2297, completion_tokens=1536,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
        )
        result, calls, diagnostic = self.run_responses(
            completion(json.dumps(invalid)),
            completion('{"private-response":', "length", id="gen-1790315027-example",
                       _request_id="req-example", usage=usage),
        )
        self.assertIsNone(result.levelAssessment)
        self.assertEqual(len(calls), 2)
        self.assertEqual([v["validation_reason"] for v in diagnostic["validations"]],
                         ["assessment_evidence_mismatch", "completion_output_limit"])
        self.assertEqual([v["stage"] for v in diagnostic["validations"]], [1, 2])
        self.assertEqual(diagnostic["calls"][1]["completion_tokens"], 1536)
        self.assertEqual(diagnostic["calls"][1]["reasoning_tokens"], 0)
        self.assertEqual(diagnostic["calls"][1]["provider_request_id"], "req-example")
        self.assertGreaterEqual(diagnostic["calls"][1]["elapsed_ms"], 0)
        self.assertNotIn("private-", json.dumps(diagnostic))
        self.assertNotIn("I like pizza", json.dumps(diagnostic))

    def test_native_output_limit_is_detected_without_standard_finish_reason(self):
        truncated = completion("{}", None)
        truncated.choices[0].native_finish_reason = "max_output_tokens"
        result, calls, diagnostic = self.run_responses(
            truncated, completion(json.dumps(self.valid)),
        )
        self.assertIsNotNone(result.levelAssessment)
        self.assertEqual(len(calls), 2)
        self.assertEqual(diagnostic["validations"][0]["validation_reason"], "completion_output_limit")

    def test_missing_metadata_is_safe_and_request_context_does_not_leak(self):
        self.run_responses(completion("bad"), completion("bad"))
        result, calls, diagnostic = self.run_responses(
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.valid)))])
        )
        self.assertIsNotNone(result.levelAssessment)
        self.assertEqual(diagnostic["validations"], [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(diagnostic["calls"][0]["attempt"], 1)
        self.assertIsNone(diagnostic["calls"][0]["completion_tokens"])

    def test_arbitrary_provider_metadata_is_not_logged(self):
        malformed = completion("private-response", "private-source", id="sk-private-secret",
                               _request_id="Authorization: private-secret",
                               usage=SimpleNamespace(prompt_tokens=True, completion_tokens="private-source",
                                   completion_tokens_details=SimpleNamespace(reasoning_tokens=-1)))
        malformed.choices[0].native_finish_reason = ["private-source"]
        self.assertTrue(all(value is None for value in completion_metadata(malformed).values()))

    def test_non_assessment_completion_keeps_existing_behavior(self):
        client = Mock()
        client.chat.completions.create.return_value = completion('{}', "length")
        with patch.object(service, "create_openai_client", return_value=client):
            self.assertEqual(service._request_json_completion(self.settings, "system", "user", 10), {})

    def test_output_budget_handles_multiple_messages_and_long_escaped_evidence(self):
        encoding = tiktoken.get_encoding("o200k_base")
        for count in (1, 3, 10):
            for utterance in ("Please email me tomorrow.", 'I said "yes".\n서울 at 9:00. ' * 8):
                with self.subTest(count=count, utterance_length=len(utterance)):
                    request = assessment_request()
                    messages = [request.assessmentMessages[0].model_copy(update={
                        "messageId": index + 1, "userMessage": utterance,
                    }) for index in range(count)]
                    request = request.model_copy(update={
                        "expectedMessageIds": list(range(1, count + 1)), "assessmentMessages": messages,
                    })
                    core_message = valid_level_assessment()["core"]["messages"][0]
                    rows = []
                    for message in messages:
                        row = deepcopy(core_message)
                        row["messageId"] = message.messageId
                        for domain in row["domains"].values():
                            domain["evidenceExcerpt"] = utterance
                        rows.append(row)
                    data = {"sessionId": 100, "levelAssessment": {"core": {"messages": rows}}}
                    budget = assessment_output_budget(messages)
                    tokens = len(encoding.encode(json.dumps(data, ensure_ascii=False)))
                    self.assertLess(tokens, budget)
                    self.assertIsNotNone(service._recover_session_level_assessment(data, request, None))
        huge = assessment_request().assessmentMessages[0].model_copy(update={"userMessage": "long utterance " * 20000})
        self.assertEqual(assessment_output_budget([huge]), 16384)

    def test_schema_and_message_id_failures_remain_distinct_from_json_failures(self):
        schema_invalid = deepcopy(self.valid)
        schema_invalid["levelAssessment"]["core"]["messages"][0]["domains"]["grammar"]["level"] = 99
        message_invalid = deepcopy(self.valid)
        message_invalid["levelAssessment"]["core"]["messages"][0]["messageId"] = 9999
        for value, reason in (
            ("{}", "assessment_session_mismatch"), ("[]", "json_object_required"),
            ('{"sessionId":}', "json_object_invalid"),
            (json.dumps(schema_invalid), "assessment_core_schema"),
            (json.dumps(message_invalid), "assessment_message_ids"),
        ):
            with self.subTest(reason=reason):
                result, _, diagnostic = self.run_responses(completion(value), completion(value))
                self.assertIsNone(result.levelAssessment)
                self.assertEqual(diagnostic["validations"][0]["validation_reason"], reason)
