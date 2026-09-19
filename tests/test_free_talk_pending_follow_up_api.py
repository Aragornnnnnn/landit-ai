# 오프닝과 첫 사용자 턴에서 지난 스몰톡의 후속 질문을 꺼내는 HTTP 계약을 검증하는 unittest 모듈
import json
import re
import unittest
from unittest.mock import patch

from app.free_talk.application.conversation_service import PENDING_FOLLOW_UP_HEADING
from app.main import create_app
from tests.test_free_talk_api import (
    FakeOpenAI,
    make_client,
    make_settings,
    normal_turn_completion,
    opening_completion,
    valid_opening_payload,
    valid_turn_payload,
)

OPENING_PATH = "/api/v1/free-talk/opening"
TURN_PATH = "/api/v1/free-talk/turn"
INTERVIEW_MEMORY = {
    "memoryId": 9020,
    "memoryType": "EVENT",
    "content": "2026년 9월 23일 화요일에 면접이 있다",
    "validFrom": "2026-09-16T21:02:10+09:00",
    "validTo": "2026-09-23T23:59:59+09:00",
    "observedAt": "2026-09-16T21:02:10+09:00",
}


def pending_follow_up(**overrides):
    pending = {
        "followUpId": 501,
        "memoryId": 9020,
        "triggerType": "CONCERN",
        "question": "저번에 말한 면접 준비, 어떻게 됐어?",
    }
    pending.update(overrides)
    return pending


def asked_opening(**overrides):
    return opening_completion(
        aiMessage="Hey! Good to see you again. So, how did the interview go?",
        translatedMessage="안녕! 다시 봐서 반가워. 그래서, 면접은 어떻게 됐어?",
        followUpAsked=True,
        **overrides,
    )


def asked_turn(**overrides):
    return normal_turn_completion(
        aiMessage="That sounds fun! Oh, by the way, how did the interview go?",
        translatedMessage="재밌겠다! 아, 그나저나 면접은 어떻게 됐어?",
        followUpAsked=True,
        **overrides,
    )


def without_clock(system_prompt):
    """시스템 프롬프트에 박히는 현재 시각은 호출마다 달라 비교에서 가린다."""
    return re.sub(r"\d{4}-\d{2}-\d{2}T[0-9:.]+[+-]\d{2}:\d{2}", "<now>", system_prompt)


class PendingFollowUpApiTests(unittest.TestCase):
    def _post(self, path, payload, fake_openai):
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            )
        )
        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            return make_client(app).post(path, json=payload)

    def _messages(self, fake):
        return fake.completions.calls[0]["messages"]

    def test_opening_asks_the_pending_question_and_echoes_its_id(self):
        fake = FakeOpenAI(contents=[json.dumps(asked_opening(usedMemoryIds=[9020]))])
        payload = valid_opening_payload() | {
            "memoryContext": [INTERVIEW_MEMORY],
            "pendingFollowUp": pending_follow_up(),
        }

        response = self._post(OPENING_PATH, payload, fake)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["followUpAsked"])
        self.assertEqual(data["followUpId"], 501)
        self.assertEqual(data["usedMemoryIds"], [9020])

    def test_asked_follow_up_counts_its_memory_as_used_even_when_the_model_omits_it(self):
        fake = FakeOpenAI(contents=[json.dumps(asked_turn(usedMemoryIds=[]))])
        payload = valid_turn_payload(
            memoryContext=[INTERVIEW_MEMORY],
            pendingFollowUp=pending_follow_up(),
        )

        data = self._post(TURN_PATH, payload, fake).json()["data"]

        self.assertEqual(data["usedMemoryIds"], [9020])

    def test_unasked_or_out_of_context_follow_up_memory_is_not_counted(self):
        cases = {
            "not_asked": (normal_turn_completion(followUpAsked=False), [INTERVIEW_MEMORY]),
            "memory_not_in_context": (asked_turn(), []),
        }
        for name, (completion, memory_context) in cases.items():
            with self.subTest(name=name):
                fake = FakeOpenAI(contents=[json.dumps(completion)])
                payload = valid_turn_payload(
                    memoryContext=memory_context,
                    pendingFollowUp=pending_follow_up(),
                )

                data = self._post(TURN_PATH, payload, fake).json()["data"]

                self.assertEqual(data["usedMemoryIds"], [])

    def test_opening_reports_when_the_question_could_not_be_asked(self):
        fake = FakeOpenAI(contents=[json.dumps(opening_completion(followUpAsked=False))])
        payload = valid_opening_payload() | {"pendingFollowUp": pending_follow_up(memoryId=None)}

        data = self._post(OPENING_PATH, payload, fake).json()["data"]

        self.assertFalse(data["followUpAsked"])
        self.assertEqual(data["followUpId"], 501)

    def test_follow_up_id_comes_from_the_request_not_the_model(self):
        completion = asked_opening() | {"followUpId": 999}
        fake = FakeOpenAI(contents=[json.dumps(completion)])
        payload = valid_opening_payload() | {"pendingFollowUp": pending_follow_up()}

        data = self._post(OPENING_PATH, payload, fake).json()["data"]

        self.assertEqual(data["followUpId"], 501)

    def test_without_pending_follow_up_the_model_cannot_claim_it_asked(self):
        cases = {
            OPENING_PATH: (valid_opening_payload(), opening_completion(followUpAsked=True)),
            TURN_PATH: (valid_turn_payload(), normal_turn_completion(followUpAsked=True)),
        }
        for path, (payload, completion) in cases.items():
            with self.subTest(path=path):
                fake = FakeOpenAI(contents=[json.dumps(completion)])

                data = self._post(path, payload, fake).json()["data"]

                self.assertFalse(data["followUpAsked"])
                self.assertIsNone(data["followUpId"])

    def test_first_user_turn_asks_the_pending_question(self):
        fake = FakeOpenAI(contents=[json.dumps(asked_turn())])
        payload = valid_turn_payload(pendingFollowUp=pending_follow_up())

        response = self._post(TURN_PATH, payload, fake)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["followUpAsked"])
        self.assertEqual(data["followUpId"], 501)
        self.assertFalse(data["userExitIntentDetected"])

    def test_exit_intent_never_counts_as_asked(self):
        completion = asked_turn(userExitIntentDetected=True)
        fake = FakeOpenAI(contents=[json.dumps(completion)])
        payload = valid_turn_payload(pendingFollowUp=pending_follow_up())

        data = self._post(TURN_PATH, payload, fake).json()["data"]

        self.assertTrue(data["userExitIntentDetected"])
        self.assertIsNone(data["aiMessage"])
        self.assertFalse(data["followUpAsked"])
        self.assertEqual(data["followUpId"], 501)

    def test_pending_follow_up_outside_the_first_user_turn_is_rejected(self):
        fake = FakeOpenAI(contents=[json.dumps(asked_turn())])
        payload = valid_turn_payload(isFirstUserTurn=False, pendingFollowUp=pending_follow_up())

        response = self._post(TURN_PATH, payload, fake)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(len(fake.completions.calls), 0)

    def test_rejects_malformed_pending_follow_up(self):
        invalid = {
            "none_trigger": pending_follow_up(triggerType="NONE"),
            "unknown_trigger": pending_follow_up(triggerType="WEATHER"),
            "blank_question": pending_follow_up(question=" "),
            "non_positive_id": pending_follow_up(followUpId=0),
            "undefined_field": pending_follow_up(invite="다음에 얘기하자."),
        }
        for name, pending in invalid.items():
            with self.subTest(name=name):
                fake = FakeOpenAI(contents=[json.dumps(asked_opening())])

                response = self._post(
                    OPENING_PATH, valid_opening_payload() | {"pendingFollowUp": pending}, fake
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_prompts_mention_the_follow_up_only_when_one_is_pending(self):
        cases = {
            OPENING_PATH: (valid_opening_payload(), asked_opening()),
            TURN_PATH: (valid_turn_payload(), asked_turn()),
        }
        for path, (payload, completion) in cases.items():
            with self.subTest(path=path):
                plain = FakeOpenAI(contents=[json.dumps(completion)])
                pending = FakeOpenAI(contents=[json.dumps(completion)])

                self._post(path, payload, plain)
                self._post(path, payload | {"pendingFollowUp": pending_follow_up()}, pending)

                plain_system, plain_user = (item["content"] for item in self._messages(plain))
                self.assertNotIn(PENDING_FOLLOW_UP_HEADING, plain_system)
                self.assertNotIn("pendingFollowUp", plain_user)
                self.assertNotIn("followUpAsked", json.dumps(plain.completions.calls[0]))

                pending_system, pending_user = (
                    item["content"] for item in self._messages(pending)
                )
                # 후속 질문 절은 기존 프롬프트 뒤에만 덧붙는다
                self.assertTrue(
                    without_clock(pending_system).startswith(without_clock(plain_system))
                )
                self.assertIn(PENDING_FOLLOW_UP_HEADING, pending_system)
                self.assertEqual(
                    json.loads(pending_user)["pendingFollowUp"]["question"],
                    "저번에 말한 면접 준비, 어떻게 됐어?",
                )
                self.assertIn("followUpAsked", json.dumps(pending.completions.calls[0]))

    def test_openapi_exposes_pending_follow_up_fields(self):
        schemas = create_app(make_settings()).openapi()["components"]["schemas"]

        for request in ("FreeTalkOpeningRequest", "FreeTalkTurnRequest"):
            self.assertIn("pendingFollowUp", schemas[request]["properties"])
        for response in ("FreeTalkOpeningResponse", "FreeTalkTurnResponse"):
            self.assertIn("followUpAsked", schemas[response]["properties"])
            self.assertIn("followUpId", schemas[response]["properties"])


if __name__ == "__main__":
    unittest.main()
