# 실제 요청·SDK 이벤트에서 작업 ID와 모델 출처 및 문맥 격리를 검증한다.
import asyncio
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from types import SimpleNamespace

import sentry_sdk

from app.common.failure_observation import observe
from app.common.observation_context import bind_model, for_failure, scope
from app.core.sentry import scrub_sensitive_request_data
from app.free_talk.application.conversation_service import _submitted_turn_correction
from app.free_talk.llm.json_completion import request_json_completion
from app.main import create_app
from tests.test_failure_observation import MemoryTransport
from test_app import make_client, make_settings
from test_conversation_api import valid_next_message_payload
from test_context_summary import _payload, _FakeAsyncCompletions
from app.free_talk.llm.embeddings import request_embeddings
from app.free_talk.application.context_summary_service import generate_context_summary
from app.pronunciation.llm.structured_completion import request_structured_pronunciation_completion
from test_free_talk_api import (
    FakeOpenAI, valid_turn_payload, valid_expression_recommendations_payload,
    valid_conversation_embeddings_payload, valid_memory_candidates_payload,
    valid_memory_resolution_payload,
)


class ObservationContextTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        self.sdk = sentry_sdk.init(
            dsn="https://public@example.invalid/1", transport=self.transport,
            before_send=scrub_sensitive_request_data, default_integrations=False,
        )
        self.context = scope(learning_session_id=None, free_talk_session_id=None,
                             message_id=None, model=None, provider=None,
                             http_route=None, http_method=None)
        self.context.__enter__()
        self.headers = {"X-Landit-Internal-Token": "test-auth", "X-Landit-User-Id": "42"}

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.sdk.__exit__(None, None, None)

    def report(self, exc=None):
        observe(workflow="feedback", failure_stage="validation", reason="invalid_result",
                outcome="failed", exc=exc)
        return self.transport.events[-1]

    def test_real_routes_map_session_meaning_and_current_message_explicitly(self):
        client = make_client(create_app(make_settings(landit_ai_internal_token="test-auth")),
                             raise_server_exceptions=False)
        cases = [
            ("conversation/next-message", "conversation.generate_next_message",
             valid_next_message_payload(), "learning_session_id", "100", "1001"),
            ("free-talk/turn", "free_talk.generate_turn", valid_turn_payload(sessionId=7),
             "free_talk_session_id", "7", None),
            ("free-talk/expression-recommendations", "free_talk.recommend_expressions",
             valid_expression_recommendations_payload(sessionId=100), "learning_session_id", "100", None),
            ("free-talk/conversation-embeddings", "free_talk.generate_conversation_embeddings",
             valid_conversation_embeddings_payload(sessionId=100), "learning_session_id", "100", None),
            ("free-talk/memory-candidates", "free_talk.generate_memory_candidates",
             valid_memory_candidates_payload(sessionId=100), "learning_session_id", "100", None),
            ("free-talk/memory-resolution", "free_talk.generate_memory_resolution",
             valid_memory_resolution_payload(), None, None, None),
        ]
        for route, target, payload, key, value, message in cases:
            with self.subTest(route=route):
                with patch("app.api." + target, side_effect=RuntimeError("secret-response")):
                    response = client.post("/api/v1/" + route + "?token=secret-query",
                                           json=payload, headers=self.headers)
                self.assertEqual(response.status_code, 500, response.text)
                event = self.transport.events[-1]
                tags = event["tags"]
                if key:
                    self.assertEqual(tags[key], value)
                else:
                    self.assertNotIn("learning_session_id", tags)
                    self.assertNotIn("free_talk_session_id", tags)
                self.assertEqual(tags.get("message_id"),
                                 str(payload["submittedMessageId"]) if "submittedMessageId" in payload else message)
                self.assertEqual(tags["http_route"], "/api/v1/" + route)
                self.assertEqual(tags["http_method"], "POST")
                self.assertEqual(event["user"], {"id": "42"})
                self.assertNotIn("secret-", json.dumps(event))
        self.assertEqual(for_failure(), {})

    def test_invalid_dto_and_untrusted_request_never_attach_domain_ids(self):
        client = make_client(create_app(make_settings(landit_ai_internal_token="test-auth")))
        response = client.post("/api/v1/conversation/next-message", headers=self.headers,
                               json={"sessionId": 100, "submittedMessageId": 23})
        self.assertEqual(response.status_code, 400)
        tags = self.transport.events[-1]["tags"]
        self.assertEqual(tags["http_route"], "/api/v1/conversation/next-message")
        self.assertNotIn("learning_session_id", tags)
        client = make_client(create_app(make_settings()), raise_server_exceptions=False)
        with patch("app.api.conversation.generate_next_message", side_effect=RuntimeError("failure")):
            response = client.post("/api/v1/conversation/next-message", headers=self.headers,
                                   json=valid_next_message_payload())
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("learning_session_id", self.transport.events[-1]["tags"])
        self.assertNotIn("user", self.transport.events[-1])

    def test_failure_model_survives_later_success_and_wrapping(self):
        settings = make_settings(openrouter_api_key="test", openrouter_model="default-model")
        fake = FakeOpenAI(contents=['not json', '{"ok": true}'])
        with scope(learning_session_id=100), patch("app.core.openai_client.OpenAI", return_value=fake):
            try:
                request_json_completion(settings=settings, system_prompt="secret-prompt", user_prompt="secret-body",
                                        model="vendor/model-a")
            except Exception as failure:
                original = failure
            request_json_completion(settings=settings, system_prompt="secret-prompt", user_prompt="secret-body",
                                    model="vendor/model-b")
            wrapped = RuntimeError("secret-wrapper")
            wrapped.__cause__ = original
        with scope(learning_session_id=200):
            event = self.report(wrapped)
        self.assertEqual(event["tags"]["model"], "vendor/model-a")
        self.assertEqual(event["tags"]["provider"], "openrouter")
        self.assertEqual(event["tags"]["learning_session_id"], "100")
        self.assertNotIn("secret-", json.dumps(event))
        self.assertEqual([call["model"] for call in fake.completions.calls], ["vendor/model-a", "vendor/model-b"])

    def test_successful_sdk_then_output_validation_uses_override_model(self):
        fake = FakeOpenAI(contents=['{"ok": true}'])
        with scope(free_talk_session_id=7), patch("app.core.openai_client.OpenAI", return_value=fake):
            request_json_completion(settings=make_settings(openrouter_api_key="test", openrouter_model="default"),
                                    system_prompt="prompt", user_prompt="text", model="vendor/review")
            event = self.report(ValueError("secret-output"))
        self.assertEqual(event["tags"]["model"], "vendor/review")
        self.assertEqual(event["tags"]["free_talk_session_id"], "7")

    def test_concurrent_tasks_and_correction_worker_isolate_mutable_model_context(self):
        async def task(session, model):
            with scope(learning_session_id=session, free_talk_session_id=None):
                bind_model("openrouter", model)
                await asyncio.sleep(0)
                return for_failure()

        async def run():
            return await asyncio.gather(task(100, "model-a"), task(200, "model-b"))
        contexts = asyncio.run(run())
        self.assertEqual([item["learning_session_id"] for item in contexts], ["100", "200"])
        self.assertEqual([item["model"] for item in contexts], ["model-a", "model-b"])
        with scope(learning_session_id=100, free_talk_session_id=7, message_id=23):
            bind_model("openrouter", "main-model")
            def correction(*_):
                bind_model("openrouter", "correction-model")
                return for_failure()
            with (ThreadPoolExecutor(max_workers=1) as executor,
                  patch("app.free_talk.application.conversation_service.generate_turn_correction", side_effect=correction)):
                context = _submitted_turn_correction(executor, None, None).result()
                self.assertEqual(context["message_id"], "23")
                self.assertEqual(context["model"], "correction-model")
                self.assertEqual(for_failure()["model"], "main-model")
                self.assertEqual(executor.submit(for_failure).result(), {})
        self.assertEqual(for_failure(), {})

    def test_identifiers_are_not_metrics_or_fingerprints_and_invalid_values_are_omitted(self):
        with scope(learning_session_id=100, free_talk_session_id=7, message_id=23,
                   model="https://secret-url?token=secret", http_route="/secret-path?secret-query"):
            with patch("app.common.failure_observation._counter") as counter:
                event = self.report()
        self.assertEqual(event["tags"]["message_id"], "23")
        for key in ("learning_session_id", "free_talk_session_id", "message_id", "model"):
            self.assertNotIn(key, counter.add.call_args.args[1])
        self.assertNotIn("100", event["fingerprint"])
        self.assertNotIn("7", event["fingerprint"])
        self.assertNotIn("23", event["fingerprint"])
        self.assertNotIn("secret", json.dumps(event))

    def test_embeddings_pronunciation_and_async_summary_keep_their_request_model(self):
        settings = make_settings(openrouter_api_key="test", openrouter_model="openai/gpt-5.4-mini")
        client = Mock()
        client.embeddings.create.return_value = SimpleNamespace(data=[])
        with scope(learning_session_id=100), patch("app.free_talk.llm.embeddings.create_openai_client", return_value=client):
            with self.assertRaises(Exception) as caught:
                request_embeddings(settings=settings, texts=["secret-text"])
        self.assertEqual(for_failure(caught.exception)["model"], "openai/text-embedding-3-small")
        self.assertEqual(for_failure(caught.exception)["learning_session_id"], "100")
        client.chat.completions.create.side_effect = RuntimeError("secret-audio")
        with scope(message_id=23), self.assertRaises(RuntimeError) as caught:
            request_structured_pronunciation_completion(
                client, settings, request={"model": "actual-pronunciation-model"},
                response_model=None, schema_name="test", workflow="pronunciation", start_format="prompt")
        self.assertEqual(for_failure(caught.exception)["model"], "actual-pronunciation-model")
        fake = _FakeAsyncCompletions(error=RuntimeError("secret-summary"))
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        async def summarize():
            with scope(free_talk_session_id=7):
                return await generate_context_summary(_payload(), settings)
        with patch("app.free_talk.application.context_summary_service.create_async_openai_client", return_value=client):
            with self.assertRaises(Exception) as caught:
                asyncio.run(summarize())
        self.assertEqual(for_failure(caught.exception)["model"], "openai/gpt-5.4-mini")
        self.assertEqual(for_failure(caught.exception)["free_talk_session_id"], "7")
        self.assertEqual(for_failure(), {})
