# 프리톡 컨텍스트 요약 API의 계약과 deadline을 검증하는 unittest 모듈
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.core.config import Settings
from app.free_talk.application.context_summary_service import (
    SummaryInputTooLargeError,
    generate_context_summary,
)
from app.free_talk.llm.json_completion import (
    AiGenerationFailedError,
    AiResponseInvalidError,
)
from app.models.free_talk import ContextSummaryRequest


def _payload(**overrides):
    value = {
        "sessionId": 7,
        "policyVersion": "v1",
        "baseRevision": 0,
        "previousSummary": None,
        "coveredThroughSequence": 0,
        "targetThroughSequence": 2,
        "timezone": "Asia/Seoul",
        "sourceMessages": [
            {
                "sequence": 1,
                "messageId": 11,
                "turnNumber": 1,
                "role": "USER",
                "content": "I practice the cello every Thursday.",
                "occurredAt": "2026-09-20T10:00:00+09:00",
            },
            {
                "sequence": 2,
                "messageId": 12,
                "turnNumber": 1,
                "role": "AI",
                "content": "That sounds like a meaningful routine.",
                "occurredAt": "2026-09-20T10:00:02+09:00",
            },
        ],
    }
    value.update(overrides)
    return ContextSummaryRequest.model_validate(value)


class _FakeAsyncCompletions:
    def __init__(self, content=None, error=None, delay=0):
        self.content = content
        self.error = error
        self.delay = delay
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
        )


class ContextSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_preserves_user_source_references(self):
        fake = _FakeAsyncCompletions(
            '{"topic":"Weekly cello practice","userStatements":'
            '[{"text":"The user practices cello every Thursday.","sourceMessageIds":[11]}],'
            '"openThreads":[],"interactionContext":[]}',
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        with patch(
            "app.free_talk.application.context_summary_service.create_async_openai_client",
            return_value=client,
        ):
            result = await generate_context_summary(
                _payload(),
                Settings(
                    _env_file=None,
                    openrouter_api_key="test",
                    openrouter_model="test-model",
                ),
            )

        self.assertEqual(result.coveredThroughSequence, 2)
        self.assertEqual(result.summary.userStatements[0].sourceMessageIds, [11])
        self.assertEqual(fake.calls[0]["max_completion_tokens"], 800)

    async def test_summary_rejects_non_user_source_for_user_statement(self):
        fake = _FakeAsyncCompletions(
            '{"topic":"Topic","userStatements":'
            '[{"text":"Claim","sourceMessageIds":[12]}],'
            '"openThreads":[],"interactionContext":[]}',
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        with patch(
            "app.free_talk.application.context_summary_service.create_async_openai_client",
            return_value=client,
        ), self.assertRaises(AiResponseInvalidError):
            await generate_context_summary(
                _payload(),
                Settings(
                    _env_file=None,
                    openrouter_api_key="test",
                    openrouter_model="test-model",
                ),
            )

    async def test_summary_input_timeout_does_not_retry(self):
        fake = _FakeAsyncCompletions(delay=0.05)
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        with patch(
            "app.free_talk.application.context_summary_service.create_async_openai_client",
            return_value=client,
        ), self.assertRaises(AiGenerationFailedError):
            await generate_context_summary(
                _payload(),
                Settings(
                    _env_file=None,
                    openrouter_api_key="test",
                    openrouter_model="test-model",
                    free_talk_summary_timeout_seconds=0.001,
                ),
            )
        self.assertEqual(len(fake.calls), 1)

    async def test_summary_input_budget_rejects_before_provider_call(self):
        fake = _FakeAsyncCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        with patch(
            "app.free_talk.application.context_summary_service.create_async_openai_client",
            return_value=client,
        ), self.assertRaises(SummaryInputTooLargeError):
            await generate_context_summary(
                _payload(sourceMessages=[
                    {
                        "sequence": 1,
                        "messageId": 11,
                        "turnNumber": 1,
                        "role": "USER",
                        "content": "x" * 1000,
                        "occurredAt": "2026-09-20T10:00:00+09:00",
                    },
                ], targetThroughSequence=1),
                Settings(
                    _env_file=None,
                    openrouter_api_key="test",
                    openrouter_model="test-model",
                    free_talk_context_input_budget_tokens=10,
                ),
            )
        self.assertEqual(len(fake.calls), 0)

class ContextSummaryBoundaryTests(unittest.TestCase):
    def test_rejects_non_finite_or_non_positive_deadline(self):
        for timeout in (float("inf"), float("-inf"), float("nan"), 0, -1):
            with self.subTest(timeout=timeout), self.assertRaises(ValidationError):
                Settings(_env_file=None, free_talk_summary_timeout_seconds=timeout)
