# 프리톡 입력 예산과 요약 경계의 회귀를 검증한다.
import json
import unittest

import tiktoken
from datetime import UTC, datetime

from pydantic import ValidationError

from app.core.config import Settings
from app.free_talk.application.conversation_service import (
    _ensure_context_budget,
)
from app.free_talk.llm.context_budget import estimate_request_tokens
from app.free_talk.llm.json_completion import AiGenerationFailedError
from app.models.free_talk import (
    FreeTalkClosingRequest,
    FreeTalkInnerThoughtRequest,
    FreeTalkTurnRequest,
)
from test_free_talk_api import (
    valid_closing_payload,
    valid_inner_thought_payload,
    valid_turn_payload,
)


class ContextBudgetTests(unittest.TestCase):
    def requests(self, **overrides):
        for model, factory in (
            (FreeTalkTurnRequest, valid_turn_payload),
            (FreeTalkInnerThoughtRequest, valid_inner_thought_payload),
            (FreeTalkClosingRequest, valid_closing_payload),
        ):
            data = factory(**overrides)
            data["submittedMessageId"] = data["conversationHistory"][-1]["messageId"]
            data["submittedTurnNumber"] = data["conversationHistory"][-1]["turnNumber"]
            yield model.model_validate(data)

    def history(self):
        return [
            {"messageId": i, "turnNumber": (i + 1) // 2,
             "role": "USER" if i % 2 else "AI",
             "content": "old content " * 500 if i < 19 else "Keep this original.",
             "translatedContent": None}
            for i in range(1, 22)
        ]

    def test_disabled_policy_preserves_large_legacy_input(self):
        for request in self.requests(conversationHistory=self.history()):
            with self.subTest(model=type(request).__name__):
                self.assertIs(_ensure_context_budget(request, Settings(_env_file=None, openrouter_model="openai/gpt-5.4-mini")), request)

    def test_overflow_drops_old_complete_units_and_stale_summary(self):
        summary = {"revision": 1, "coveredThroughSequence": 3, "content": {
            "topic": "Old topic", "userStatements": [], "openThreads": [],
            "interactionContext": []}}
        for request in self.requests(conversationHistory=self.history(),
                                     contextPolicyVersion="v1", sessionSummary=summary):
            with self.subTest(model=type(request).__name__):
                result = _ensure_context_budget(request, Settings(_env_file=None, openrouter_model="openai/gpt-5.4-mini"))
                self.assertLess(len(result.conversationHistory), len(request.conversationHistory))
                self.assertEqual(result.conversationHistory[-2:], request.conversationHistory[-2:])
                self.assertEqual(result.conversationHistory[0].role, "USER")
                self.assertTrue(result.historyIncomplete)
                self.assertIsNone(result.sessionSummary)
                self.assertIsNotNone(request.sessionSummary)
                self.assertEqual(len(request.conversationHistory), 21)

    def test_oversized_latest_pair_is_preserved_without_truncating_text(self):
        history = self.history()[-2:]
        history[0]["content"] = "🙂 " * 12000
        for request in self.requests(conversationHistory=self.history()[:-2] + history,
                                     contextPolicyVersion="v1"):
            with self.subTest(model=type(request).__name__):
                result = _ensure_context_budget(request, Settings(
                    _env_file=None, openrouter_model="openai/gpt-5.4-mini",
                ))
                self.assertEqual(result.conversationHistory, request.conversationHistory[-2:])
                self.assertTrue(result.historyIncomplete)
                self.assertEqual(len(request.conversationHistory), 21)

    def test_budget_includes_system_and_response_schema(self):
        payload = valid_turn_payload(contextPolicyVersion="v1")
        payload["conversationHistory"][0]["content"] = "word " * 7500
        request = FreeTalkTurnRequest.model_validate(payload)
        result = _ensure_context_budget(request, Settings(
            _env_file=None, openrouter_model="openai/gpt-5.4-mini",
        ), datetime.now(UTC))
        self.assertTrue(result.historyIncomplete)
        self.assertEqual(result.conversationHistory, request.conversationHistory)

    def test_short_policy_input_keeps_summary_and_original(self):
        for request in self.requests(contextPolicyVersion="v1"):
            self.assertIs(_ensure_context_budget(request, Settings(_env_file=None, openrouter_model="openai/gpt-5.4-mini")), request)

    def test_inconsistent_summary_contract_is_rejected(self):
        summary = {"revision": 1, "coveredThroughSequence": 3, "content": {
            "topic": "Old topic", "userStatements": [], "openThreads": [],
            "interactionContext": []}}
        for factory, model in ((valid_turn_payload, FreeTalkTurnRequest),
                               (valid_closing_payload, FreeTalkClosingRequest),
                               (valid_inner_thought_payload, FreeTalkInnerThoughtRequest)):
            for fields in ({"sessionSummary": summary},
                           {"sessionSummary": summary, "contextPolicyVersion": "v1",
                            "historyIncomplete": True}):
                with self.subTest(model=model.__name__, fields=tuple(fields)), self.assertRaises(ValidationError):
                    model.model_validate(factory(**fields))

class ContextTokenizerTests(unittest.TestCase):
    def test_counts_korean_json_with_the_supported_model_tokenizer(self):
        user = "면접이 취소됐어요. Thursday에는 첼로를 연습해요. " * 600
        schema = {"type": "json_schema", "description": "한국어 출력 계약" * 100}
        serialized = json.dumps({"messages": [
            {"role": "system", "content": "요약하세요."},
            {"role": "user", "content": user},
        ], "response_format": schema}, ensure_ascii=False)
        expected = len(tiktoken.get_encoding("o200k_base").encode_ordinary(serialized)) + 512
        self.assertGreater(expected, (len(serialized.encode("utf-8")) + 3) // 4 + 512)
        for model in ("openai/gpt-5.4-mini", "openai/gpt-5.4-mini-20260317"):
            self.assertEqual(estimate_request_tokens("요약하세요.", user, schema, model), expected)

    def test_unknown_model_rejects_policy_instead_of_guessing_encoding(self):
        request = FreeTalkTurnRequest.model_validate(valid_turn_payload(contextPolicyVersion="v1"))
        with self.assertRaises(AiGenerationFailedError):
            _ensure_context_budget(request, Settings(_env_file=None, openrouter_model="unknown"))

    def test_special_token_text_is_counted_as_user_text(self):
        self.assertGreater(estimate_request_tokens("", "<|endoftext|>", {},
                                                 "openai/gpt-5.4-mini"), 512)

    def test_unknown_model_does_not_change_legacy_requests(self):
        request = FreeTalkTurnRequest.model_validate(valid_turn_payload())
        self.assertIs(_ensure_context_budget(request, Settings(
            _env_file=None, openrouter_model="unknown")), request)
