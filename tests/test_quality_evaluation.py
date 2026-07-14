# LAN-138 실제 모델 평가 도구의 결과 요약을 검증하는 unittest 모듈
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import Settings
from app.conversation.application.next_message_service import AiResponseInvalidError
from app.models.conversation import (
    FeedbackStatus,
    MessageFeedbackData,
    MessageFeedbackResponse,
)
from scripts.evaluate_conversation_quality import evaluate_cases, main


def closing_case():
    return {
        "caseId": "closing-meta-wrap-up",
        "kind": "closing",
        "expectedContextTerms": ["quiet", "조용"],
        "payload": {
            "sessionId": 100,
            "submittedMessageId": 1007,
            "submittedTurnNumber": 4,
            "scenario": {
                "scenarioId": 10,
                "title": "기숙사에서 조용히 해달라고 말하기",
                "briefing": "룸메이트에게 밤에 조용히 해달라고 말하는 상황입니다.",
                "conversationGoal": "불편함을 공격적이지 않게 전달합니다.",
                "counterpartRole": "roommate",
            },
            "conversationHistory": [
                {
                    "messageId": 1006,
                    "turnNumber": 4,
                    "role": "AI",
                    "content": "What do you want me to do?",
                },
                {
                    "messageId": 1007,
                    "turnNumber": 4,
                    "role": "USER",
                    "content": "Could you keep it down at night?",
                },
            ],
            "closingReason": "GOAL_COMPLETED",
            "goalCompletionStatus": "COMPLETED",
        },
    }


def feedback_case():
    return {
        "caseId": "feedback-natural-colloquial",
        "kind": "message-feedback",
        "expectedFeedbackType": "GOOD",
        "payload": {
            "sessionId": 200,
            "messageId": 2001,
            "turnNumber": 1,
            "messageSequence": 2,
            "scenario": {
                "scenarioId": 20,
                "title": "친구와 약속 잡기",
                "briefing": "친구와 주말 약속을 잡는 상황입니다.",
                "conversationGoal": "제안에 자연스럽게 답합니다.",
                "counterpartRole": "friend",
            },
            "evaluationContext": {
                "type": "AI_MESSAGE",
                "content": "Do you want to watch a movie this weekend?",
            },
            "userMessage": "Yeah, sounds good to me.",
        },
    }


class QualityEvaluationTests(unittest.TestCase):
    def test_main_records_reproducible_execution_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            cases_path = Path(directory) / "cases.json"
            output_path = Path(directory) / "results.json"
            cases_path.write_text("[]", encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "evaluate_conversation_quality.py",
                        "--cases",
                        str(cases_path),
                        "--runs",
                        "2",
                        "--kind",
                        "closing",
                        "--output",
                        str(output_path),
                    ],
                ),
                patch(
                    "scripts.evaluate_conversation_quality.Settings",
                    return_value=SimpleNamespace(openrouter_model="openai/test-model"),
                ),
                patch(
                    "scripts.evaluate_conversation_quality.evaluate_cases",
                    return_value=[],
                ),
            ):
                main()

            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["model"], "openai/test-model")
        self.assertEqual(report["casesFile"], str(cases_path))
        self.assertEqual(report["casesSha256"], hashlib.sha256(b"[]").hexdigest())
        self.assertEqual(report["runs"], 2)
        self.assertEqual(report["kind"], "closing")
        self.assertEqual(report["results"], [])
        datetime.fromisoformat(report["evaluatedAt"])

    def test_closing_result_detects_meta_wrap_up_through_real_generation_path(self):
        with patch(
            "app.conversation.application.next_message_service._request_json_completion",
            return_value={
                "aiMessage": "I understand. Let’s wrap up here.",
                "translatedMessage": "알겠어. 여기서 마무리하자.",
                "innerThought": "부탁한 내용은 이해했다.",
                "innerThoughtType": "NORMAL",
            },
        ):
            try:
                results = evaluate_cases(
                    [closing_case()],
                    runs=1,
                    kind="closing",
                    settings=Settings(_env_file=None),
                )
            except AiResponseInvalidError:
                self.fail("quality evaluation must inspect candidates before policy rejection")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["caseId"], "closing-meta-wrap-up")
        self.assertTrue(results[0]["hasMetaClosing"])
        self.assertFalse(results[0]["hasQuestion"])

    def test_closing_result_compares_expected_context_terms(self):
        with patch(
            "app.conversation.application.next_message_service._request_json_completion",
            return_value={
                "aiMessage": "Thanks for being honest with me.",
                "translatedMessage": "솔직하게 말해줘서 고마워.",
                "innerThought": "무슨 뜻인지는 알겠다.",
                "innerThoughtType": "NORMAL",
            },
        ):
            results = evaluate_cases(
                [closing_case()],
                runs=1,
                kind="closing",
                settings=Settings(_env_file=None),
            )

        self.assertFalse(results[0].get("matchesExpectedContext", True))

    def test_feedback_result_compares_expected_type(self):
        feedback = MessageFeedbackData(
            messageId=2001,
            feedbackType="GOOD",
            baseLocaleAnalogy='"그래, 좋지"라고 자연스럽게 답하는 것과 같아요.',
            feedbackDetail="친구의 제안에 자연스럽게 동의했어요.",
        )
        response = MessageFeedbackResponse(
            sessionId=200,
            messageId=2001,
            feedbackStatus=FeedbackStatus.PREPARING,
        )

        with (
            patch(
                "scripts.evaluate_conversation_quality.generate_message_feedback",
                return_value=response,
            ),
            patch(
                "scripts.evaluate_conversation_quality.get_cached_message_feedback",
                return_value=feedback,
            ),
        ):
            results = evaluate_cases(
                [feedback_case()],
                runs=1,
                kind="message-feedback",
                settings=Settings(_env_file=None),
            )

        self.assertEqual(results[0]["feedbackType"], "GOOD")
        self.assertTrue(results[0]["feedbackTypeMatchesExpectation"])
