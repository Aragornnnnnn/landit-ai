# 프리톡 입력 예산과 요약 경계의 회귀를 검증한다.
import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from app.core.config import Settings
from app.free_talk.application.conversation_service import (
    AiContextTooLargeError,
    _ensure_context_budget,
)
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
                self.assertIs(_ensure_context_budget(request, Settings(_env_file=None)), request)

    def test_short_policy_input_keeps_summary_and_original(self):
        for request in self.requests(contextPolicyVersion="v1"):
            self.assertIs(_ensure_context_budget(request, Settings(_env_file=None)), request)
