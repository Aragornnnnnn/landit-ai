# 실제 SDK 이벤트에서 진단 정보 보존과 민감정보 제거 및 실패 누락 방지를 검증한다.
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import sentry_sdk
from pydantic import BaseModel, ConfigDict, ValidationError

from app.common.failure_observation import observe, request_id
from app.core.sentry import init_sentry
from app.conversation.application import next_message_service as service
from app.free_talk.application.correction_service import unexpected_turn_correction
from app.free_talk.application.conversation_service import _submitted_turn_correction
from app.main import create_app
from app.models.conversation import SessionLevelAssessmentRequest
from tests.test_failure_observation import MemoryTransport
from tests.test_conversation_api import (
    valid_assessment_messages, valid_level_assessment, valid_session_feedback_payload,
)
from test_app import make_settings, make_client


class FailureDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        actual_init = sentry_sdk.init
        with patch("app.core.sentry.sentry_sdk.init",
                   side_effect=lambda **options: actual_init(**options, transport=self.transport)):
            init_sentry(make_settings(sentry_dsn="https://public@example.invalid/1"))

    def tearDown(self):
        sentry_sdk.get_client().close()

    def test_validation_fields_and_types_survive_without_values_or_arbitrary_keys(self):
        class Input(BaseModel):
            model_config = ConfigDict(extra="forbid")
            sessionId: int

        try:
            try:
                Input.model_validate({"sessionId": "secret-input", "secret-key": "secret-value"})
            except ValidationError as cause:
                raise service.AiResponseInvalidError("schema_validation") from cause
        except service.AiResponseInvalidError as failure:
            observe(workflow="feedback", failure_stage="validation", reason="generation_failed",
                    outcome="failed", exc=failure)
        event = self.transport.events[0]
        self.assertEqual(event["contexts"]["failure"]["validation_errors"], [
            {"field": "sessionId", "type": "int_parsing"},
            {"field": "<field>", "type": "extra_forbidden"},
        ])
        self.assertEqual(event["tags"]["validation_reason"], "schema_validation")
        self.assertNotIn("secret-", json.dumps(event))
        self.assertTrue(event["exception"]["values"][-1]["stacktrace"]["frames"])

    def test_provider_status_survives_without_body_headers_or_url(self):
        response = httpx.Response(429, request=httpx.Request("POST", "https://secret-host.test"),
                                 json={"message": "secret-provider-body"})
        try:
            raise openai.RateLimitError("secret-error", response=response, body={"key": "secret-key"})
        except openai.RateLimitError as failure:
            observe(workflow="feedback", failure_stage="generation", reason="generation_failed",
                    outcome="failed", exc=failure)
        event = self.transport.events[0]
        self.assertEqual(event["tags"]["upstream_status"], "429")
        self.assertNotIn("secret-", json.dumps(event))

    def test_unrecognized_reason_is_not_transmitted(self):
        observe(workflow="feedback", failure_stage="validation", reason="generation_failed",
                outcome="failed", exc=service.AiResponseInvalidError("secret-model-output"))
        self.assertNotIn("secret-", json.dumps(self.transport.events))

    def test_level_assessment_final_failure_retains_specific_reason_and_stack(self):
        payload = valid_session_feedback_payload()
        payload["assessmentMessages"] = valid_assessment_messages()
        request = SessionLevelAssessmentRequest.model_validate(payload)
        malformed = {"levelAssessment": {"core": {"messages": "secret-response"}}}
        module = "app.conversation.application.next_message_service."
        with (patch(module + "_request_json_completion_with_format_fallback",
                    return_value=({"sessionId": request.sessionId, **malformed}, None)),
              patch(module + "_request_json_completion", return_value=malformed)):
            result = service.generate_session_level_assessment(request, make_settings())
        self.assertIsNone(result.levelAssessment)
        self.assertEqual(len(self.transport.events), 1)
        event = self.transport.events[0]
        self.assertEqual(event["tags"]["validation_reason"], "assessment_core_schema")
        self.assertEqual(event["tags"]["attempt"], "2")
        self.assertNotIn("secret-", json.dumps(event))
        self.assertIn("_validate_session_level_assessment", json.dumps(event))

    def test_message_order_and_evidence_failures_have_distinct_reasons(self):
        payload = valid_session_feedback_payload()
        payload["assessmentMessages"] = valid_assessment_messages()
        request = SessionLevelAssessmentRequest.model_validate(payload)
        for reason in ("assessment_message_ids", "assessment_evidence_mismatch"):
            assessment = valid_level_assessment()
            if reason == "assessment_message_ids":
                assessment["core"]["messages"].reverse()
            else:
                assessment["core"]["messages"][0]["domains"]["grammar"]["evidenceExcerpt"] = "secret-invalid-evidence"
            failures = []
            result = service._recover_session_level_assessment(
                {"sessionId": request.sessionId, "levelAssessment": assessment}, request, None,
                failures=failures)
            self.assertIsNone(result)
            self.assertEqual(failures[-1].reason, reason)

    def test_correction_bug_is_reported_once_and_response_still_falls_back(self):
        try:
            raise ValueError("secret-user-utterance")
        except ValueError as failure:
            result = unexpected_turn_correction(SimpleNamespace(sessionId=1, submittedMessageId=2), failure)
            sentry_sdk.capture_exception(failure)
        self.assertIsNone(result.correction)
        self.assertEqual(len(self.transport.events), 1)
        event = self.transport.events[0]
        self.assertEqual(event["tags"]["workflow"], "free_talk_turn_correction")
        self.assertIn("test_correction_bug", json.dumps(event))
        self.assertNotIn("secret-", json.dumps(event))

    def test_correction_worker_inherits_request_id(self):
        token = request_id.set("11111111-2222-4333-8444-555555555555")
        try:
            with (ThreadPoolExecutor(max_workers=1) as executor,
                  patch("app.free_talk.application.conversation_service.generate_turn_correction",
                        side_effect=lambda *_: request_id.get())):
                future = _submitted_turn_correction(executor, None, None)
                self.assertEqual(future.result(), request_id.get())
        finally:
            request_id.reset(token)

    def test_request_id_is_preserved_without_enabling_authentication(self):
        app = create_app(make_settings())
        @app.get("/api/test-correlation")
        def correlation():
            return {"id": request_id.get()}
        expected = "11111111-2222-4333-8444-555555555555"
        client = make_client(app)
        self.assertEqual(client.get("/api/test-correlation", headers={"X-Request-Id": expected}).json()["id"], expected)
        self.assertNotEqual(client.get("/api/test-correlation", headers={"X-Request-Id": "secret-input"}).json()["id"], "secret-input")

    def test_synthetic_failure_has_code_location(self):
        observe(workflow="feedback", failure_stage="result", reason="result_missing", outcome="failed")
        event = self.transport.events[0]
        self.assertTrue(event["exception"]["values"][-1]["stacktrace"]["frames"])
        self.assertEqual(event["exception"]["values"][-1]["value"], "feedback: result_missing")
