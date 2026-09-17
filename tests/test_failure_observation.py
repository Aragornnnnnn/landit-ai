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
