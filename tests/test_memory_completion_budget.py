# 기억 생성의 한도 소진과 안전한 시도별 진단을 검증한다.
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from pydantic import BaseModel

from app.free_talk.llm.json_completion import (
    AiGenerationFailedError, AiResponseInvalidError, request_json_completion,
)
from tests.test_free_talk_api import make_settings


class Candidates(BaseModel):
    candidates: list


def completion(content, finish="stop", **metadata):
    return NS(choices=[NS(message=NS(content=content), finish_reason=finish,
                          native_finish_reason="max_output_tokens" if finish == "length" else None)],
              **metadata)


class MemoryCompletionBudgetTests(unittest.TestCase):
    def invoke(self, responses):
        self.client = Mock()
        self.client.chat.completions.create.side_effect = responses
        with patch("app.core.openai_client.OpenAI", return_value=self.client):
            return request_json_completion(
                settings=make_settings(openrouter_api_key="test", openrouter_model="test"),
                system_prompt="PRIVATE_PROMPT", user_prompt="PRIVATE_USER",
                reasoning_effort="low", response_model=Candidates,
                workflow="free_talk_memory_candidates",
            )

    def test_length_exhaustion_never_retries_even_valid_or_partial_json(self):
        for content in ("", '{"candidates":[', '{"candidates":[]}'):
            with self.subTest(content=content):
                with self.assertRaises(AiResponseInvalidError) as caught:
                    self.invoke([completion(content, "length")])
                self.assertEqual(caught.exception.reason, "completion_token_limit")
                self.assertEqual(self.client.chat.completions.create.call_count, 1)

    def test_blank_is_failure_but_empty_candidates_is_success(self):
        with self.assertRaises(AiResponseInvalidError):
            self.invoke([completion(""), completion("")])
        self.assertEqual(self.client.chat.completions.create.call_count, 2)
        self.assertEqual(self.invoke([completion('{"candidates":[]}')]), {"candidates": []})

    def test_first_failure_and_usage_survive_a_later_provider_failure(self):
        response = completion("", id="gen-123-test", _request_id="req_test",
                              usage=NS(completion_tokens=4096,
                                       completion_tokens_details=NS(reasoning_tokens=4096)))
        with self.assertLogs("app.free_talk.llm", level="INFO") as logs:
            with self.assertRaises(AiGenerationFailedError):
                self.invoke([response, RuntimeError("PRIVATE_SECRET")])
        output = " ".join(logs.output)
        for value in ("completion content is blank", "provider_error", "4096", "gen-123-test",
                      "req_test", "elapsed_ms", "first_failure"):
            self.assertIn(value, output)
        for secret in ("PRIVATE_PROMPT", "PRIVATE_USER", "PRIVATE_SECRET"):
            self.assertNotIn(secret, output)

    def test_missing_diagnostics_and_untrusted_values_are_safe(self):
        with self.assertLogs("app.free_talk.llm", level="INFO") as logs:
            self.invoke([completion('{"candidates":[]}', id="PRIVATE_USER\n", usage=None)])
        self.assertNotIn("PRIVATE_USER", " ".join(logs.output))
