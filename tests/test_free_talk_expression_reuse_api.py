# 표현 추천 응답에 얹는 학습 표현 재사용 판정의 HTTP 계약을 검증하는 unittest 모듈
import json
import unittest
from unittest.mock import patch

from app.free_talk.application.expression_reuse_service import (
    DROPPED_WORKFLOW,
    EXPRESSION_REUSE_POLICY_HEADING,
    FALLBACK_WORKFLOW,
)
from app.free_talk.domain.expression_reuse_rules import ReuseClaim, verified_reuse_claims
from app.free_talk.llm.json_completion import AiGenerationFailedError
from app.main import create_app
from tests.test_free_talk_api import (
    FakeOpenAI,
    expression_selection,
    make_client,
    make_settings,
    valid_expression_recommendations_payload,
)

RECOMMENDATIONS_PATH = "/api/v1/free-talk/expression-recommendations"
REUSE_LOGGER = "app.free_talk.application.expression_reuse_service"
COFFEE_MESSAGE = "Wanna grab a quick coffee after? I'm down for anything, honestly."


def learned_expression(expression_id, text, meaning="뜻"):
    return {
        "expressionId": expression_id,
        "targetExpressionText": text,
        "baseExpressionMeaningText": meaning,
    }


def reuse_payload(**overrides):
    payload = valid_expression_recommendations_payload(
        conversationHistory=[
            {
                "messageId": 55020,
                "turnNumber": 1,
                "role": "USER",
                "content": "Hi. How are you? I'm working out now.",
                "translatedContent": None,
            },
            {
                "messageId": 55021,
                "turnNumber": 1,
                "role": "AI",
                "content": "Nice! Want to grab a coffee later?",
                "translatedContent": "좋아! 이따 커피 한잔할래?",
            },
            {
                "messageId": 55029,
                "turnNumber": 2,
                "role": "USER",
                "content": COFFEE_MESSAGE,
                "translatedContent": None,
            },
        ],
        learnedExpressions=[
            learned_expression(101, "grab a coffee"),
            learned_expression(87, "be down for"),
            learned_expression(73, "work out"),
        ],
    )
    payload.update(overrides)
    return payload


def used(*items):
    return json.dumps(
        {
            "usedExpressions": [
                {"expressionId": expression_id, "messageId": message_id, "matchedText": text}
                for expression_id, message_id, text in items
            ],
        }
    )


class ExpressionReuseApiTests(unittest.TestCase):
    def _post(self, payload, fake_openai):
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            )
        )
        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            return make_client(app).post(RECOMMENDATIONS_PATH, json=payload)

    def _fake(self, *reuse_contents):
        return FakeOpenAI(
            contents=[expression_selection(1)],
            reuse_contents=list(reuse_contents) or None,
        )

    def test_returns_variations_inserted_words_and_contractions_as_used(self):
        fake = self._fake(
            used(
                (101, 55029, "grab a quick coffee"),
                (87, 55029, "down for"),
                (73, 55020, "working out"),
            )
        )

        response = self._post(reuse_payload(), fake)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["usedExpressions"],
            [
                {"expressionId": 101, "messageId": 55029, "matchedText": "grab a quick coffee"},
                {"expressionId": 87, "messageId": 55029, "matchedText": "down for"},
                {"expressionId": 73, "messageId": 55020, "matchedText": "working out"},
            ],
        )
        self.assertEqual(len(fake.completions.calls), 1)
        self.assertEqual(len(fake.completions.reuse_calls), 1)

    def test_matched_text_is_replaced_with_the_exact_source_span(self):
        fake = self._fake(used((101, 55029, "GRAB  a quick coffee")))

        response = self._post(reuse_payload(), fake)

        self.assertEqual(
            response.json()["data"]["usedExpressions"],
            [{"expressionId": 101, "messageId": 55029, "matchedText": "grab a quick coffee"}],
        )

    def test_drops_unknown_ids_ai_messages_and_text_missing_from_source(self):
        fake = self._fake(
            used(
                (999, 55029, "grab a quick coffee"),
                (101, 55021, "grab a coffee"),
                (101, 70000, "grab a coffee"),
                (87, 55029, "up for anything"),
                (73, 55020, "working out"),
            )
        )

        with self.assertLogs(REUSE_LOGGER, level="WARNING") as logs:
            response = self._post(reuse_payload(), fake)

        self.assertEqual(
            response.json()["data"]["usedExpressions"],
            [{"expressionId": 73, "messageId": 55020, "matchedText": "working out"}],
        )
        self.assertIn(DROPPED_WORKFLOW, logs.output[0])
        self.assertIn("dropped=4 total=5", logs.output[0])
        self.assertNotIn("working out", logs.output[0])

    def test_same_expression_counts_once_per_message_and_again_in_another_message(self):
        payload = reuse_payload()
        payload["conversationHistory"][0]["content"] = "I work out a lot. I work out daily."
        fake = self._fake(
            used((73, 55020, "work out"), (73, 55020, "work out"), (87, 55029, "down for"))
        )

        response = self._post(payload, fake)

        self.assertEqual(
            [item["expressionId"] for item in response.json()["data"]["usedExpressions"]],
            [73, 87],
        )

    def test_missing_or_empty_learned_expressions_skips_the_reuse_call(self):
        for payload in (
            valid_expression_recommendations_payload(),
            reuse_payload(learnedExpressions=[]),
        ):
            with self.subTest(payload=payload.get("learnedExpressions")):
                fake = self._fake()

                response = self._post(payload, fake)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["usedExpressions"], [])
                self.assertEqual(len(fake.completions.reuse_calls), 0)

    def test_reuse_failure_never_blocks_recommendations(self):
        failures = {
            "generation_failed": AiGenerationFailedError(),
            "response_invalid": "not json",
            "contract_validation": json.dumps({"usedExpressions": [{"expressionId": 1}]}),
        }
        for reason, content in failures.items():
            with self.subTest(reason=reason):
                fake = self._fake(content)

                with self.assertLogs(REUSE_LOGGER, level="WARNING") as logs:
                    response = self._post(reuse_payload(), fake)

                self.assertEqual(response.status_code, 200)
                data = response.json()["data"]
                self.assertEqual(data["recommendations"][0]["existingExpressionId"], 1)
                self.assertEqual(data["usedExpressions"], [])
                self.assertIn(FALLBACK_WORKFLOW, logs.output[-1])
                self.assertIn(f"reason={reason}", logs.output[-1])

    def test_reuse_prompt_sends_only_user_messages_and_learned_expressions(self):
        fake = self._fake()

        self._post(reuse_payload(), fake)

        reuse_call = fake.completions.reuse_calls[0]
        self.assertIn(EXPRESSION_REUSE_POLICY_HEADING, reuse_call["messages"][0]["content"])
        user_prompt = json.loads(reuse_call["messages"][1]["content"])
        self.assertEqual(
            [message["messageId"] for message in user_prompt["userMessages"]],
            [55020, 55029],
        )
        self.assertEqual(len(user_prompt["learnedExpressions"]), 3)
        self.assertNotIn("existingExpressions", user_prompt)

    def test_recommendation_prompt_does_not_receive_learned_expressions(self):
        fake = self._fake()

        self._post(reuse_payload(), fake)

        recommendation_prompt = json.loads(fake.completions.calls[0]["messages"][1]["content"])
        self.assertNotIn("learnedExpressions", recommendation_prompt)
        self.assertIn("existingExpressions", recommendation_prompt)

    def test_rejects_too_many_duplicate_or_malformed_learned_expressions(self):
        invalid_lists = {
            "too_many": [learned_expression(index, "work out") for index in range(1, 52)],
            "duplicate_id": [learned_expression(7, "work out"), learned_expression(7, "be down")],
            "non_positive_id": [learned_expression(0, "work out")],
            "blank_text": [learned_expression(7, " ")],
            "undefined_field": [learned_expression(7, "work out") | {"usageSummary": "x"}],
        }
        for name, learned in invalid_lists.items():
            with self.subTest(name=name):
                fake = self._fake()

                response = self._post(reuse_payload(learnedExpressions=learned), fake)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
                self.assertEqual(len(fake.completions.calls), 0)

    def test_openapi_exposes_learned_and_used_expressions(self):
        schemas = create_app(make_settings()).openapi()["components"]["schemas"]

        self.assertIn("learnedExpressions", schemas["ExpressionRecommendationsRequest"]["properties"])
        self.assertIn("usedExpressions", schemas["ExpressionRecommendationsResponse"]["properties"])
        self.assertEqual(
            set(schemas["UsedExpression"]["required"]),
            {"expressionId", "messageId", "matchedText"},
        )


class ExpressionReuseRulesTests(unittest.TestCase):
    def test_keeps_only_claims_found_in_a_user_message_of_a_listed_expression(self):
        claims = [
            ReuseClaim(1, 10, "Working Out"),
            ReuseClaim(2, 10, "working out"),
            ReuseClaim(1, 11, "working out"),
            ReuseClaim(1, 10, "worked out"),
        ]

        verified = verified_reuse_claims(claims, {1}, {10: "I'm working out now."})

        self.assertEqual(verified, [ReuseClaim(1, 10, "working out")])

    def test_blank_matched_text_is_dropped(self):
        self.assertEqual(verified_reuse_claims([ReuseClaim(1, 10, "  ")], {1}, {10: "hello"}), [])


if __name__ == "__main__":
    unittest.main()
