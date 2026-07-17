# AI 서버 초기 앱 동작을 검증하는 unittest 모듈
import os
import unittest
import warnings
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import BaseModel

from app.api.health import health_check
from app.common.errors import ApiException, ErrorCode
from app.common.response import error_response, success_response
from app.core.config import Settings
from app.core.openai_client import create_openai_client
from app.core.sentry import init_sentry
from app.main import create_app


def make_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def make_client(app, **kwargs):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated.*",
        )
        from fastapi.testclient import TestClient

        return TestClient(app, **kwargs)


class SettingsTests(unittest.TestCase):
    def test_default_settings_use_local_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = make_settings()

        self.assertEqual(settings.app_name, "landit-ai")
        self.assertEqual(settings.app_env, "local")
        self.assertEqual(settings.llm_provider, "openrouter")
        self.assertEqual(settings.openrouter_base_url, "https://openrouter.ai/api/v1")
        self.assertIsNone(settings.openrouter_api_key)
        self.assertIsNone(settings.openrouter_model)
        self.assertIsNone(settings.message_feedback_model)
        self.assertIsNone(settings.openrouter_review_model)
        self.assertTrue(settings.message_feedback_review_enabled)
        self.assertIsNone(settings.sentry_dsn)

    def test_settings_read_openrouter_environment_variables(self):
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-openrouter-key",
                "OPENROUTER_BASE_URL": "https://openrouter.example/v1",
                "OPENROUTER_MODEL": "openrouter-test-model",
                "MESSAGE_FEEDBACK_MODEL": "message-feedback-model",
                "OPENROUTER_REVIEW_MODEL": "openrouter-review-model",
                "MESSAGE_FEEDBACK_REVIEW_ENABLED": "false",
            },
            clear=True,
        ):
            settings = make_settings()

        self.assertEqual(settings.llm_provider, "openrouter")
        self.assertIsNotNone(settings.openrouter_api_key)
        self.assertEqual(
            settings.openrouter_api_key.get_secret_value(),
            "test-openrouter-key",
        )
        self.assertEqual(settings.openrouter_base_url, "https://openrouter.example/v1")
        self.assertEqual(settings.openrouter_model, "openrouter-test-model")
        self.assertEqual(
            settings.message_feedback_model,
            "message-feedback-model",
        )
        self.assertEqual(
            settings.openrouter_review_model,
            "openrouter-review-model",
        )
        self.assertFalse(settings.message_feedback_review_enabled)


class AppFactoryTests(unittest.TestCase):
    def test_create_app_registers_health_endpoint(self):
        app = create_app(make_settings())

        paths = app.openapi()["paths"]

        self.assertIn("/health", paths)

    def test_health_check_returns_ok_status(self):
        self.assertEqual(health_check(), {"status": "ok"})

    def test_health_endpoint_keeps_plain_response(self):
        app = create_app(make_settings())
        response = make_client(app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class CommonResponseTests(unittest.TestCase):
    def test_success_response_wraps_data(self):
        response = success_response({"message": "ok"})

        self.assertEqual(
            response.model_dump(mode="json"),
            {
                "success": True,
                "data": {"message": "ok"},
                "error": None,
            },
        )

    def test_error_response_wraps_code_and_message(self):
        response = error_response(ErrorCode.INVALID_REQUEST, "요청이 올바르지 않습니다.")

        self.assertEqual(
            response.model_dump(mode="json"),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "요청이 올바르지 않습니다.",
                },
            },
        )

    def test_invalid_request_default_message_matches_api_spec(self):
        self.assertEqual(ErrorCode.INVALID_REQUEST.default_message, "잘못된 요청입니다.")


class ExceptionHandlerTests(unittest.TestCase):
    def test_validation_error_returns_invalid_request_response(self):
        class TestPayload(BaseModel):
            count: int

        app = create_app(make_settings())

        @app.post("/test/validation")
        def validate_payload(payload: TestPayload):
            return success_response({"count": payload.count})

        response = make_client(app).post("/test/validation", json={"count": "bad"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": ErrorCode.INVALID_REQUEST.default_message,
                },
            },
        )

    def test_api_exception_uses_status_code_and_error_code(self):
        app = create_app(make_settings())

        @app.get("/test/api-exception")
        def raise_api_exception():
            raise ApiException(
                status_code=503,
                error_code=ErrorCode.AI_GENERATION_FAILED,
                message="AI 생성에 실패했습니다.",
            )

        with self.assertLogs("uvicorn.error", level="ERROR") as captured_logs:
            response = make_client(app, raise_server_exceptions=False).get(
                "/test/api-exception",
            )

        output = "\n".join(captured_logs.output)
        self.assertEqual(response.status_code, 503)
        self.assertIn("Handled server error.", output)
        self.assertIn("Traceback", output)
        self.assertIn("ApiException: AI 생성에 실패했습니다.", output)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "AI_GENERATION_FAILED",
                    "message": "AI 생성에 실패했습니다.",
                },
            },
        )

    def test_http_exception_uses_common_error_response(self):
        app = create_app(make_settings())

        @app.get("/test/http-exception")
        def raise_http_exception():
            raise HTTPException(status_code=404, detail="missing")

        response = make_client(app, raise_server_exceptions=False).get(
            "/test/http-exception",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "missing",
                },
            },
        )

    def test_server_http_exception_logs_stack_trace(self):
        app = create_app(make_settings())

        @app.get("/test/http-server-error-log")
        def raise_http_server_error():
            raise HTTPException(status_code=503, detail="upstream unavailable")

        with self.assertLogs("uvicorn.error", level="ERROR") as captured_logs:
            response = make_client(app, raise_server_exceptions=False).get(
                "/test/http-server-error-log",
            )

        output = "\n".join(captured_logs.output)
        self.assertEqual(response.status_code, 503)
        self.assertIn("Handled server error.", output)
        self.assertIn("Traceback", output)
        self.assertIn("HTTPException", output)
        self.assertIn("upstream unavailable", output)

    def test_unexpected_exception_returns_internal_server_error_response(self):
        app = create_app(make_settings())

        @app.get("/test/unexpected")
        def raise_unexpected_exception():
            raise RuntimeError("unexpected failure")

        with self.assertLogs("uvicorn.error", level="ERROR"):
            response = make_client(app, raise_server_exceptions=False).get(
                "/test/unexpected",
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": ErrorCode.INTERNAL_SERVER_ERROR.default_message,
                },
            },
        )

    def test_unexpected_exception_logs_stack_trace_without_request_values(self):
        class TestPayload(BaseModel):
            content: str

        app = create_app(make_settings())

        @app.post("/test/unexpected-log")
        def raise_unexpected_exception(payload: TestPayload):
            raise RuntimeError("unexpected failure")

        with self.assertLogs("uvicorn.error", level="ERROR") as captured_logs:
            response = make_client(app, raise_server_exceptions=False).post(
                "/test/unexpected-log?token=secret-query",
                headers={"Authorization": "secret-header"},
                json={"content": "secret-body"},
            )

        output = "\n".join(captured_logs.output)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Unexpected server error.", output)
        self.assertIn("Traceback", output)
        self.assertIn("RuntimeError: unexpected failure", output)
        self.assertNotIn("secret-query", output)
        self.assertNotIn("secret-header", output)
        self.assertNotIn("secret-body", output)
        self.assertNotIn("Authorization", output)

    def test_expected_client_errors_do_not_log_at_error_level(self):
        class TestPayload(BaseModel):
            count: int

        app = create_app(make_settings())

        @app.post("/test/validation-log")
        def validate_payload(payload: TestPayload):
            return success_response({"count": payload.count})

        @app.get("/test/api-client-error-log")
        def raise_api_client_error():
            raise ApiException(
                status_code=409,
                error_code=ErrorCode.MESSAGE_FEEDBACK_NOT_READY,
            )

        with self.assertNoLogs("uvicorn.error", level="ERROR"):
            validation_response = make_client(app).post(
                "/test/validation-log",
                json={"count": "bad"},
            )
            not_found_response = make_client(app).get("/test/not-found")
            api_error_response = make_client(
                app,
                raise_server_exceptions=False,
            ).get("/test/api-client-error-log")

        self.assertEqual(validation_response.status_code, 400)
        self.assertEqual(not_found_response.status_code, 404)
        self.assertEqual(api_error_response.status_code, 409)


class SentryInitializationTests(unittest.TestCase):
    def test_sentry_logging_integration_does_not_create_error_events(self):
        logging_integration = object()

        with (
            patch(
                "app.core.sentry.LoggingIntegration",
                return_value=logging_integration,
            ) as integration_factory,
            patch("app.core.sentry.sentry_sdk.init") as sentry_init,
        ):
            init_sentry(
                make_settings(
                    sentry_dsn="https://public@example.invalid/1",
                ),
            )

        integration_factory.assert_called_once_with(event_level=None)
        sentry_init.assert_called_once_with(
            dsn="https://public@example.invalid/1",
            environment="local",
            traces_sample_rate=0.0,
            integrations=[logging_integration],
        )


class OpenAIClientTests(unittest.TestCase):
    def test_create_openai_client_requires_openrouter_api_key(self):
        settings = make_settings(openrouter_api_key=None)

        with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
            create_openai_client(settings)

    def test_create_openai_client_rejects_blank_openrouter_api_key(self):
        settings = make_settings(openrouter_api_key="")

        with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
            create_openai_client(settings)

    def test_create_openai_client_requires_openrouter_provider(self):
        settings = make_settings(
            llm_provider="other",
            openrouter_api_key="test-openrouter-key",
        )

        with self.assertRaisesRegex(RuntimeError, "LLM_PROVIDER"):
            create_openai_client(settings)

    def test_create_openai_client_uses_openrouter_base_url(self):
        settings = make_settings(
            openrouter_api_key="test-openrouter-key",
            openrouter_base_url="https://openrouter.example/v1",
        )

        client = create_openai_client(settings)

        self.assertEqual(str(client.base_url), "https://openrouter.example/v1/")
