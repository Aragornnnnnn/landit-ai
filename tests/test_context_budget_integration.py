# 컨텍스트 예산과 후속 질문·턴 교정이 함께 동작하는 경계를 검증한다.
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.free_talk.application.conversation_service import safe_closing_response
from app.free_talk.llm.context_budget import estimate_request_tokens
from app.main import create_app
from tests.test_free_talk_api import (
    FakeOpenAI,
    closing_completion,
    inner_thought_completion,
    make_client,
    make_settings,
    normal_turn_completion,
    valid_closing_payload,
    valid_turn_payload,
)
from tests.test_free_talk_correction_api import (
    correction_completion,
    payload_with_partner_turn,
)
from tests.test_free_talk_pending_follow_up_api import asked_turn, pending_follow_up


class ContextBudgetIntegrationTests(unittest.TestCase):
    def _post(self, path, payload, fake, budget=8000):
        app = create_app(make_settings(
            openrouter_api_key="test-openrouter-key",
            openrouter_model="openai/gpt-5.4-mini",
            free_talk_context_input_budget_tokens=budget,
        ))
        with (
            patch("app.core.openai_client.OpenAI", return_value=fake),
            patch("app.free_talk.application.conversation_service.datetime") as clock,
        ):
            clock.now.return_value = datetime(2026, 9, 22, tzinfo=UTC)
            return make_client(app).post(path, json=payload)

    def test_follow_up_and_continue_repairs_run_above_the_budget(self):
        for mode in ("NORMAL", "CONTINUE_AFTER_EXIT_DECLINED"):
            with self.subTest(mode=mode):
                payload = valid_turn_payload(
                    contextPolicyVersion="v1", responseMode=mode,
                    pendingFollowUp=pending_follow_up(),
                )
                replies = [normal_turn_completion(followUpAsked=False), asked_turn()]
                if mode == "CONTINUE_AFTER_EXIT_DECLINED":
                    replies.insert(0, normal_turn_completion(
                        aiMessage=None, translatedMessage=None, followUpAsked=False,
                    ))
                fake = FakeOpenAI(contents=[json.dumps(reply) for reply in replies])
                response = self._post("/api/v1/free-talk/turn", payload, fake)

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["data"]["followUpAsked"])
                self.assertEqual(len(fake.completions.calls), len(replies))
                sizes = [estimate_request_tokens(
                    call["messages"][0]["content"], call["messages"][1]["content"],
                    call["response_format"], call["model"],
                ) for call in fake.completions.calls]
                self.assertGreater(max(sizes), sizes[0] + 5)
                self.assertLessEqual(max(sizes), 8000)

                oversized = FakeOpenAI(contents=[json.dumps(reply) for reply in replies])
                response = self._post(
                    "/api/v1/free-talk/turn", payload, oversized, budget=max(sizes) - 5,
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["data"]["followUpAsked"])
                self.assertEqual(len(oversized.completions.calls), len(replies))
                for call in oversized.completions.calls:
                    user = json.loads(call["messages"][1]["content"])
                    self.assertEqual(user["conversationHistory"], payload["conversationHistory"])

    def test_oversized_inner_thought_runs_generation_and_correction(self):
        payload = payload_with_partner_turn(contextPolicyVersion="v1")
        fake = FakeOpenAI(
            contents=[json.dumps(inner_thought_completion())],
            correction_contents=[json.dumps(correction_completion())],
        )
        response = self._post("/api/v1/free-talk/inner-thought", payload, fake, budget=1)

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["data"]["correction"])
        self.assertEqual(len(fake.completions.calls), 1)
        self.assertEqual(len(fake.completions.correction_calls), 1)
        user = json.loads(fake.completions.calls[0]["messages"][1]["content"])
        self.assertEqual(user["conversationHistory"], payload["conversationHistory"][-2:])

    def test_oversized_closing_keeps_generation_and_safe_fallback(self):
        payload = valid_closing_payload(contextPolicyVersion="v1")
        for completion, expected in (
            (json.dumps(closing_completion()), closing_completion()["aiMessage"]),
            (RuntimeError("provider unavailable"), safe_closing_response().aiMessage),
        ):
            with self.subTest(fallback=isinstance(completion, Exception)):
                fake = FakeOpenAI(contents=[completion])
                response = self._post("/api/v1/free-talk/closing", payload, fake, budget=1)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["aiMessage"], expected)
                self.assertEqual(len(fake.completions.calls), 1)
                user = json.loads(fake.completions.calls[0]["messages"][1]["content"])
                self.assertEqual(user["conversationHistory"], payload["conversationHistory"])

    def test_trimmed_inner_thought_repair_preserves_correction_source(self):
        payload = payload_with_partner_turn(contextPolicyVersion="v1")
        payload["conversationHistory"][0]["content"] = "Old conversation. " * 5000
        correction = correction_completion(reactedToPartner=False)
        fake = FakeOpenAI(
            contents=["not JSON", json.dumps(inner_thought_completion())],
            correction_contents=[json.dumps(correction)],
        )
        with self.assertLogs("app.common.failure_observation", level="WARNING") as logs:
            response = self._post("/api/v1/free-talk/inner-thought", payload, fake)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["innerThought"], inner_thought_completion()["innerThought"])
        self.assertFalse(data["reactedToPartner"])
        self.assertEqual(data["correction"]["originalSentence"], correction["correction"]["originalSentence"])
        self.assertEqual(len(fake.completions.calls), 2)
        for call in fake.completions.calls:
            user = json.loads(call["messages"][1]["content"])
            self.assertEqual(user["conversationHistory"], payload["conversationHistory"][-2:])
            self.assertTrue(user["historyIncomplete"])
            self.assertNotIn("memoryContext", user)
            self.assertNotIn("watchPatterns", user)
        self.assertEqual(len(fake.completions.correction_calls), 1)
        correction_user = fake.completions.correction_calls[0]["messages"][1]["content"]
        self.assertIn(payload["conversationHistory"][-1]["content"], correction_user)
        self.assertIn(payload["conversationHistory"][-2]["content"], correction_user)
        self.assertIn("reason=contract_repaired", " ".join(logs.output))
