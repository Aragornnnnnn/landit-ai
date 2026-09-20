# 프리톡 턴 교정의 강조 구절과 지켜볼 실수 패턴 사용례의 HTTP 계약을 검증하는 unittest 모듈
import json
import unittest
from unittest.mock import patch

from app.free_talk.application.correction_service import (
    PATTERN_USAGE_DROPPED_WORKFLOW,
    SPAN_DROPPED_WORKFLOW,
    WATCH_PATTERN_FILTERED_WORKFLOW,
)
from app.free_talk.llm.json_completion import AiGenerationFailedError
from app.main import create_app
from tests.test_free_talk_api import (
    FakeOpenAI,
    inner_thought_completion,
    make_client,
    make_settings,
)
from tests.test_free_talk_correction_api import (
    CORRECTION_LOGGER,
    GYM_MEMORY,
    INNER_THOUGHT_PATH,
    correction_completion,
    gym_correction,
    gym_payload,
    payload_with_partner_turn,
)

GYM_SENTENCE = "I go to gym yesterday with my friend."
TIRING_SENTENCE = "It was tiring."


def usage(pattern, sentence, span, correct):
    return {"pattern": pattern, "sentence": sentence, "span": span, "correct": correct}


def draft(**overrides):
    correction = dict(correction_completion()["correction"])
    correction.update(overrides)
    return correction


class FreeTalkPatternUsageApiTests(unittest.TestCase):
    def _post(self, payload, fake_openai):
        settings = make_settings(
            openrouter_api_key="test-openrouter-key", openrouter_model="openrouter-test-model"
        )
        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            return make_client(create_app(settings)).post(INNER_THOUGHT_PATH, json=payload)

    def _fake(self, correction):
        content = correction if isinstance(correction, Exception) else json.dumps(correction)
        return FakeOpenAI(
            contents=[json.dumps(inner_thought_completion())], correction_contents=[content]
        )

    def _data(self, payload, correction):
        response = self._post(payload, self._fake(correction))
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def test_span_that_is_not_in_its_sentence_is_dropped_alone(self):
        cases = {
            "not_found": draft(wrongSpan="goes"),
            # 같은 단어가 두 번 나오면 화면이 어느 쪽을 칠할지 알 수 없다
            "ambiguous": draft(
                betterSentence="I went to the gym yesterday with the friend.", betterSpan="the"
            ),
            "blank": draft(wrongSpan=" "),
        }
        for reason, correction in cases.items():
            with self.subTest(reason=reason):
                with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
                    data = self._data(
                        payload_with_partner_turn(),
                        correction_completion(correction=correction),
                    )

                field = "betterSpan" if reason == "ambiguous" else "wrongSpan"
                kept = "wrongSpan" if field == "betterSpan" else "betterSpan"
                self.assertIsNone(data["correction"][field])
                self.assertIsNotNone(data["correction"][kept])
                self.assertIn(f"workflow={SPAN_DROPPED_WORKFLOW}", logs.output[0])
                self.assertIn(f"reason={reason} field={field}", logs.output[0])
                # 구절에는 사용자 발화가 담기므로 로그에 남기지 않는다
                self.assertNotIn("gym", logs.output[0])

    def test_span_is_normalized_to_the_sentence_slice_and_may_be_null(self):
        data = self._data(
            payload_with_partner_turn(),
            correction_completion(correction=draft(wrongSpan="GO", betterSpan=None)),
        )

        self.assertEqual(data["correction"]["wrongSpan"], "go")
        self.assertIsNone(data["correction"]["betterSpan"])

    def test_watched_patterns_come_back_as_right_and_wrong_usages(self):
        completion = correction_completion(
            patternUsages=[
                usage("TENSE", GYM_SENTENCE, "go", False),
                usage("TENSE", TIRING_SENTENCE, "was", True),
            ]
        )

        data = self._data(payload_with_partner_turn(watchPatterns=["TENSE"]), completion)

        self.assertEqual(
            data["patternUsages"],
            [
                usage("TENSE", TIRING_SENTENCE, "was", True),
                usage("TENSE", GYM_SENTENCE, "go", False),
            ],
        )

    def test_invalid_usages_are_dropped_item_by_item(self):
        completion = correction_completion(
            hasCorrection=False,
            correction=None,
            patternUsages=[
                usage("TENSE", TIRING_SENTENCE, "was", True),
                usage("TENSE", TIRING_SENTENCE, "were", True),
                usage("TENSE", "I never said this.", "said", True),
                usage("ARTICLE", GYM_SENTENCE, "gym", False),
                usage("TENSE", TIRING_SENTENCE, "", True),
            ],
        )

        with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
            data = self._data(payload_with_partner_turn(watchPatterns=["TENSE"]), completion)

        self.assertEqual(data["patternUsages"], [usage("TENSE", TIRING_SENTENCE, "was", True)])
        self.assertIn(f"workflow={PATTERN_USAGE_DROPPED_WORKFLOW}", logs.output[0])
        self.assertIn("dropped=4 total=5", logs.output[0])
        self.assertNotIn("tiring", logs.output[0])

    def test_no_usage_is_an_empty_list_and_no_watch_is_null(self):
        nothing = {
            "reactedToPartner": True,
            "hasCorrection": False,
            "correction": None,
            "patternUsages": [],
        }

        watched = self._data(payload_with_partner_turn(watchPatterns=["ARTICLE"]), nothing)
        plain = self._data(payload_with_partner_turn(), correction_completion())

        self.assertEqual(watched["patternUsages"], [])
        self.assertIsNone(plain["patternUsages"])

    def test_failed_judgment_returns_null_usages(self):
        with self.assertLogs(CORRECTION_LOGGER, level="WARNING"):
            data = self._data(
                payload_with_partner_turn(watchPatterns=["TENSE"]),
                AiGenerationFailedError("boom"),
            )

        self.assertIsNone(data["correction"])
        self.assertIsNone(data["patternUsages"])

    def test_missing_usages_in_a_watched_reply_is_a_contract_violation(self):
        with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
            data = self._data(
                payload_with_partner_turn(watchPatterns=["TENSE"]), correction_completion()
            )

        self.assertIsNone(data["patternUsages"])
        self.assertIn("reason=contract_validation", logs.output[0])

    def test_correction_on_a_watched_pattern_is_always_a_wrong_usage(self):
        completion = correction_completion(
            patternUsages=[usage("TENSE", GYM_SENTENCE, "I go", True)]
        )

        data = self._data(payload_with_partner_turn(watchPatterns=["TENSE"]), completion)

        self.assertEqual(data["patternUsages"], [usage("TENSE", GYM_SENTENCE, "go", False)])

    def test_correction_dropped_by_server_rules_takes_its_wrong_usage_with_it(self):
        gym = "And I am doing stairs at a gym."
        completion = gym_correction(wrongSpan="a gym", betterSpan="the gym")
        completion["patternUsages"] = [
            usage("ARTICLE", gym, "a", False),
            usage("ARTICLE", "Yes. I'm doing solid cardio session.", "solid", False),
        ]

        data = self._data(gym_payload(watchPatterns=["ARTICLE"]), completion)

        # 기억 근거 없는 a→the 교정은 버려진다. 같은 자리를 틀렸다고 한 사용례가 남으면 카드가 어긋난다.
        self.assertIsNone(data["correction"])
        self.assertEqual(
            data["patternUsages"],
            [usage("ARTICLE", "Yes. I'm doing solid cardio session.", "solid", False)],
        )

    def test_requests_without_countable_watch_patterns_are_identical_to_plain_ones(self):
        calls = []
        for overrides in ({}, {"watchPatterns": []}, {"watchPatterns": ["NATURALNESS"]}):
            fake = self._fake(correction_completion())
            self._post(payload_with_partner_turn(**overrides), fake)
            calls.append(fake.completions.correction_calls[0])

        # 지켜볼 패턴이 없는 요청은 입력·프롬프트·스키마가 글자까지 같아야 교정 품질 회귀가 없다
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[0], calls[2])
        self.assertNotIn("patternUsages", json.dumps(calls[0]))
        self.assertNotIn("watchPatterns", json.dumps(calls[0]))
        self.assertNotIn("Watched Patterns:", json.dumps(calls[0]))

    def test_uncountable_watch_patterns_are_filtered_with_a_trace(self):
        completion = correction_completion(patternUsages=[])
        fake = self._fake(completion)

        with self.assertLogs(CORRECTION_LOGGER, level="WARNING") as logs:
            self._post(payload_with_partner_turn(watchPatterns=["OTHER", "TENSE"]), fake)

        self.assertIn(f"workflow={WATCH_PATTERN_FILTERED_WORKFLOW}", logs.output[0])
        self.assertIn("filtered=1 total=2", logs.output[0])
        user_prompt = json.loads(fake.completions.correction_calls[0]["messages"][1]["content"])
        self.assertEqual(user_prompt["watchPatterns"], ["TENSE"])

    def test_watch_section_is_appended_after_the_unchanged_prompt(self):
        plain = self._fake(correction_completion())
        watched = self._fake(correction_completion(patternUsages=[]))

        self._post(payload_with_partner_turn(), plain)
        self._post(payload_with_partner_turn(watchPatterns=["TENSE"]), watched)

        plain_system = plain.completions.correction_calls[0]["messages"][0]["content"]
        watched_call = watched.completions.correction_calls[0]
        watched_system = watched_call["messages"][0]["content"]
        self.assertTrue(watched_system.startswith(plain_system.split("Output Schema:")[0]))
        self.assertIn("Watched Patterns:", watched_system)
        self.assertIn("Highlight Spans:", plain_system)
        self.assertIn("patternUsages", json.dumps(watched_call["response_format"]))

    def test_memory_label_and_watch_patterns_combine_in_one_schema(self):
        completion = gym_correction(
            usedMemoryId=9012, memoryLabel="헬스장", wrongSpan="a gym", betterSpan="the gym"
        )
        completion["patternUsages"] = []
        fake = self._fake(completion)

        response = self._post(
            gym_payload(memoryContext=[GYM_MEMORY], watchPatterns=["ARTICLE"]), fake
        )

        data = response.json()["data"]
        schema = json.dumps(fake.completions.correction_calls[0]["response_format"])
        self.assertIn("memoryLabel", schema)
        self.assertIn("patternUsages", schema)
        self.assertEqual(data["correction"]["memoryLabel"], "헬스장")
        self.assertEqual(
            data["patternUsages"],
            [usage("ARTICLE", "And I am doing stairs at a gym.", "a gym", False)],
        )

    def test_watch_patterns_are_validated_at_the_request_boundary(self):
        for watch in (["TENSE", "TENSE"], ["PAST_TENSE"], ["TENSE", "ARTICLE", "PLURAL", "PRONOUN"]):
            with self.subTest(watch=watch):
                response = self._post(
                    payload_with_partner_turn(watchPatterns=watch),
                    self._fake(correction_completion()),
                )
                self.assertEqual(response.status_code, 400)

    def test_openapi_schema_exposes_span_and_usage_fields(self):
        app = create_app(make_settings(openrouter_api_key="k", openrouter_model="m"))

        schemas = app.openapi()["components"]["schemas"]

        self.assertIn("watchPatterns", schemas["FreeTalkInnerThoughtRequest"]["properties"])
        self.assertIn("patternUsages", schemas["FreeTalkInnerThoughtResponse"]["properties"])
        for field in ("wrongSpan", "betterSpan"):
            self.assertEqual(
                schemas["FreeTalkCorrection"]["properties"][field]["anyOf"],
                [{"type": "string"}, {"type": "null"}],
            )
        self.assertEqual(
            set(schemas["FreeTalkPatternUsage"]["required"]),
            {"pattern", "sentence", "span", "correct"},
        )


if __name__ == "__main__":
    unittest.main()
