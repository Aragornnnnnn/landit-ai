# Structured Outputs 스키마 생성과 재시도 및 fallback 정책을 검증하는 unittest 모듈
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict

from app.conversation.application import next_message_service
from app.core.config import Settings
from app.core.structured_output import json_schema_response_format
from app.free_talk.llm.json_completion import (
    AiGenerationFailedError,
    request_json_completion,
)
from app.pronunciation.llm.structured_completion import (
    request_structured_pronunciation_completion,
)


class _NestedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class _ExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    nested: _NestedOutput
    note: str | None = None


class _ProviderUnsupportedError(Exception):
    status_code = 404


class _FakeCompletions:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=result))],
        )


class _FakeOpenAI:
    def __init__(self, results):
        self.completions = _FakeCompletions(results)
        self.chat = SimpleNamespace(completions=self.completions)


class StructuredOutputTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            _env_file=None,
            openrouter_api_key="test-key",
            openrouter_model="test-model",
        )

    def test_schema_is_strict_for_root_and_nested_objects(self):
        response_format = json_schema_response_format(
            _ExampleOutput,
            name="example_output",
        )

        schema = response_format["json_schema"]["schema"]
        nested = schema["$defs"]["_NestedOutput"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["name", "nested", "note"])
        self.assertFalse(nested["additionalProperties"])
        self.assertEqual(nested["required"], ["enabled"])

    def test_malformed_json_is_retried_once(self):
        expected = {
            "name": "ok",
            "nested": {"enabled": True},
            "note": None,
        }
        fake = _FakeOpenAI(["not json", json.dumps(expected)])

        with patch("app.free_talk.llm.json_completion.create_openai_client", return_value=fake):
            result = request_json_completion(
                settings=self.settings,
                system_prompt="system",
                user_prompt="user",
                response_model=_ExampleOutput,
                schema_name="example_output",
                workflow="test_workflow",
            )

        self.assertEqual(result, expected)
        self.assertEqual(len(fake.completions.calls), 2)

    def test_reasoning_options_survive_schema_fallback(self):
        fake = _FakeOpenAI([
            _ProviderUnsupportedError("response_format json_schema unsupported"),
            json.dumps({"name": "legacy"}),
        ])
        with patch("app.free_talk.llm.json_completion.create_openai_client", return_value=fake):
            request_json_completion(
                settings=self.settings,
                system_prompt="system",
                user_prompt="user",
                reasoning_effort="medium",
                response_model=_ExampleOutput,
            )
        self.assertEqual(len(fake.completions.calls), 2)
        for call in fake.completions.calls:
            self.assertEqual(call["max_completion_tokens"], 4096)
            self.assertEqual(
                call["extra_body"],
                {"reasoning": {"effort": "medium", "exclude": True}},
            )
        self.assertEqual(fake.completions.calls[0]["response_format"]["type"], "json_schema")
        self.assertEqual(fake.completions.calls[1]["response_format"]["type"], "json_object")

    def test_unsupported_provider_falls_back_to_json_object(self):
        fake = _FakeOpenAI([
            _ProviderUnsupportedError(
                "No endpoints found that can handle the requested parameters"
            ),
            json.dumps({"name": "legacy"}),
        ])

        with patch("app.free_talk.llm.json_completion.create_openai_client", return_value=fake):
            result = request_json_completion(
                settings=self.settings,
                system_prompt="system",
                user_prompt="user",
                response_model=_ExampleOutput,
                schema_name="example_output",
                workflow="test_workflow",
            )

        self.assertEqual(result, {"name": "legacy"})
        self.assertEqual(
            fake.completions.calls[1]["response_format"],
            {"type": "json_object"},
        )

    def test_json_object_unsupported_falls_back_to_prompt_json(self):
        fake = _FakeOpenAI([
            _ProviderUnsupportedError("response_format json_schema unsupported"),
            _ProviderUnsupportedError("response_format json_object unsupported"),
            json.dumps({"name": "legacy"}),
        ])

        with patch("app.free_talk.llm.json_completion.create_openai_client", return_value=fake):
            result = request_json_completion(
                settings=self.settings,
                system_prompt="system",
                user_prompt="user",
                response_model=_ExampleOutput,
                schema_name="example_output",
                workflow="test_workflow",
            )

        self.assertEqual(result, {"name": "legacy"})
        self.assertNotIn("response_format", fake.completions.calls[2])

    def test_scenario_unsupported_provider_uses_json_object_before_prompt(self):
        fake = _FakeOpenAI([
            _ProviderUnsupportedError("response_format json_schema unsupported"),
            json.dumps({"name": "legacy"}),
        ])

        with patch.object(next_message_service, "create_openai_client", return_value=fake):
            result = next_message_service._request_json_completion(
                self.settings,
                system_prompt="system",
                user_prompt="user",
                max_tokens=10,
                response_model=_ExampleOutput,
                schema_name="scenario_example",
                workflow="scenario_example",
            )

        self.assertEqual(result, {"name": "legacy"})
        self.assertEqual(
            fake.completions.calls[1]["response_format"],
            {"type": "json_object"},
        )

    def test_pronunciation_fallback_reuses_json_object_format(self):
        fake = _FakeOpenAI([
            _ProviderUnsupportedError("response_format json_schema unsupported"),
            json.dumps({"name": "legacy"}),
        ])

        result = request_structured_pronunciation_completion(
            fake,
            self.settings,
            request={"model": "test-model", "messages": []},
            response_model=_ExampleOutput,
            schema_name="pronunciation_example",
            workflow="pronunciation_example",
            deadline=time.monotonic() + 1,
        )

        self.assertEqual(result.output_format, "json_object")
        self.assertEqual(
            fake.completions.calls[1]["response_format"],
            {"type": "json_object"},
        )

    def test_pronunciation_falls_back_to_prompt_when_json_object_is_unsupported(self):
        fake = _FakeOpenAI([
            _ProviderUnsupportedError("response_format json_schema unsupported"),
            _ProviderUnsupportedError("response_format json_object unsupported"),
            json.dumps({"name": "legacy"}),
        ])

        result = request_structured_pronunciation_completion(
            fake,
            self.settings,
            request={"model": "test-model", "messages": []},
            response_model=_ExampleOutput,
            schema_name="pronunciation_example",
            workflow="pronunciation_example",
            deadline=time.monotonic() + 1,
        )

        self.assertEqual(result.output_format, "prompt")
        self.assertNotIn("response_format", fake.completions.calls[2])

    def test_schema_violation_is_retried_once(self):
        expected = {
            "name": "ok",
            "nested": {"enabled": True},
            "note": None,
        }
        fake = _FakeOpenAI([
            json.dumps({"name": "missing fields"}),
            json.dumps(expected),
        ])

        with patch("app.free_talk.llm.json_completion.create_openai_client", return_value=fake):
            with self.assertLogs(
                "app.free_talk.llm.json_completion",
                level="WARNING",
            ) as logs:
                result = request_json_completion(
                    settings=self.settings,
                    system_prompt="system",
                    user_prompt="user",
                    response_model=_ExampleOutput,
                    schema_name="example_output",
                    workflow="test_workflow",
                )

        self.assertEqual(result, expected)
        self.assertEqual(len(fake.completions.calls), 2)
        self.assertTrue(
            any("event=schema_validation_failure" in entry for entry in logs.output)
        )

    def test_timeout_does_not_trigger_format_fallback(self):
        fake = _FakeOpenAI([TimeoutError("timed out")])

        with patch("app.free_talk.llm.json_completion.create_openai_client", return_value=fake):
            with self.assertRaises(AiGenerationFailedError):
                request_json_completion(
                    settings=self.settings,
                    system_prompt="system",
                    user_prompt="user",
                    response_model=_ExampleOutput,
                    schema_name="example_output",
                    workflow="test_workflow",
                )

        self.assertEqual(len(fake.completions.calls), 1)


if __name__ == "__main__":
    unittest.main()
