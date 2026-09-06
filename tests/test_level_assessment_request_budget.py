# 수준 평가의 시간 예산과 출력 모드 오류 분류를 검증한다.
import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.conversation.application.next_message_service import (
    AiGenerationFailedError,
    _is_response_format_unsupported,
    _request_json_completion,
    _request_json_completion_with_format_fallback,
)
from tests.test_conversation_api import FakeOpenAI


class LevelAssessmentRequestBudgetTests(unittest.TestCase):
    def test_schema_errors_do_not_trigger_mode_switch(self):
        for message in (
            "Invalid schema for response_format: keyword 'oneOf' is not supported",
            "json_schema keyword not supported",
            "Unsupported model",
        ):
            cause = RuntimeError(message)
            cause.status_code = 400
            error = AiGenerationFailedError()
            error.__cause__ = cause
            self.assertFalse(_is_response_format_unsupported(error), message)

    def test_deadline_prevents_another_provider_request(self):
        with patch("app.conversation.application.next_message_service.time.monotonic", return_value=101), patch(
            "app.conversation.application.next_message_service.create_openai_client"
        ) as factory:
            with self.assertRaises(AiGenerationFailedError):
                _request_json_completion(
                    Settings(openrouter_model="test"), "system", "user", 100, deadline=100,
                )
            factory.assert_not_called()

    def test_modes_share_budget_and_disable_sdk_retries(self):
        unsupported = RuntimeError("response_format json_schema is not supported")
        unsupported.status_code = 400
        fake = FakeOpenAI(contents=['{}'], errors=[unsupported])
        with patch("app.core.openai_client.OpenAI", return_value=fake) as factory, patch(
            "app.conversation.application.next_message_service.time.monotonic",
            side_effect=[10, 20, 25],
        ):
            data, mode = _request_json_completion_with_format_fallback(
                Settings(openrouter_model="test", openrouter_api_key="test"),
                system_prompt="system", user_prompt="JSON", max_tokens=100,
                response_format={"type": "json_schema"}, deadline=100,
            )
        self.assertEqual(data, {})
        self.assertEqual(mode, {"type": "json_object"})
        self.assertEqual([call.kwargs["timeout"] for call in factory.call_args_list], [90, 80])
        self.assertTrue(all(call.kwargs["max_retries"] == 0 for call in factory.call_args_list))

    def test_response_after_deadline_is_rejected(self):
        with patch("app.core.openai_client.OpenAI", return_value=FakeOpenAI(content='{}')), patch(
            "app.conversation.application.next_message_service.time.monotonic", side_effect=[90, 101],
        ):
            with self.assertRaises(AiGenerationFailedError):
                _request_json_completion(
                    Settings(openrouter_model="test", openrouter_api_key="test"),
                    "system", "user", 100, deadline=100,
                )
