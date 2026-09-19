# 프리톡 속마음 응답에 얹는 턴 교정·반응 판정의 HTTP 계약을 검증하는 unittest 모듈
import json
import time
import unittest
from unittest.mock import patch

from app.free_talk.application.correction_service import (
    CORRECTION_POLICY_HEADING,
    FALLBACK_WORKFLOW,
    UNKNOWN_MEMORY_WORKFLOW,
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


GYM_MEMORY = {
    "memoryId": 9012,
    "memoryType": "EPISODE",
    "content": "판교에 있는 헬스장에 다닌다",
    "validFrom": "2026-09-13T20:10:00+09:00",
    "validTo": None,
    "observedAt": "2026-09-13T20:10:00+09:00",
}


def gym_correction(**overrides):
    correction = {
        "originalSentence": "And I am doing stairs at a gym.",
        "betterSentence": "And I am doing stairs at the gym.",
        "reason": "저번에 말한 그 헬스장이면 the gym이라고 해요. 둘 다 아는 곳이니까요.",
        "mistakePattern": "ARTICLE",
        "usedMemoryId": None,
    }
    correction.update(overrides)
    return correction_completion(correction=correction)


def gym_payload(**overrides):
    payload = payload_with_partner_turn(**overrides)
    payload["conversationHistory"][-1]["content"] = (
        "Yes. I'm doing solid cardio session. And I am doing stairs at a gym."
    )
    return payload


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
                "usedMemoryId": None,
            },
        )
        self.assertEqual(len(fake.completions.calls), 1)
        self.assertEqual(len(fake.completions.correction_calls), 1)

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
                "memoryContext": [],
            },
        )

    def test_memory_grounded_correction_returns_the_used_memory_id(self):
        fake = self._fake(gym_correction(usedMemoryId=9012))

        response = self._post(gym_payload(memoryContext=[GYM_MEMORY]), fake)

        correction = response.json()["data"]["correction"]
        self.assertEqual(correction["originalSentence"], "And I am doing stairs at a gym.")
        self.assertEqual(correction["betterSentence"], "And I am doing stairs at the gym.")
        self.assertEqual(correction["mistakePattern"], "ARTICLE")
        self.assertEqual(correction["usedMemoryId"], 9012)

    def test_memory_id_outside_the_request_is_dropped_but_correction_stays(self):
        completion = correction_completion()
        completion["correction"]["usedMemoryId"] = 4040
        fake = self._fake(completion)

        with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
            response = self._post(payload_with_partner_turn(memoryContext=[GYM_MEMORY]), fake)

        correction = response.json()["data"]["correction"]
        self.assertEqual(correction["mistakePattern"], "TENSE")
        self.assertIsNone(correction["usedMemoryId"])
        self.assertIn(UNKNOWN_MEMORY_WORKFLOW, logs.output[-1])
        self.assertNotIn("gym", logs.output[-1])

    def test_article_swap_without_a_grounding_memory_is_not_a_correction(self):
        cases = {
            "no_memory": (gym_correction(), []),
            "memory_not_cited": (gym_correction(), [GYM_MEMORY]),
            "unknown_memory_cited": (gym_correction(usedMemoryId=4040), [GYM_MEMORY]),
        }
        for name, (completion, memory_context) in cases.items():
            with self.subTest(name=name):
                fake = self._fake(completion)

                response = self._post(gym_payload(memoryContext=memory_context), fake)

                data = response.json()["data"]
                self.assertIsNone(data["correction"])
                # 교정만 버리고 반응 판정은 그대로 둔다
                self.assertTrue(data["reactedToPartner"])

    def test_article_fix_that_adds_a_missing_word_is_kept_without_memory(self):
        completion = correction_completion(
            correction={
                "originalSentence": "I go to gym yesterday with my friend.",
                "betterSentence": "I go to the gym yesterday with my friend.",
                "reason": "gym 앞에 the가 빠졌어요.",
                "mistakePattern": "ARTICLE",
                "usedMemoryId": None,
            }
        )
        fake = self._fake(completion)

        response = self._post(payload_with_partner_turn(), fake)

        self.assertEqual(response.json()["data"]["correction"]["mistakePattern"], "ARTICLE")

    def test_memory_reaches_only_the_correction_prompt(self):
        fake = self._fake(gym_correction(usedMemoryId=9012))

        self._post(gym_payload(memoryContext=[GYM_MEMORY]), fake)

        correction_call = fake.completions.correction_calls[0]
        self.assertIn("Memory Grounding:", correction_call["messages"][0]["content"])
        correction_prompt = json.loads(correction_call["messages"][1]["content"])
        self.assertEqual(
            correction_prompt["memoryContext"],
            [
                {
                    "memoryId": 9012,
                    "content": "판교에 있는 헬스장에 다닌다",
                    "observedAt": "2026-09-13T20:10:00+09:00",
                }
            ],
        )
        # 속마음 판정에는 기억을 넘기지 않는다
        inner_thought_prompt = json.loads(fake.completions.calls[0]["messages"][1]["content"])
        self.assertNotIn("memoryContext", inner_thought_prompt)
        self.assertNotIn("판교", fake.completions.calls[0]["messages"][1]["content"])

    def test_inner_thought_prompt_is_unchanged_by_memory_context(self):
        plain = self._fake(gym_correction())
        with_memory = self._fake(gym_correction())

        self._post(gym_payload(), plain)
        self._post(gym_payload(memoryContext=[GYM_MEMORY]), with_memory)

        self.assertEqual(
            plain.completions.calls[0]["messages"],
            with_memory.completions.calls[0]["messages"],
        )

    def test_prompt_forbids_guessing_shared_knowledge_without_memory(self):
        fake = self._fake(gym_correction())

        self._post(gym_payload(), fake)

        system_prompt = fake.completions.correction_calls[0]["messages"][0]["content"]
        self.assertIn("'at a gym' is then correct as it stands", system_prompt)
        self.assertNotIn("(a place both know)", system_prompt)

    def test_rejects_more_than_three_memories(self):
        memories = [GYM_MEMORY | {"memoryId": index} for index in range(1, 5)]
        fake = self._fake(gym_correction())

        response = self._post(gym_payload(memoryContext=memories), fake)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

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
        self.assertIn("usedMemoryId", schemas["FreeTalkCorrection"]["properties"])
        self.assertIn("memoryContext", schemas["FreeTalkInnerThoughtRequest"]["properties"])
        self.assertEqual(
            set(schemas["FreeTalkMistakePattern"]["enum"]),
            {pattern.value for pattern in FreeTalkMistakePattern},
        )
        self.assertEqual(len(schemas["FreeTalkMistakePattern"]["enum"]), 17)
