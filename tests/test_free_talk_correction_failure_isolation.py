# 턴 교정의 예기치 못한 예외가 속마음 응답을 실패시키지 않는지 검증하는 unittest 모듈
import json
import unittest
from unittest.mock import patch

from app.free_talk.application.correction_service import FALLBACK_WORKFLOW
from app.main import create_app
from tests.test_free_talk_api import (
    FakeOpenAI,
    inner_thought_completion,
    make_client,
    make_settings,
)
from tests.test_free_talk_correction_api import (
    CORRECTION_LOGGER,
    INNER_THOUGHT_PATH,
    correction_completion,
    payload_with_partner_turn,
)

CONVERSATION_SERVICE = "app.free_talk.application.conversation_service"
CORRECTION_SERVICE = "app.free_talk.application.correction_service"
# 정규식·검증 오류의 메시지에는 입력값이 들어간다. 그 모양을 흉내 내 로그에 새지 않는지 본다.
LEAKY_ERROR = ValueError("bad input: I go to gym yesterday with my friend.")


class FailingExecutor:
    def __init__(self, *args, **kwargs):
        pass

    def submit(self, *args, **kwargs):
        raise RuntimeError("can't start new thread")

    def shutdown(self, *args, **kwargs):
        pass


class CorrectionFailureIsolationTests(unittest.TestCase):
    def _post(self, payload=None):
        fake = FakeOpenAI(
            contents=[json.dumps(inner_thought_completion())],
            correction_contents=[json.dumps(correction_completion())],
        )
        settings = make_settings(
            openrouter_api_key="test-openrouter-key", openrouter_model="openrouter-test-model"
        )
        with patch("app.core.openai_client.OpenAI", return_value=fake):
            return make_client(create_app(settings)).post(
                INNER_THOUGHT_PATH, json=payload or payload_with_partner_turn()
            )

    def assert_inner_thought_survives(self, response, logs):
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["innerThought"], "친구들과 등산을 간다니 꽤 기대하고 있나 보네.")
        self.assertEqual(data["innerThoughtType"], "GOOD")
        self.assertIsNone(data["reactedToPartner"])
        self.assertIsNone(data["correction"])
        self.assertIsNone(data["patternUsages"])
        self.assertEqual(len(logs.output), 1)
        self.assertIn(f"workflow={FALLBACK_WORKFLOW} reason=unexpected_error", logs.output[0])
        self.assertIn("sessionId=300 messageId=3004", logs.output[0])
        # 예외 메시지에는 사용자 발화가 담길 수 있어 타입과 위치만 남긴다
        self.assertNotIn("gym", logs.output[0])
        self.assertNotIn("bad input", logs.output[0])

    def test_bug_in_post_processing_does_not_fail_the_inner_thought(self):
        with (
            patch(f"{CORRECTION_SERVICE}._validated_result", side_effect=LEAKY_ERROR),
            self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs,
        ):
            response = self._post(payload_with_partner_turn(watchPatterns=["TENSE"]))

        self.assert_inner_thought_survives(response, logs)
        self.assertIn("exceptionType=ValueError", logs.output[0])
        # 고칠 수 있도록 어디서 났는지는 남긴다
        self.assertIn("correction_service.py:", logs.output[0])

    def test_exception_escaping_the_correction_call_does_not_fail_the_inner_thought(self):
        with (
            patch(f"{CONVERSATION_SERVICE}.generate_turn_correction", side_effect=LEAKY_ERROR),
            self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs,
        ):
            response = self._post()

        self.assert_inner_thought_survives(response, logs)
        self.assertIn("exceptionType=ValueError", logs.output[0])

    def test_failing_to_start_the_correction_thread_does_not_fail_the_inner_thought(self):
        with (
            patch(f"{CONVERSATION_SERVICE}.ThreadPoolExecutor", FailingExecutor),
            self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs,
        ):
            response = self._post()

        self.assert_inner_thought_survives(response, logs)
        self.assertIn("exceptionType=RuntimeError", logs.output[0])


if __name__ == "__main__":
    unittest.main()
