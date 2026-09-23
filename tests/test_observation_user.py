# 인증된 사용자 ID의 Sentry 전송과 요청 및 스레드 간 격리를 검증한다.
import asyncio
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
import sentry_sdk

from app.common.failure_observation import observe, request_id, user_id
from app.core.sentry import init_sentry
from app.free_talk.application.conversation_service import _submitted_turn_correction
from app.main import create_app
from tests.test_failure_observation import MemoryTransport
from test_app import make_client, make_settings


class ObservationUserTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        actual_init = sentry_sdk.init
        with patch("app.core.sentry.sentry_sdk.init", side_effect=lambda **options: actual_init(
            **options, transport=self.transport,
        )):
            init_sentry(make_settings(sentry_dsn="https://public@example.invalid/1"))

    def tearDown(self):
        sentry_sdk.set_user(None)
        sentry_sdk.get_client().close()

    def application(self, token="secret-auth"):
        app = create_app(make_settings(landit_ai_internal_token=token))

        @app.get("/api/test-actor")
        def actor():
            observe(workflow="feedback", failure_stage="result", reason="result_missing", outcome="failed")
            return {"user_id": user_id.get()}

        @app.get("/api/test-unhandled")
        def unhandled():
            raise RuntimeError("secret-body")

        return app

    def headers(self, actor):
        return {"X-Landit-Internal-Token": "secret-auth", "X-Landit-User-Id": actor}

    def test_authenticated_user_is_retained_without_scope_email_ip_or_name(self):
        sentry_sdk.set_user({"id": "999", "email": "secret-email", "ip_address": "secret-ip",
                             "username": "secret-name"})
        client = make_client(self.application())
        response = client.get("/api/test-actor", headers=self.headers("42"))
        self.assertEqual(response.json()["user_id"], "42")
        self.assertEqual(self.transport.events[-1]["user"], {"id": "42"})
        self.assertNotIn("secret-", json.dumps(self.transport.events))
        client.get("/api/test-actor", headers=self.headers("7"))
        self.assertEqual(self.transport.events[-1]["user"], {"id": "7"})
        client.get("/api/test-actor", headers={"X-Landit-Internal-Token": "secret-auth"})
        self.assertNotIn("user", self.transport.events[-1])

    def test_auth_disabled_or_invalid_ids_are_not_trusted(self):
        client = make_client(self.application(token=""))
        self.assertEqual(client.get("/api/test-actor", headers=self.headers("42")).json()["user_id"], "")
        self.assertNotIn("user", self.transport.events[-1])
        client = make_client(self.application())
        for value in ("secret-email", "0", "-1", "01", "9223372036854775808"):
            with self.subTest(value=value):
                self.assertEqual(client.get("/api/test-actor", headers=self.headers(value)).json()["user_id"], "")
                self.assertNotIn("user", self.transport.events[-1])

    def test_rejected_auth_does_not_observe_supplied_or_inherited_user(self):
        context_token = user_id.set("7")
        try:
            with patch("app.core.internal_auth.observe") as observed:
                observed.side_effect = lambda **_: self.assertEqual(user_id.get(), "")
                response = make_client(self.application()).get(
                    "/api/test-actor", headers={"X-Landit-User-Id": "42"})
            self.assertEqual(response.status_code, 401)
            observed.assert_called_once()
            self.assertEqual(user_id.get(), "7")
            self.assertEqual(self.transport.events, [])
        finally:
            user_id.reset(context_token)

    def test_unhandled_error_keeps_actor_after_middleware_restores_context(self):
        context_token = user_id.set("7")
        request_token = request_id.set("outer-request")
        expected_request = "11111111-2222-4333-8444-555555555555"
        try:
            response = make_client(self.application(), raise_server_exceptions=False).get(
                "/api/test-unhandled", headers={**self.headers("42"), "X-Request-Id": expected_request})
            self.assertEqual(response.status_code, 500)
            self.assertEqual(len(self.transport.events), 1)
            self.assertEqual(self.transport.events[0]["user"], {"id": "42"})
            self.assertEqual(self.transport.events[0]["tags"]["request_id"], expected_request)
            self.assertEqual(user_id.get(), "7")
            self.assertNotIn("secret-", json.dumps(self.transport.events))
        finally:
            user_id.reset(context_token)
            request_id.reset(request_token)

    def test_concurrent_requests_keep_separate_actors(self):
        app = self.application()

        @app.get("/api/test-concurrent")
        async def concurrent_actor():
            before = user_id.get()
            await asyncio.sleep(0)
            return {"before": before, "after": user_id.get()}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                responses = await asyncio.gather(*[
                    client.get("/api/test-concurrent", headers=self.headers(actor)) for actor in ("42", "7")
                ])
                self.assertEqual([response.json() for response in responses], [
                    {"before": "42", "after": "42"}, {"before": "7", "after": "7"},
                ])
                self.assertEqual(user_id.get(), "")
        asyncio.run(run())

    def test_correction_thread_keeps_actor_and_leaves_no_worker_context(self):
        context_token = user_id.set("42")
        try:
            with (ThreadPoolExecutor(max_workers=1) as executor,
                  patch("app.free_talk.application.conversation_service.generate_turn_correction",
                        side_effect=lambda *_: user_id.get())):
                self.assertEqual(_submitted_turn_correction(executor, None, None).result(), "42")
                self.assertEqual(executor.submit(user_id.get).result(), "")
        finally:
            user_id.reset(context_token)

    def test_metric_dimensions_exclude_user_id(self):
        context_token = user_id.set("42")
        try:
            with patch("app.common.failure_observation._counter") as counter:
                observe(workflow="feedback", failure_stage="result", reason="result_missing", outcome="failed")
            self.assertEqual(self.transport.events[-1]["user"], {"id": "42"})
            self.assertNotIn("user_id", counter.add.call_args.args[1])
            self.assertNotIn("user.id", counter.add.call_args.args[1])
            self.assertNotIn("42", self.transport.events[-1]["fingerprint"])
        finally:
            user_id.reset(context_token)
