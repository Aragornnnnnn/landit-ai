# BE에 저장한 메시지 평가가 캐시 없이 같은 최종 결과를 만드는지 검증한다.
import copy
import json
import unittest
from unittest.mock import patch

from app.conversation.application.next_message_service import clear_message_feedback_cache
from app.main import create_app
from tests.test_conversation_api import (
    FakeOpenAI,
    good_message_feedback,
    make_client,
    make_settings,
    valid_message_feedback_payload,
    valid_session_feedback_payload,
)


class DurableMessageFeedbackTests(unittest.TestCase):
    def setUp(self):
        clear_message_feedback_cache()
        self.client = make_client(create_app(make_settings(
            openrouter_api_key="test", openrouter_model="test",
        )))
        with patch("app.core.openai_client.OpenAI", return_value=FakeOpenAI(
            message_feedback=good_message_feedback(1001),
        )):
            result = self.client.post("/api/v1/conversation/message-feedback",
                                      json=valid_message_feedback_payload())
        self.assertEqual(result.status_code, 202)
        self.snapshot = result.json()["data"]["completedFeedback"]
        self.assertEqual(self.snapshot["schemaVersion"], 1)
        self.assertEqual(self.snapshot["feedback"]["messageId"], 1001)
        self.assertEqual(self.snapshot["scoreEvidence"]["contextFit"], 2)
        self.assertTrue(self.snapshot["adjudicationEvidence"]["coverageEvidence"])
        self.payload = valid_session_feedback_payload()
        self.payload["expectedMessageIds"] = [1001]
        self.payload["assessmentMessages"] = []

    def _summary(self, payload):
        with patch("app.core.openai_client.OpenAI", return_value=FakeOpenAI(content=json.dumps({"sessionId": 100, "highlightMessage": "의도를 잘 전달했어요.", "summaryMessage": "질문에 맞춰 대답했어요."}))):
            return self.client.post("/api/v1/conversation/session-feedback", json=payload)

    def test_saved_result_survives_instance_change_and_repeated_request(self):
        legacy = self._summary(self.payload)
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(self._summary(self.payload).status_code, 200)
        clear_message_feedback_cache()
        self.assertEqual(self._summary(self.payload).status_code, 409)
        self.payload["completedFeedbacks"] = [self.snapshot]
        for _ in range(2):
            response = self._summary(self.payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), legacy.json())

    def test_explicit_incomplete_foreign_or_unsupported_input_never_uses_cache(self):
        foreign = copy.deepcopy(self.snapshot)
        foreign["sessionId"] += 1
        unsupported = copy.deepcopy(self.snapshot)
        unsupported["schemaVersion"] = 2
        boolean_version = copy.deepcopy(self.snapshot)
        boolean_version["schemaVersion"] = True
        for snapshots in ([], [foreign], [unsupported], [boolean_version], [self.snapshot, self.snapshot]):
            with self.subTest(snapshots=snapshots):
                self.payload["completedFeedbacks"] = snapshots
                self.assertEqual(self._summary(self.payload).status_code, 400)

    def test_failed_generation_has_no_completed_result(self):
        with patch("app.core.openai_client.OpenAI", side_effect=RuntimeError("unused")):
            client = make_client(create_app(make_settings()))
            result = client.post("/api/v1/conversation/message-feedback",
                                 json=valid_message_feedback_payload())
        self.assertEqual(result.json()["data"]["feedbackStatus"], "FAILED")
        self.assertIsNone(result.json()["data"]["completedFeedback"])
