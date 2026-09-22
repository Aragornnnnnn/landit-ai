# 프리톡 속마음 응답에 얹는 턴 교정·반응 판정의 HTTP 계약을 검증하는 unittest 모듈
import json
import time
import unittest
from unittest.mock import patch

from app.free_talk.application.correction_service import (
    CORRECTION_POLICY_HEADING,
    FALLBACK_WORKFLOW,
)
from app.free_talk.llm.json_completion import AiGenerationFailedError
from app.main import create_app
from app.models.free_talk import FreeTalkMistakePattern
from tests.test_free_talk_api import (
    FakeOpenAI,
    inner_thought_completion,
    make_client,
    make_settings,
    valid_inner_thought_payload,
)

INNER_THOUGHT_PATH = "/api/v1/free-talk/inner-thought"
CORRECTION_LOGGER = "app.free_talk.application.correction_service"


def correction_completion(**overrides):
    result = {
        "reactedToPartner": True,
        "hasCorrection": True,
        "correction": {
            "originalSentence": "I go to gym yesterday with my friend.",
            "betterSentence": "I went to the gym yesterday with my friend.",
            "reason": "어제 일이라 went로 말해야 해요. 그래야 언제 얘기인지 바로 알아들어요.",
            "mistakePattern": "TENSE",
        },
    }
    result.update(overrides)
    return result


def payload_with_partner_turn(**overrides):
    """직전 AI 말이 있는 두 번째 사용자 턴."""
    payload = valid_inner_thought_payload(
        submittedMessageId=3004,
        submittedTurnNumber=2,
        conversationHistory=[
            {
                "messageId": 3002,
                "turnNumber": 1,
                "role": "USER",
                "content": "I'm going hiking with my friends.",
                "translatedContent": None,
            },
            {
                "messageId": 3003,
                "turnNumber": 1,
                "role": "AI",
                "content": "That sounds fun! Did you do anything yesterday?",
                "translatedContent": "재밌겠다! 어제는 뭐 했어?",
            },
            {
                "messageId": 3004,
                "turnNumber": 2,
                "role": "USER",
                "content": "Yeah! I go to gym yesterday with my friend. It was tiring.",
                "translatedContent": None,
            },
        ],
    )
    payload.update(overrides)
    return payload


class FreeTalkTurnCorrectionApiTests(unittest.TestCase):
    def _post(self, payload, fake_openai, **settings_overrides):
        settings = {
            "openrouter_api_key": "test-openrouter-key",
            "openrouter_model": "openrouter-test-model",
        }
        settings.update(settings_overrides)
        with patch("app.core.openai_client.OpenAI", return_value=fake_openai) as openai_class:
            client = make_client(create_app(make_settings(**settings)))
            response = client.post(INNER_THOUGHT_PATH, json=payload)
        self.openai_constructor_calls = openai_class.call_args_list
        return response

    def _fake(self, correction, inner_thought=None):
        contents = [json.dumps(inner_thought or inner_thought_completion())]
        correction_contents = [
            correction if isinstance(correction, (Exception, str)) or callable(correction)
            else json.dumps(correction)
        ]
        return FakeOpenAI(contents=contents, correction_contents=correction_contents)

    def assert_inner_thought_intact(self, data):
        self.assertEqual(data["innerThought"], "친구들과 등산을 간다니 꽤 기대하고 있나 보네.")
        self.assertEqual(data["innerThoughtType"], "GOOD")

    def test_returns_correction_and_reaction_alongside_inner_thought(self):
        fake = self._fake(correction_completion(reactedToPartner=False))

        response = self._post(payload_with_partner_turn(), fake)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assert_inner_thought_intact(data)
        self.assertFalse(data["reactedToPartner"])
        self.assertEqual(
            data["correction"],
            {
                "originalSentence": "I go to gym yesterday with my friend.",
                "betterSentence": "I went to the gym yesterday with my friend.",
                "reason": "어제 일이라 went로 말해야 해요. 그래야 언제 얘기인지 바로 알아들어요.",
                "mistakePattern": "TENSE",
            },
        )
        self.assertEqual(len(fake.completions.calls), 1)
        self.assertEqual(len(fake.completions.correction_calls), 1)

    def test_inner_thought_repair_keeps_correction_and_records_recovery(self):
        correction = correction_completion(reactedToPartner=False)
        fake = FakeOpenAI(
            contents=["not JSON", json.dumps(inner_thought_completion())],
            correction_contents=[json.dumps(correction)],
        )

        with self.assertLogs("app.common.failure_observation", level="WARNING") as logs:
            response = self._post(payload_with_partner_turn(), fake)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assert_inner_thought_intact(data)
        self.assertFalse(data["reactedToPartner"])
        self.assertEqual(data["correction"], correction["correction"])
        self.assertEqual(len(fake.completions.calls), 2)
        self.assertEqual(len(fake.completions.correction_calls), 1)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("workflow=free_talk_inner_thought", logs.output[0])
        self.assertIn("reason=contract_repaired", logs.output[0])
        self.assertIn("outcome=recovered", logs.output[0])
        self.assertIn("attempt=2", logs.output[0])

    def test_no_correction_keeps_reaction_and_returns_null_correction(self):
        fake = self._fake(
            {"reactedToPartner": False, "hasCorrection": False, "correction": None}
        )

        response = self._post(payload_with_partner_turn(), fake)

        data = response.json()["data"]
        self.assertFalse(data["reactedToPartner"])
        self.assertIsNone(data["correction"])

    def test_original_sentence_is_normalized_to_the_submitted_text(self):
        fake = self._fake(
            correction_completion(
                correction={
                    **correction_completion()["correction"],
                    "originalSentence": "i go to   gym YESTERDAY with my friend.",
                }
            )
        )

        response = self._post(payload_with_partner_turn(), fake)

        self.assertEqual(
            response.json()["data"]["correction"]["originalSentence"],
            "I go to gym yesterday with my friend.",
        )

    def test_original_sentence_missing_from_submitted_text_drops_the_judgment(self):
        fake = self._fake(
            correction_completion(
                correction={
                    **correction_completion()["correction"],
                    "originalSentence": "I went to the gym yesterday.",
                }
            )
        )

        with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
            response = self._post(payload_with_partner_turn(), fake)

        data = response.json()["data"]
        self.assert_inner_thought_intact(data)
        self.assertIsNone(data["reactedToPartner"])
        self.assertIsNone(data["correction"])
        self.assertIn(f"workflow={FALLBACK_WORKFLOW}", logs.output[0])
        self.assertIn("reason=original_not_substring", logs.output[0])
        self.assertNotIn("gym", logs.output[0])

    def test_contract_violations_drop_the_judgment(self):
        cases = {
            "invalid_enum": correction_completion(
                correction={**correction_completion()["correction"], "mistakePattern": "TYPO"}
            ),
            "flag_mismatch": correction_completion(hasCorrection=False),
            "missing_reaction": {"hasCorrection": False, "correction": None},
            "string_bool": correction_completion(reactedToPartner="true"),
            "blank_better_sentence": correction_completion(
                correction={**correction_completion()["correction"], "betterSentence": "  "}
            ),
            "blank_reason": correction_completion(
                correction={**correction_completion()["correction"], "reason": ""}
            ),
        }
        for name, completion in cases.items():
            with self.subTest(case=name):
                with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
                    response = self._post(payload_with_partner_turn(), self._fake(completion))

                data = response.json()["data"]
                self.assertEqual(response.status_code, 200)
                self.assert_inner_thought_intact(data)
                self.assertIsNone(data["reactedToPartner"])
                self.assertIsNone(data["correction"])
                self.assertIn("reason=contract_validation", logs.output[0])

    def test_correction_call_failure_keeps_inner_thought(self):
        fake = self._fake(AiGenerationFailedError())

        with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
            response = self._post(payload_with_partner_turn(), fake)

        data = response.json()["data"]
        self.assertEqual(response.status_code, 200)
        self.assert_inner_thought_intact(data)
        self.assertIsNone(data["reactedToPartner"])
        self.assertIsNone(data["correction"])
        self.assertIn("reason=generation_failed", logs.output[-1])

    def test_correction_slower_than_timeout_is_dropped(self):
        def slow_completion():
            time.sleep(0.3)
            return json.dumps(correction_completion())

        fake = self._fake(slow_completion)

        with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
            response = self._post(
                payload_with_partner_turn(),
                fake,
                free_talk_correction_timeout_seconds=0.05,
            )

        data = response.json()["data"]
        self.assertEqual(response.status_code, 200)
        self.assert_inner_thought_intact(data)
        self.assertIsNone(data["reactedToPartner"])
        self.assertIsNone(data["correction"])
        self.assertIn("reason=timeout", logs.output[0])

    def test_first_turn_without_partner_message_reacts_by_definition(self):
        fake = self._fake(
            {"reactedToPartner": False, "hasCorrection": False, "correction": None}
        )

        response = self._post(valid_inner_thought_payload(), fake)

        self.assertTrue(response.json()["data"]["reactedToPartner"])

    def test_identical_better_sentence_is_not_a_correction(self):
        fake = self._fake(
            correction_completion(
                correction={
                    **correction_completion()["correction"],
                    "betterSentence": "I go to gym yesterday with my friend.",
                }
            )
        )

        with self.assertNoLogs(CORRECTION_LOGGER, level="WARNING"):
            response = self._post(payload_with_partner_turn(), fake)

        data = response.json()["data"]
        self.assertTrue(data["reactedToPartner"])
        self.assertIsNone(data["correction"])

    def test_correction_prompt_carries_policy_patterns_and_only_the_turn(self):
        fake = self._fake(correction_completion())

        self._post(payload_with_partner_turn(), fake)

        call = fake.completions.correction_calls[0]
        system_prompt = call["messages"][0]["content"]
        self.assertIn(CORRECTION_POLICY_HEADING, system_prompt)
        self.assertIn("Reaction Policy:", system_prompt)
        self.assertIn("Never force a correction", system_prompt)
        for pattern in FreeTalkMistakePattern:
            self.assertIn(f"{pattern.value}:", system_prompt)
        user_prompt = json.loads(call["messages"][1]["content"])
        self.assertEqual(
            user_prompt,
            {
                "targetLocale": "EN",
                "baseLocale": "KR",
                "previousPartnerMessage": "That sounds fun! Did you do anything yesterday?",
                "submittedMessage": "Yeah! I go to gym yesterday with my friend. It was tiring.",
            },
        )

    def test_correction_call_uses_its_own_model_and_timeout(self):
        fake = self._fake(correction_completion())

        self._post(
            payload_with_partner_turn(),
            fake,
            free_talk_correction_model="correction-test-model",
            free_talk_correction_timeout_seconds=4.5,
        )

        self.assertEqual(fake.completions.correction_calls[0]["model"], "correction-test-model")
        self.assertEqual(fake.completions.calls[0]["model"], "openrouter-test-model")
        # 타임아웃은 create()가 아니라 SDK 클라이언트 생성자로 전달된다 (재시도 0회와 함께).
        timeouts = [call.kwargs.get("timeout") for call in self.openai_constructor_calls]
        self.assertEqual(sorted(timeouts, key=str), sorted([4.5, None], key=str))
        correction_client = next(
            call for call in self.openai_constructor_calls if call.kwargs.get("timeout") == 4.5
        )
        self.assertEqual(correction_client.kwargs["max_retries"], 0)

    def test_openapi_schema_exposes_correction_fields(self):
        app = create_app(make_settings(openrouter_api_key="k", openrouter_model="m"))

        schemas = app.openapi()["components"]["schemas"]

        response_fields = schemas["FreeTalkInnerThoughtResponse"]["properties"]
        self.assertIn("reactedToPartner", response_fields)
        self.assertIn("correction", response_fields)
        self.assertEqual(
            set(schemas["FreeTalkMistakePattern"]["enum"]),
            {pattern.value for pattern in FreeTalkMistakePattern},
        )
        self.assertEqual(len(schemas["FreeTalkMistakePattern"]["enum"]), 17)
