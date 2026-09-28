# 비교 카드와 여러 재사용 표현을 포함한 총평 출력의 잘림 방지를 검증한다.
import json
import unittest

import tiktoken

from app.conversation.llm.session_feedback_budget import session_feedback_output_budget
from app.models.conversation import SessionFeedbackRequest, SessionFeedbackSummary
from tests.test_conversation_api import valid_session_feedback_payload


class SessionFeedbackBudgetTests(unittest.TestCase):
    def request(self, count=0, previous=False):
        payload = valid_session_feedback_payload()
        payload["learnedExpressions"] = [
            {"expressionId": i + 1, "text": "take a break", "meaning": "잠깐 쉬다"}
            for i in range(count)
        ]
        if previous:
            payload["previousMistakes"] = [{
                "messageId": 90, "userMessage": "I go yesterday.",
                "correctionExpression": "I went yesterday.", "correctionReason": "과거형",
            }]
        return SessionFeedbackRequest.model_validate(payload)

    def test_legacy_summary_keeps_existing_budget(self):
        self.assertEqual(session_feedback_output_budget(self.request(), ["Hello."]), 512)

    def test_valid_growth_and_fifty_matches_fit_expanded_budget(self):
        sentence = "Yesterday I decided to take a break with my friends."
        result = SessionFeedbackSummary.model_validate({
            "sessionId": 100, "highlightMessage": "배운 표현을 활용했어요.",
            "summaryMessage": "이번에는 과거형을 정확히 썼어요. 이유도 덧붙여 보세요.",
            "growthFeedback": {
                "pattern": "TENSE", "previousMessageId": 90,
                "previousSentence": "I go yesterday.", "previousWrongSpan": "go",
                "currentMessageId": 1001, "currentSentence": sentence,
                "currentSpan": "decided", "succeeded": True,
            },
            "usedExpressions": [{"expressionId": i + 1, "messageId": 1001,
                                 "matchedText": "take a break"} for i in range(50)],
        })
        encoded = tiktoken.get_encoding("o200k_base").encode(
            json.dumps(result.model_dump(), ensure_ascii=False), disallowed_special=(),
        )
        self.assertGreater(len(encoded), 512)
        budget = session_feedback_output_budget(self.request(50, previous=True), [sentence])
        self.assertGreater(budget, len(encoded))

    def test_large_quotes_have_a_bounded_budget(self):
        budget = session_feedback_output_budget(self.request(50, previous=True), ["word " * 10000])
        self.assertEqual(budget, 16384)
