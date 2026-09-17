# 외부 전송 없이 실제 Sentry 이벤트의 정책·중복·민감정보 제거를 검증한다.
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import sentry_sdk
from sentry_sdk.transport import Transport
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from pydantic import BaseModel

from app.common.failure_observation import observe
from app.core.sentry import scrub_sensitive_request_data, init_sentry
from app.free_talk.llm.json_completion import AiResponseInvalidError, AiGenerationFailedError
from app.free_talk.application.memory_candidate_review import _refinement_failure_reason
from app.conversation.application import next_message_service as service
from test_app import make_settings, make_client
from app.main import create_app


class MemoryTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") == "event":
                self.events.append(item.payload.json)


class FailureObservationTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        self.sdk = sentry_sdk.init(
            dsn="https://public@example.invalid/1", transport=self.transport,
            before_send=scrub_sensitive_request_data, default_integrations=False,
            integrations=[FastApiIntegration(), StarletteIntegration(), LoggingIntegration(event_level=None)],
            include_local_variables=True,  # 최종 필터도 방어하는지 의도적으로 켠다.
        )

    def tearDown(self):
        self.sdk.__exit__(None, None, None)

    def test_recovered_and_rejected_are_not_sent_by_explicit_or_automatic_capture(self):
        for outcome in ("recovered", "expected_rejection"):
            exc = AiResponseInvalidError("secret-output", raw_content="secret-content")
            observe(workflow="closing", failure_stage="validation", reason="safe_fallback",
                    outcome=outcome, exc=exc)
            sentry_sdk.capture_exception(exc)
        self.assertEqual(self.transport.events, [])

    def test_config_defect_is_sent_even_when_fallback_succeeds(self):
        error = AiGenerationFailedError()
        error.__cause__ = RuntimeError("secret-provider-key")
        observe(workflow="closing", failure_stage="generation", reason="safe_fallback",
                outcome="recovered", exc=error)
        self.assertEqual(len(self.transport.events), 1)
        self.assertEqual(self.transport.events[0]["tags"]["outcome"], "failed")
        self.assertNotIn("secret-provider-key", json.dumps(self.transport.events))

    def test_recovered_missing_completion_content_is_an_output_contract_failure(self):
        try:
            service._extract_message_content(SimpleNamespace(choices=[]))
        except service.AiResponseInvalidError as failure:
            observe(workflow="closing", failure_stage="output_validation", reason="safe_fallback",
                    outcome="recovered", exc=failure)
        self.assertEqual(self.transport.events, [])

    def test_local_file_defect_is_not_treated_as_transient_provider_io(self):
        failure = AiGenerationFailedError()
        failure.__cause__ = FileNotFoundError("secret-config-path")
        observe(workflow="closing", failure_stage="generation", reason="safe_fallback",
                outcome="recovered", exc=failure)
        self.assertEqual(len(self.transport.events), 1)
        self.assertEqual(self.transport.events[0]["tags"]["outcome"], "failed")
        self.assertNotIn("secret-", json.dumps(self.transport.events))

    def test_event_preserves_stack_and_cause_types_but_no_sensitive_values(self):
        sentry_sdk.set_user({"email": "secret-email"})
        sentry_sdk.set_context("payload", {"text": "secret-context"})
        sentry_sdk.set_extra("body", "secret-body")
        sentry_sdk.add_breadcrumb(message="secret-breadcrumb", data={"token": "secret-token"})
        try:
            try:
                raise ValueError("secret-cause")
            except ValueError as cause:
                raise RuntimeError("secret-exception") from cause
        except RuntimeError as failure:
            observe(workflow="feedback", failure_stage="storage", reason="storage_failed",
                    outcome="failed", exc=failure)
            sentry_sdk.capture_exception(failure)
        self.assertEqual(len(self.transport.events), 1)
        event = self.transport.events[0]
        self.assertNotIn("secret-", json.dumps(event))
        self.assertEqual([x["type"] for x in event["exception"]["values"]], ["ValueError", "RuntimeError"])
        self.assertTrue(event["exception"]["values"][-1]["stacktrace"]["frames"])

    def test_unhandled_fastapi_failure_is_sent_once(self):
        app = create_app(make_settings())

        @app.get("/api/test-failure")
        def fail():
            raise RuntimeError("secret-unhandled")

        response = make_client(app, raise_server_exceptions=False).get("/api/test-failure")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.transport.events), 1)
        self.assertNotIn("secret-unhandled", json.dumps(self.transport.events))
        self.assertTrue(self.transport.events[0]["tags"].get("request_id"))

    def test_authenticated_contract_violation_is_distinct_from_external_request(self):
        app = create_app(make_settings(landit_ai_internal_token="secret-auth"))

        class Input(BaseModel):
            count: int

        @app.post("/api/test-contract")
        def accept(payload: Input):
            return {"ok": True}

        client = make_client(app)
        self.assertEqual(client.post("/api/test-contract", json={}).status_code, 401)
        self.assertEqual(self.transport.events, [])
        correlation = "5c8e22b5-07c0-4c93-90f5-1c023411ffec"
        response = client.post("/api/test-contract", json={}, headers={
            "X-Landit-Internal-Token": "secret-auth", "X-Request-Id": correlation})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.transport.events), 1)
        self.assertEqual(self.transport.events[0]["tags"]["request_id"], correlation)
        self.assertNotIn("secret-auth", json.dumps(self.transport.events))

    def test_http_405_keeps_allow_header_without_event(self):
        app = create_app(make_settings())
        response = make_client(app).post("/health")
        self.assertEqual(response.status_code, 405)
        self.assertIn("GET", response.headers["allow"])
        self.assertEqual(self.transport.events, [])

    def test_feedback_failed_body_reports_even_without_http_exception(self):
        with patch.object(service, "_generate_message_feedback_candidate",
                          side_effect=service.AiGenerationFailedError()):
            result = service.generate_message_feedback(SimpleNamespace(sessionId=1, messageId=2), make_settings())
        self.assertEqual(result.feedbackStatus.value, "FAILED")
        self.assertEqual(len(self.transport.events), 1)
        self.assertEqual(self.transport.events[0]["tags"]["workflow"], "message_feedback")

    def test_missing_assessment_core_reports_even_inside_success_response(self):
        request = SimpleNamespace(sessionId=1)
        with (patch.object(service, "_session_level_assessment_user_prompt", return_value=""),
              patch.object(service, "_request_json_completion_with_format_fallback", return_value=({}, None)),
              patch.object(service, "_recover_session_level_assessment", return_value=None),
              patch.object(service, "_retry_session_level_assessment_core", return_value=None)):
            result = service.generate_session_level_assessment(request, make_settings())
        self.assertIsNone(result.levelAssessment)
        self.assertEqual(len(self.transport.events), 1)
        self.assertEqual(self.transport.events[0]["tags"]["reason"], "core_missing")

    def test_normal_closing_recovery_has_metrics_but_no_event(self):
        with patch("app.common.failure_observation._counter") as counter:
            response = service._recover_closing_message_response({"innerThoughtType": []})
        self.assertEqual(response.aiMessage, "Okay.")
        self.assertEqual(self.transport.events, [])
        counter.add.assert_called_once()
        self.assertEqual(counter.add.call_args.args[1]["outcome"], "recovered")
        self.assertNotIn("request_id", counter.add.call_args.args[1])

    def test_missing_result_fingerprints_separate_workflows(self):
        for workflow in ("feedback", "level_assessment"):
            observe(workflow=workflow, failure_stage="result", reason="result_missing", outcome="failed")
        self.assertEqual(len(self.transport.events), 2)
        self.assertNotEqual(self.transport.events[0]["fingerprint"], self.transport.events[1]["fingerprint"])

    def test_memory_rejection_reasons_are_safe_and_distinct(self):
        draft = SimpleNamespace(content="2 dogs", sourceMessageIds=[1])
        review = SimpleNamespace(content="2 pet dogs", sourceMessageId=1, quote="dogs")
        context = {"conversationHistory": [{"messageId": 1, "role": "USER", "content": "2 dogs"}]}
        self.assertIsNone(_refinement_failure_reason(draft, review, context))
        for field, value, reason in [
            ("content", None, "refinement_fields_missing"),
            ("sourceMessageId", 2, "source_id_mismatch"),
            ("content", "3 dogs", "numbers_changed"),
            ("quote", "secret-mismatch", "quote_not_in_source"),
        ]:
            original = getattr(review, field)
            setattr(review, field, value)
            self.assertEqual(_refinement_failure_reason(draft, review, context), reason)
            setattr(review, field, original)
        context["conversationHistory"][0]["role"] = "AI"
        self.assertEqual(_refinement_failure_reason(draft, review, context), "source_message_missing_or_not_user")


class ProductionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        actual_init = sentry_sdk.init
        with patch("app.core.sentry.sentry_sdk.init",
                   side_effect=lambda **options: actual_init(**options, transport=self.transport)):
            init_sentry(make_settings(sentry_dsn="https://public@example.invalid/1"))

    def tearDown(self):
        sentry_sdk.get_client().close()

    def provider_failure(self, *, invalid_url=False):
        def reply(request):
            if invalid_url:
                raise httpx.UnsupportedProtocol("secret-base-url")
            return httpx.Response(429, json={"error": {"message": "secret-provider-message"}})
        with openai.OpenAI(api_key="secret-key", max_retries=0,
                           http_client=httpx.Client(transport=httpx.MockTransport(reply))) as client:
            try:
                client.chat.completions.create(model="test", messages=[{"role": "user", "content": "secret-input"}])
            except openai.OpenAIError as cause:
                failure = AiGenerationFailedError()
                failure.__cause__ = cause
                return failure
        self.fail("provider did not fail")

    def test_provider_failure_waits_for_final_outcome(self):
        recovered = self.provider_failure()
        observe(workflow="closing", failure_stage="generation", reason="safe_fallback",
                outcome="recovered", exc=recovered)
        self.assertEqual(self.transport.events, [])
        failed = self.provider_failure()
        observe(workflow="feedback", failure_stage="generation", reason="result_missing",
                outcome="failed", exc=failed)
        sentry_sdk.capture_exception(failed)
        self.assertEqual(len(self.transport.events), 1)
        self.assertEqual(self.transport.events[0]["tags"]["workflow"], "feedback")
        self.assertNotIn("secret-", json.dumps(self.transport.events))

    def test_invalid_provider_configuration_survives_successful_fallback(self):
        failure = self.provider_failure(invalid_url=True)
        observe(workflow="closing", failure_stage="generation", reason="safe_fallback",
                outcome="recovered", exc=failure)
        self.assertEqual(len(self.transport.events), 1)
        self.assertEqual(self.transport.events[0]["tags"]["reason"], "recovered_with_defect")
        self.assertNotIn("secret-", json.dumps(self.transport.events))
