# 프리톡 대화 생성 API의 HTTP 계약을 검증하는 unittest 모듈
import json
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import Settings
from app.free_talk.llm.json_completion import AiResponseInvalidError
from app.main import create_app


def make_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def make_client(app):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated.*",
        )
        from fastapi.testclient import TestClient

        return TestClient(app)


class FakeCompletions:
    def __init__(self, *, contents=None, error=None):
        self.contents = list(contents or [])
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )


class FakeEmbeddings:
    def __init__(self, *, vectors=None, error=None, indices=None):
        self.vectors = vectors
        self.error = error
        self.indices = indices
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        vectors = self.vectors
        if vectors is None:
            vectors = [
                [0.001 * (position + 1)] * 1536
                for position in range(len(kwargs["input"]))
            ]
        indices = self.indices if self.indices is not None else range(len(vectors))
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=vector)
                for index, vector in zip(indices, vectors, strict=True)
            ],
        )


class FakeOpenAI:
    def __init__(
        self,
        *,
        contents=None,
        error=None,
        embedding_vectors=None,
        embedding_error=None,
        embedding_indices=None,
    ):
        self.completions = FakeCompletions(contents=contents, error=error)
        self.chat = SimpleNamespace(completions=self.completions)
        self.embeddings = FakeEmbeddings(
            vectors=embedding_vectors,
            error=embedding_error,
            indices=embedding_indices,
        )


def valid_opening_payload():
    return {
        "sessionId": 300,
        "characterId": "chloe",
        "targetLocale": "EN",
        "baseLocale": "KR",
        "topic": {
            "topicId": 2,
            "title": "주말 계획",
            "promptDescription": "Ask about the user's upcoming weekend plans.",
        },
    }


def valid_memory_context(memory_id=77, **overrides):
    context = {
        "memoryId": memory_id,
        "memoryType": "EVENT",
        "content": "사용자는 다음 주에 면접이 있다.",
        "validFrom": "2026-09-01T09:00:00",
        "validTo": "2026-09-30T18:00:00",
        "observedAt": "2026-08-28T10:30:00",
    }
    context.update(overrides)
    return context


def valid_turn_payload(**overrides):
    payload = {
        "sessionId": 300,
        "characterId": "chloe",
        "submittedMessageId": 3002,
        "submittedTurnNumber": 1,
        "targetLocale": "EN",
        "baseLocale": "KR",
        "responseMode": "NORMAL",
        "isFirstUserTurn": True,
        "topic": None,
        "conversationHistory": [
            {
                "messageId": 3002,
                "turnNumber": 1,
                "role": "USER",
                "content": "I'm going hiking with my friends.",
                "translatedContent": None,
            },
        ],
    }
    payload.update(overrides)
    return payload


def valid_closing_payload(**overrides):
    payload = {
        "sessionId": 300,
        "characterId": "chloe",
        "submittedMessageId": 3010,
        "submittedTurnNumber": 5,
        "targetLocale": "EN",
        "baseLocale": "KR",
        "closingReason": "USER_CONFIRMED",
        "titleGenerationRequired": False,
        "topic": {"title": "주말 등산 이야기"},
        "conversationHistory": [
            {
                "messageId": 3010,
                "turnNumber": 5,
                "role": "USER",
                "content": "I should get going now.",
                "translatedContent": None,
            },
        ],
    }
    payload.update(overrides)
    return payload


def valid_inner_thought_payload(**overrides):
    payload = valid_turn_payload()
    payload.pop("responseMode")
    payload.pop("isFirstUserTurn")
    payload.update(overrides)
    return payload


def opening_completion(**overrides):
    result = {
        "aiMessage": "Do you have any plans for the weekend?",
        "translatedMessage": "이번 주말에 무슨 계획 있어?",
        "emotion": "HAPPY",
        "usedMemoryIds": [],
    }
    result.update(overrides)
    return result


def normal_turn_completion(**overrides):
    result = {
        "userExitIntentDetected": False,
        "inferredTitle": "주말 등산 이야기",
        "aiMessage": "That sounds fun! Where are you going hiking?",
        "translatedMessage": "재밌겠다! 어디로 등산 가?",
        "emotion": "HAPPY",
        "usedMemoryIds": [],
    }
    result.update(overrides)
    return result


def closing_completion(**overrides):
    result = {
        "inferredTitle": None,
        "aiMessage": "No problem. It was great talking with you.",
        "translatedMessage": "그럼. 이야기해서 즐거웠어.",
        "emotion": "HAPPY",
    }
    result.update(overrides)
    return result


def inner_thought_completion(**overrides):
    result = {
        "innerThought": "친구들과 등산을 간다니 꽤 기대하고 있나 보네.",
        "answerCoverage": "COMPLETE",
        "relationshipTone": "WARM",
        "directedAttack": False,
    }
    result.update(overrides)
    return result


def valid_expression_recommendations_payload(**overrides):
    payload = {
        "sessionId": 300,
        "targetLocale": "EN",
        "baseLocale": "KR",
        "conversationHistory": [
            {
                "messageId": 3002,
                "turnNumber": 1,
                "role": "USER",
                "content": "I'm going hiking with my friends.",
                "translatedContent": None,
            },
        ],
        "existingExpressions": [
            {
                "expressionId": 1,
                "targetExpressionText": "There's nothing like",
                "baseExpressionMeaningText": "~만 한 게 없다",
                "usageSummary": "좋아하는 경험을 강조할 때 사용",
            },
        ],
    }
    payload.update(overrides)
    return payload


def expression_selection(*expression_ids):
    return json.dumps({"expressionIds": list(expression_ids)})


def existing_expression(expression_id, **overrides):
    expression = {
        "expressionId": expression_id,
        "targetExpressionText": f"There's nothing like {expression_id}",
        "baseExpressionMeaningText": f"~만 한 게 없다 {expression_id}",
        "usageSummary": f"좋아하는 경험을 강조할 때 사용 {expression_id}",
    }
    expression.update(overrides)
    return expression


def valid_conversation_embeddings_payload(**overrides):
    payload = {
        "sessionId": 300,
        "targetLocale": "EN",
        "baseLocale": "KR",
        "conversationHistory": [
            {
                "messageId": 3001,
                "turnNumber": 1,
                "role": "AI",
                "content": "Do you like cooking?",
                "translatedContent": "요리하는 거 좋아해?",
            },
            {
                "messageId": 3002,
                "turnNumber": 1,
                "role": "USER",
                "content": "That's easy for me. I cook every day.",
                "translatedContent": None,
            },
        ],
    }
    payload.update(overrides)
    return payload


def valid_memory_candidates_payload(**overrides):
    payload = {
        "sessionId": 300,
        "characterId": "chloe",
        "targetLocale": "EN",
        "baseLocale": "KR",
        "timezone": "Asia/Seoul",
        "conversationHistory": [
            {
                "messageId": 3001,
                "turnNumber": 1,
                "role": "AI",
                "content": "How was your weekend?",
                "translatedContent": "주말은 어땠어?",
                "occurredAt": "2026-08-25T20:00:00+09:00",
            },
            {
                "messageId": 3002,
                "turnNumber": 1,
                "role": "USER",
                "content": "I have an interview next Friday.",
                "translatedContent": None,
                "occurredAt": "2026-08-25T20:10:00+09:00",
            },
        ],
    }
    payload.update(overrides)
    return payload


def valid_memory_candidate_completion(**overrides):
    candidate = {
        "candidateIndex": 0,
        "memoryType": "EVENT",
        "content": "사용자는 2026년 8월 28일에 면접이 있다.",
        "contentLocale": "KR",
        "sourceMessageIds": [3002],
        "confidence": 0.94,
        "validFrom": "2026-08-25T20:10:00+09:00",
        "validTo": None,
    }
    candidate.update(overrides)
    return {"candidates": [candidate]}


def valid_memory_resolution_payload(**overrides):
    payload = {
        "candidates": [
            {
                "candidateIndex": 0,
                "content": "사용자는 면접에 합격했다.",
                "memoryType": "EVENT",
                "sourceMessageIds": [3002],
                "observedAt": "2026-08-29T19:20:00+09:00",
                "comparableMemories": [
                    {
                        "memoryId": 77,
                        "content": "사용자는 다음 주에 면접이 있다.",
                        "validFrom": "2026-08-25T20:10:00+09:00",
                        "validTo": None,
                        "observedAt": "2026-08-25T20:10:00+09:00",
                    },
                ],
            },
        ],
    }
    payload.update(overrides)
    return payload


class FreeTalkApiTests(unittest.TestCase):
    def _app(self, **overrides):
        settings = {
            "openrouter_api_key": "test-openrouter-key",
            "openrouter_model": "openrouter-test-model",
        }
        settings.update(overrides)
        return create_app(make_settings(**settings))

    def _post(self, path, payload, fake_openai):
        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            return make_client(self._app()).post(path, json=payload)

    def test_opening_returns_generated_message(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(opening_completion())])
        response = self._post(
            "/api/v1/free-talk/opening",
            valid_opening_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            opening_completion(emotion=None),
        )
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_opening_passes_memory_context_and_returns_used_memory_ids(self):
        fake_openai = FakeOpenAI(
            contents=[json.dumps(opening_completion(usedMemoryIds=[77]))],
        )
        response = self._post(
            "/api/v1/free-talk/opening",
            valid_opening_payload() | {"memoryContext": [valid_memory_context()]},
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["usedMemoryIds"], [77])
        user_prompt = fake_openai.completions.calls[0]["messages"][1]["content"]
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("memoryContext", user_prompt)
        self.assertIn('"validFrom": "2026-09-01T09:00:00"', user_prompt)
        self.assertIn('"validTo": "2026-09-30T18:00:00"', user_prompt)
        self.assertIn('"observedAt": "2026-08-28T10:30:00"', user_prompt)
        self.assertIn("untrusted reference data", system_prompt)

    def test_opening_normalizes_used_memory_id_outside_context(self):
        response = self._post(
            "/api/v1/free-talk/opening",
            valid_opening_payload() | {"memoryContext": [valid_memory_context()]},
            FakeOpenAI(contents=[json.dumps(opening_completion(usedMemoryIds=[88]))]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["usedMemoryIds"], [])

    def test_opening_requires_supported_character(self):
        for character_id in (None, "unknown"):
            with self.subTest(character_id=character_id):
                payload = valid_opening_payload()
                if character_id is None:
                    payload.pop("characterId")
                else:
                    payload["characterId"] = character_id

                response = self._post(
                    "/api/v1/free-talk/opening",
                    payload,
                    FakeOpenAI(contents=[json.dumps(opening_completion())]),
                )

                self.assertEqual(response.status_code, 400)

    def test_character_persona_and_dialect_are_added_to_generation_prompts(self):
        cases = (
            ("chloe", "American English", "friendly and upbeat"),
            ("marco", "Australian English", "relaxed and playful"),
            ("teddy", "British English", "calm and kind"),
        )

        for character_id, dialect, persona in cases:
            with self.subTest(character_id=character_id):
                fake_openai = FakeOpenAI(contents=[json.dumps(opening_completion())])
                response = self._post(
                    "/api/v1/free-talk/opening",
                    valid_opening_payload() | {"characterId": character_id},
                    fake_openai,
                )

                self.assertEqual(response.status_code, 200)
                system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
                self.assertIn(dialect, system_prompt)
                self.assertIn(persona, system_prompt)
                self.assertIn("avoid obscure slang", system_prompt)

    def test_character_policy_applies_to_turn_closing_and_inner_thought(self):
        cases = (
            (
                "/api/v1/free-talk/turn",
                valid_turn_payload(characterId="teddy"),
                normal_turn_completion(),
                "British English",
            ),
            (
                "/api/v1/free-talk/closing",
                valid_closing_payload(characterId="marco"),
                closing_completion(),
                "Australian English",
            ),
            (
                "/api/v1/free-talk/inner-thought",
                valid_inner_thought_payload(characterId="chloe"),
                inner_thought_completion(),
                "friendly and upbeat",
            ),
        )

        for path, payload, completion, expected_prompt in cases:
            with self.subTest(path=path):
                fake_openai = FakeOpenAI(contents=[json.dumps(completion)])
                response = self._post(path, payload, fake_openai)

                self.assertEqual(response.status_code, 200)
                system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
                self.assertIn(expected_prompt, system_prompt)
                if path.endswith("inner-thought"):
                    self.assertNotIn("American English", system_prompt)

    def test_turn_prompt_prohibits_direct_language_correction_and_feedback(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(normal_turn_completion())])

        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("Do not correct, rewrite, or evaluate", system_prompt)
        self.assertIn("even if the user asks for correction", system_prompt)
        self.assertIn("Silently ignore requests for correction", system_prompt)
        self.assertIn("do not mention that you ignored them", system_prompt)
        self.assertIn("respond naturally to the meaning", system_prompt)

    def test_turn_prompt_sets_concise_response_budget(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(normal_turn_completion())])

        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("20 to 35 words", system_prompt)
        self.assertIn("one or two sentences", system_prompt)

    def test_turn_prompt_avoids_restatement_and_limits_follow_up_question(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(normal_turn_completion())])

        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("without restating it", system_prompt)
        self.assertIn("at most one follow-up question", system_prompt)
        self.assertIn("Do not repeat the same reaction or empathy", system_prompt)

    def test_closing_prompt_prohibits_language_feedback(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(closing_completion())])

        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("Do not correct, rewrite, or evaluate", system_prompt)
        self.assertIn("Do not provide language-learning feedback", system_prompt)
        self.assertIn("Do not mention English proficiency", system_prompt)

    def test_closing_prompt_sets_concise_budget_without_summary(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(closing_completion())])

        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("15 to 30 words", system_prompt)
        self.assertIn("one or two sentences", system_prompt)
        self.assertIn("without summarizing it", system_prompt)

    def test_opening_prompt_prohibits_language_proficiency_feedback(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(opening_completion())])

        response = self._post(
            "/api/v1/free-talk/opening",
            valid_opening_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("Do not mention English proficiency", system_prompt)

    def test_turn_prompt_requires_exit_intent_field(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(normal_turn_completion())])

        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("Always return userExitIntentDetected", system_prompt)

    def test_inner_thought_prompt_requires_boolean_directed_attack(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(inner_thought_completion())])

        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("directedAttack must be a JSON boolean", system_prompt)
        self.assertIn('"directedAttack":false', system_prompt)
        self.assertIn(
            "Judge answer relevance and relationship tone separately.",
            system_prompt,
        )
        self.assertIn(
            "Do not praise or evaluate the user's wording, sentence length, or naturalness.",
            system_prompt,
        )

    def test_opening_maps_blank_llm_response_to_502(self):
        response = self._post(
            "/api/v1/free-talk/opening",
            valid_opening_payload(),
            FakeOpenAI(
                contents=[json.dumps(opening_completion(aiMessage="   "))],
            ),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_opening_ignores_unsupported_emotion(self):
        response = self._post(
            "/api/v1/free-talk/opening",
            valid_opening_payload(),
            FakeOpenAI(
                contents=[json.dumps(opening_completion(emotion="friendly"))],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["emotion"])

    def test_opening_rejects_internal_partner_name_field(self):
        payload = valid_opening_payload()
        payload["partnerDisplayName"] = "Harper"
        response = self._post(
            "/api/v1/free-talk/opening",
            payload,
            FakeOpenAI(contents=[json.dumps(opening_completion())]),
        )

        self.assertEqual(response.status_code, 400)

    def test_turn_normal_returns_visible_message_without_inner_thought(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(normal_turn_completion())])
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["aiMessage"],
            "That sounds fun! Where are you going hiking?",
        )
        self.assertNotIn("innerThought", response.json()["data"])
        self.assertIsNone(response.json()["data"]["emotion"])
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_turn_returns_only_used_memory_ids_from_context(self):
        fake_openai = FakeOpenAI(
            contents=[json.dumps(normal_turn_completion(usedMemoryIds=[77]))],
        )
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload() | {"memoryContext": [valid_memory_context()]},
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["usedMemoryIds"], [77])

    def test_turn_normalizes_duplicate_used_memory_ids(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload() | {"memoryContext": [valid_memory_context()]},
            FakeOpenAI(contents=[json.dumps(normal_turn_completion(usedMemoryIds=[77, 77]))]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["usedMemoryIds"], [])

    def test_turn_treats_all_null_topic_as_absent(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(normal_turn_completion())])
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(
                topic={
                    "topicId": None,
                    "title": None,
                    "promptDescription": None,
                },
            ),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        user_prompt = fake_openai.completions.calls[0]["messages"][1]["content"]
        self.assertIsNone(json.loads(user_prompt)["topic"])

    def test_turn_ignores_unsupported_emotion(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            FakeOpenAI(
                contents=[json.dumps(normal_turn_completion(emotion="friendly"))],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["emotion"])

    def test_inner_thought_returns_derived_type_separately_from_turn(self):
        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(),
            FakeOpenAI(contents=[json.dumps(inner_thought_completion())]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "innerThought": "친구들과 등산을 간다니 꽤 기대하고 있나 보네.",
                "innerThoughtType": "GOOD",
            },
        )

    def test_inner_thought_normalizes_known_negative_directed_attack_values(self):
        negative_values = (None, "", "NONE", "none", "no attack", "없음")

        for directed_attack in negative_values:
            with self.subTest(directed_attack=directed_attack):
                response = self._post(
                    "/api/v1/free-talk/inner-thought",
                    valid_inner_thought_payload(),
                    FakeOpenAI(
                        contents=[
                            json.dumps(
                                inner_thought_completion(
                                    directedAttack=directed_attack,
                                ),
                            ),
                        ],
                    ),
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["innerThoughtType"], "GOOD")

    def test_inner_thought_repairs_unrecognized_directed_attack_value(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    inner_thought_completion(
                        directedAttack="User directed a personal insult at the assistant.",
                    ),
                ),
                json.dumps(
                    inner_thought_completion(
                        directedAttack=True,
                        relationshipTone="HOSTILE",
                    ),
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["innerThoughtType"], "BAD")
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_inner_thought_repairs_missing_directed_attack(self):
        missing_directed_attack = inner_thought_completion()
        missing_directed_attack.pop("directedAttack")
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(missing_directed_attack),
                json.dumps(inner_thought_completion(directedAttack=True)),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["innerThoughtType"], "BAD")
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_inner_thought_falls_back_after_unrecognized_directed_attack_repair(self):
        inner_thought = "상대의 반응이 조금 애매하게 느껴진다."
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    inner_thought_completion(
                        innerThought=inner_thought,
                        directedAttack="unknown",
                    ),
                ),
                json.dumps(
                    inner_thought_completion(
                        innerThought=inner_thought,
                        directedAttack="still unknown",
                    ),
                ),
            ],
        )

        with self.assertLogs("app.common.inner_thought_contract", level="ERROR") as logs:
            response = self._post(
                "/api/v1/free-talk/inner-thought",
                valid_inner_thought_payload(),
                fake_openai,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["innerThought"], inner_thought)
        self.assertEqual(response.json()["data"]["innerThoughtType"], "NORMAL")
        self.assertEqual(len(fake_openai.completions.calls), 2)
        self.assertIn("workflow=free_talk_inner_thought_contract_fallback", logs.output[0])
        self.assertIn("fields=directedAttack", logs.output[0])
        self.assertNotIn(inner_thought, logs.output[0])

    def test_inner_thought_repairs_malformed_json_response(self):
        fake_openai = FakeOpenAI(
            contents=["not JSON", json.dumps(inner_thought_completion())],
        )

        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["innerThoughtType"], "GOOD")
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_inner_thought_uses_safe_fallback_after_malformed_json_repair(self):
        fake_openai = FakeOpenAI(contents=["not JSON", "still not JSON"])

        with self.assertLogs("app.common.inner_thought_contract", level="ERROR") as logs:
            response = self._post(
                "/api/v1/free-talk/inner-thought",
                valid_inner_thought_payload(),
                fake_openai,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "innerThought": "상대의 말을 받아들이고 있다.",
                "innerThoughtType": "NORMAL",
            },
        )
        self.assertEqual(len(fake_openai.completions.calls), 2)
        self.assertIn("reason=response_invalid", logs.output[0])

    def test_inner_thought_repairs_invalid_enum_response(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(inner_thought_completion(answerCoverage="UNKNOWN")),
                json.dumps(inner_thought_completion()),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["innerThoughtType"], "GOOD")
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_inner_thought_treats_all_null_topic_as_absent(self):
        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(
                topic={
                    "topicId": None,
                    "title": None,
                    "promptDescription": None,
                },
            ),
            FakeOpenAI(contents=[json.dumps(inner_thought_completion())]),
        )

        self.assertEqual(response.status_code, 200)

    def test_inner_thought_returns_repair_with_prohibited_feedback_language(self):
        inner_thought = (
            "답답하고 지친 마음이 느껴져서 안타까워요. "
            "문법 실수가 계속 나와서 속상한 기분이구나 하고 받아들여졌어요."
        )
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(inner_thought_completion(innerThought=inner_thought)),
                json.dumps(inner_thought_completion(innerThought=inner_thought)),
            ],
        )

        with self.assertLogs(
            "app.common.inner_thought_contract",
            level="ERROR",
        ) as logs:
            response = self._post(
                "/api/v1/free-talk/inner-thought",
                valid_inner_thought_payload(),
                fake_openai,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["innerThought"], inner_thought)
        self.assertEqual(response.json()["data"]["innerThoughtType"], "NORMAL")
        self.assertEqual(len(fake_openai.completions.calls), 2)
        self.assertIn(
            "workflow=free_talk_inner_thought_contract_fallback",
            logs.output[0],
        )
        self.assertIn("reason=prohibited_feedback_language", logs.output[0])
        self.assertNotIn(inner_thought, logs.output[0])

    def test_inner_thought_repairs_prohibited_feedback_language(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    inner_thought_completion(
                        innerThought="문법을 교정하면 더 자연스러워질 텐데.",
                    ),
                ),
                json.dumps(inner_thought_completion()),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["innerThoughtType"], "GOOD")
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_turn_does_not_generate_title_on_first_user_turn(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            FakeOpenAI(
                contents=[
                    json.dumps(normal_turn_completion(inferredTitle="Weekend Hiking")),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["inferredTitle"])

    def test_turn_ignores_inferred_title_after_first_user_turn(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(isFirstUserTurn=False),
            FakeOpenAI(contents=[json.dumps(normal_turn_completion())]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["inferredTitle"])

    def test_turn_ignores_non_string_inferred_title_after_first_user_turn(self):
        for title in ({"unexpected": "object"}, 123):
            with self.subTest(title=title):
                response = self._post(
                    "/api/v1/free-talk/turn",
                    valid_turn_payload(isFirstUserTurn=False),
                    FakeOpenAI(
                        contents=[
                            json.dumps(normal_turn_completion(inferredTitle=title)),
                        ],
                    ),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["data"]["inferredTitle"])

    def test_turn_exit_intent_returns_only_allowed_nullable_fields(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        normal_turn_completion(
                            userExitIntentDetected=True,
                            inferredTitle="주말 등산 이야기",
                            aiMessage=None,
                            translatedMessage=None,
                            emotion=None,
                        ),
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "userExitIntentDetected": True,
                "inferredTitle": None,
                "aiMessage": None,
                "translatedMessage": None,
                "emotion": None,
                "usedMemoryIds": [],
            },
        )

    def test_turn_ignores_generated_fields_when_exit_intent_is_detected(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        normal_turn_completion(userExitIntentDetected=True),
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "userExitIntentDetected": True,
                "inferredTitle": None,
                "aiMessage": None,
                "translatedMessage": None,
                "emotion": None,
                "usedMemoryIds": [],
            },
        )

    def test_turn_ignores_non_string_generated_fields_when_exit_intent_is_detected(
        self,
    ):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        normal_turn_completion(
                            userExitIntentDetected=True,
                            aiMessage={"unexpected": "object"},
                            translatedMessage=123,
                            emotion={"unexpected": "object"},
                        ),
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "userExitIntentDetected": True,
                "inferredTitle": None,
                "aiMessage": None,
                "translatedMessage": None,
                "emotion": None,
                "usedMemoryIds": [],
            },
        )

    def test_turn_continue_after_exit_declined_ignores_exit_intent_value(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(
                responseMode="CONTINUE_AFTER_EXIT_DECLINED",
                isFirstUserTurn=False,
            ),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        normal_turn_completion(
                            userExitIntentDetected={"unexpected": "object"},
                            inferredTitle=None,
                        ),
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["userExitIntentDetected"])
        self.assertIsNone(response.json()["data"]["inferredTitle"])

    def test_turn_continue_after_exit_declined_repairs_missing_visible_messages(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    normal_turn_completion(
                        userExitIntentDetected=False,
                        inferredTitle=None,
                        aiMessage=None,
                        translatedMessage=None,
                    ),
                ),
                json.dumps(
                    normal_turn_completion(
                        userExitIntentDetected=False,
                        inferredTitle=None,
                    ),
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(
                responseMode="CONTINUE_AFTER_EXIT_DECLINED",
                isFirstUserTurn=False,
            ),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["aiMessage"],
            "That sounds fun! Where are you going hiking?",
        )
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_turn_continue_after_exit_declined_repairs_blank_or_non_string_messages(self):
        invalid_messages = (
            (" ", "번역문"),
            ("다음 대사", 123),
        )

        for ai_message, translated_message in invalid_messages:
            with self.subTest(
                ai_message=ai_message,
                translated_message=translated_message,
            ):
                fake_openai = FakeOpenAI(
                    contents=[
                        json.dumps(
                            normal_turn_completion(
                                userExitIntentDetected=False,
                                inferredTitle=None,
                                aiMessage=ai_message,
                                translatedMessage=translated_message,
                            ),
                        ),
                        json.dumps(
                            normal_turn_completion(
                                userExitIntentDetected=False,
                                inferredTitle=None,
                            ),
                        ),
                    ],
                )

                response = self._post(
                    "/api/v1/free-talk/turn",
                    valid_turn_payload(
                        responseMode="CONTINUE_AFTER_EXIT_DECLINED",
                        isFirstUserTurn=False,
                    ),
                    fake_openai,
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_turn_continue_after_exit_declined_rejects_missing_messages_after_repair(
        self,
    ):
        invalid_completion = normal_turn_completion(
            userExitIntentDetected=False,
            inferredTitle=None,
            aiMessage=None,
            translatedMessage=None,
        )
        fake_openai = FakeOpenAI(
            contents=[json.dumps(invalid_completion), json.dumps(invalid_completion)],
        )

        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(
                responseMode="CONTINUE_AFTER_EXIT_DECLINED",
                isFirstUserTurn=False,
            ),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_closing_supports_both_reasons_without_inner_thought(self):
        for reason in ("USER_CONFIRMED", "TIME_LIMIT_REACHED"):
            with self.subTest(reason=reason):
                fake_openai = FakeOpenAI(
                    contents=[json.dumps(closing_completion())],
                )
                response = self._post(
                    "/api/v1/free-talk/closing",
                    valid_closing_payload(closingReason=reason),
                    fake_openai,
                )

                self.assertEqual(response.status_code, 200)
                self.assertNotIn("innerThought", response.json()["data"])
                self.assertIsNone(response.json()["data"]["emotion"])
                self.assertIsNone(response.json()["data"]["inferredTitle"])
                self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_closing_accepts_korean_and_english_titles_when_required(self):
        for title in ("주말 등산 이야기", "Weekend Hiking"):
            with self.subTest(title=title):
                fake_openai = FakeOpenAI(
                    contents=[json.dumps(closing_completion(inferredTitle=title))],
                )
                response = self._post(
                    "/api/v1/free-talk/closing",
                    valid_closing_payload(titleGenerationRequired=True),
                    fake_openai,
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["inferredTitle"], title)
                self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_closing_repairs_only_invalid_title_once(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(closing_completion(inferredTitle="123")),
                json.dumps({"inferredTitle": "Weekend Hiking"}),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(titleGenerationRequired=True),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["inferredTitle"], "Weekend Hiking")
        self.assertEqual(
            response.json()["data"]["aiMessage"],
            "No problem. It was great talking with you.",
        )
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_closing_returns_null_title_when_repair_is_invalid(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(closing_completion(inferredTitle="123")),
                json.dumps({"inferredTitle": "456"}),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(titleGenerationRequired=True),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["inferredTitle"])
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_closing_returns_null_title_when_repair_call_fails(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(closing_completion(inferredTitle="123")),
                RuntimeError("provider unavailable"),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(titleGenerationRequired=True),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["inferredTitle"])
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_closing_ignores_title_when_generation_is_not_required(self):
        fake_openai = FakeOpenAI(
            contents=[json.dumps(closing_completion(inferredTitle={"invalid": True}))],
        )

        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(titleGenerationRequired=False),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["inferredTitle"])
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_closing_ignores_unsupported_emotion(self):
        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(),
            FakeOpenAI(
                contents=[json.dumps(closing_completion(emotion="friendly"))],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["emotion"])

    def test_user_confirmed_closing_replaces_question_with_safe_message(self):
        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(closingReason="USER_CONFIRMED"),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        closing_completion(
                            aiMessage="Would you like to talk again?",
                            translatedMessage="다시 이야기할래?",
                        )
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["aiMessage"],
            "I really enjoyed hearing about that. Thanks for sharing!",
        )
        self.assertEqual(
            response.json()["data"]["translatedMessage"],
            "그 이야기 들으니까 정말 좋았어. 얘기해 줘서 고마워!",
        )

    def test_closing_replaces_generation_failure_with_safe_message(self):
        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(titleGenerationRequired=True),
            FakeOpenAI(error=RuntimeError("provider unavailable")),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "inferredTitle": None,
                "aiMessage": "I really enjoyed hearing about that. Thanks for sharing!",
                "translatedMessage": "그 이야기 들으니까 정말 좋았어. 얘기해 줘서 고마워!",
                "emotion": None,
            },
        )

    def test_closing_replaces_invalid_ai_contract_with_safe_message(self):
        invalid_contents = (
            "not json",
            json.dumps({"translatedMessage": "얘기해 줘서 고마워!"}),
        )

        for content in invalid_contents:
            with self.subTest(content=content):
                response = self._post(
                    "/api/v1/free-talk/closing",
                    valid_closing_payload(titleGenerationRequired=True),
                    FakeOpenAI(contents=[content]),
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["data"],
                    {
                        "inferredTitle": None,
                        "aiMessage": (
                            "I really enjoyed hearing about that. Thanks for sharing!"
                        ),
                        "translatedMessage": (
                            "그 이야기 들으니까 정말 좋았어. 얘기해 줘서 고마워!"
                        ),
                        "emotion": None,
                    },
                )

    def test_closing_does_not_replace_unexpected_error_with_safe_message(self):
        with patch(
            "app.api.free_talk.generate_closing",
            side_effect=RuntimeError("unexpected bug"),
        ), self.assertRaisesRegex(RuntimeError, "unexpected bug"):
            make_client(self._app()).post(
                "/api/v1/free-talk/closing",
                json=valid_closing_payload(),
            )

    def test_time_limit_closing_allows_question_form_message(self):
        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(closingReason="TIME_LIMIT_REACHED"),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        closing_completion(
                            aiMessage="That sort of musical stays with you, doesn't it?",
                            translatedMessage="그런 뮤지컬은 오래 기억에 남지 않아?",
                        )
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["aiMessage"],
            "That sort of musical stays with you, doesn't it?",
        )
        self.assertEqual(
            response.json()["data"]["translatedMessage"],
            "그런 뮤지컬은 오래 기억에 남지 않아?",
        )

    def test_closing_replaces_other_policy_violations_with_safe_message(self):
        prohibited_messages = (
            "Please review your feedback.",
            "This session has ended.",
            "By the way, let's talk about movies next time.",
        )

        for reason in ("USER_CONFIRMED", "TIME_LIMIT_REACHED"):
            for message in prohibited_messages:
                with self.subTest(reason=reason, message=message):
                    response = self._post(
                        "/api/v1/free-talk/closing",
                        valid_closing_payload(closingReason=reason),
                        FakeOpenAI(
                            contents=[
                                json.dumps(closing_completion(aiMessage=message)),
                            ],
                        ),
                    )

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        response.json()["data"]["aiMessage"],
                        "I really enjoyed hearing about that. Thanks for sharing!",
                    )
                    self.assertEqual(
                        response.json()["data"]["translatedMessage"],
                        "그 이야기 들으니까 정말 좋았어. 얘기해 줘서 고마워!",
                    )

    def test_closing_allows_natural_social_goodbye(self):
        allowed_messages = (
            "It was lovely talking with you. Take care.",
            "By the way, it was lovely talking with you.",
        )

        for message in allowed_messages:
            with self.subTest(message=message):
                response = self._post(
                    "/api/v1/free-talk/closing",
                    valid_closing_payload(),
                    FakeOpenAI(
                        contents=[
                            json.dumps(closing_completion(aiMessage=message)),
                        ],
                    ),
                )

                self.assertEqual(response.status_code, 200)

    def test_expression_recommendations_returns_one_to_three_recommendations(self):
        for count in (1, 3):
            with self.subTest(count=count):
                expression_ids = tuple(range(1, count + 1))
                fake_openai = FakeOpenAI(
                    contents=[expression_selection(*expression_ids)],
                )

                response = self._post(
                    "/api/v1/free-talk/expression-recommendations",
                    valid_expression_recommendations_payload(
                        existingExpressions=[
                            existing_expression(expression_id)
                            for expression_id in expression_ids
                        ],
                    ),
                    fake_openai,
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()["data"]["recommendations"]), count)
                self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_expression_recommendations_fill_texts_from_input_candidates(self):
        candidates = [existing_expression(expression_id) for expression_id in (1, 2)]

        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(existingExpressions=candidates),
            FakeOpenAI(contents=[expression_selection(2, 1)]),
        )

        self.assertEqual(response.status_code, 200)
        recommendations = response.json()["data"]["recommendations"]
        self.assertEqual(
            [
                (item["displayOrder"], item["existingExpressionId"])
                for item in recommendations
            ],
            [(1, 2), (2, 1)],
        )
        for recommendation in recommendations:
            source = next(
                candidate
                for candidate in candidates
                if candidate["expressionId"] == recommendation["existingExpressionId"]
            )
            self.assertEqual(
                recommendation["targetExpressionText"],
                source["targetExpressionText"],
            )
            self.assertEqual(
                recommendation["baseExpressionMeaningText"],
                source["baseExpressionMeaningText"],
            )
            self.assertEqual(recommendation["usageSummary"], source["usageSummary"])

    def test_expression_recommendations_rejects_unknown_existing_expression_id(self):
        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(),
            FakeOpenAI(contents=[expression_selection(999)]),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_expression_recommendations_rejects_duplicate_expression_id(self):
        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(
                existingExpressions=[existing_expression(1)],
            ),
            FakeOpenAI(contents=[expression_selection(1, 1)]),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_expression_recommendations_rejects_out_of_range_selection(self):
        for expression_ids in ((), (1, 2, 3, 4)):
            with self.subTest(count=len(expression_ids)):
                response = self._post(
                    "/api/v1/free-talk/expression-recommendations",
                    valid_expression_recommendations_payload(
                        existingExpressions=[
                            existing_expression(expression_id)
                            for expression_id in range(1, 5)
                        ],
                    ),
                    FakeOpenAI(contents=[expression_selection(*expression_ids)]),
                )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "AI_RESPONSE_INVALID",
                )

    def test_expression_recommendations_rejects_response_without_expression_ids(self):
        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(),
            FakeOpenAI(contents=[json.dumps({"recommendations": []})]),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_invalid_ai_response_without_message_is_not_rendered_as_none(self):
        self.assertEqual(str(AiResponseInvalidError()), "")

    def test_sdk_failure_maps_to_generation_failed(self):
        response = self._post(
            "/api/v1/free-talk/opening",
            valid_opening_payload(),
            FakeOpenAI(error=RuntimeError("provider unavailable")),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")

    def test_invalid_llm_settings_fail_before_openai_call(self):
        invalid_settings = (
            {"openrouter_api_key": None},
            {"openrouter_api_key": "   "},
            {"openrouter_model": None},
            {"openrouter_model": "   "},
            {"llm_provider": "unsupported"},
        )

        for settings in invalid_settings:
            with self.subTest(settings=settings), patch(
                "app.core.openai_client.OpenAI"
            ) as openai:
                response = make_client(self._app(**settings)).post(
                    "/api/v1/free-talk/opening",
                    json=valid_opening_payload(),
                )

                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["error"]["code"], "AI_GENERATION_FAILED"
                )
                openai.assert_not_called()

    def test_invalid_json_contract_maps_to_response_invalid(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            FakeOpenAI(contents=["not json"]),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_conversation_embeddings_returns_one_to_four_excerpts(self):
        for count in (1, 4):
            with self.subTest(count=count):
                excerpts = [f"That's easy for me {index}." for index in range(count)]
                fake_openai = FakeOpenAI(
                    contents=[json.dumps({"excerpts": excerpts})],
                )

                response = self._post(
                    "/api/v1/free-talk/conversation-embeddings",
                    valid_conversation_embeddings_payload(),
                    fake_openai,
                )

                self.assertEqual(response.status_code, 200)
                data = response.json()["data"]
                self.assertEqual(
                    [excerpt["excerptText"] for excerpt in data["excerpts"]],
                    excerpts,
                )
                for excerpt in data["excerpts"]:
                    self.assertEqual(len(excerpt["embedding"]), 1536)
                embedding_call = fake_openai.embeddings.calls[0]
                self.assertEqual(
                    embedding_call["model"], "openai/text-embedding-3-small"
                )
                self.assertEqual(embedding_call["input"], excerpts)
                self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_conversation_embeddings_repairs_invalid_excerpts_once(self):
        invalid_candidates = (
            ({}, "missing_excerpts", None),
            ({"excerpts": []}, "empty_excerpts", 0),
            (
                {"excerpts": [f"Sentence {index}." for index in range(5)]},
                "too_many_excerpts",
                5,
            ),
            ({"excerpts": ["   "]}, "blank_excerpt", 1),
        )

        for invalid_candidate, reason, count in invalid_candidates:
            with self.subTest(reason=reason):
                fake_openai = FakeOpenAI(
                    contents=[
                        json.dumps(invalid_candidate),
                        json.dumps({"excerpts": ["I cook every day."]}),
                    ],
                )

                with self.assertLogs(
                    "app.free_talk.application.embedding_service",
                    level="WARNING",
                ) as captured_logs:
                    response = self._post(
                        "/api/v1/free-talk/conversation-embeddings",
                        valid_conversation_embeddings_payload(),
                        fake_openai,
                    )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(fake_openai.completions.calls), 2)
                self.assertEqual(
                    fake_openai.embeddings.calls[0]["input"],
                    ["I cook every day."],
                )
                repair_prompt = fake_openai.completions.calls[1]["messages"][0][
                    "content"
                ]
                self.assertIn(reason, repair_prompt)
                self.assertIn("one to four non-blank strings", repair_prompt)
                self.assertIn("based only on USER messages", repair_prompt)
                self.assertIn(
                    "most meaningful non-blank USER utterance",
                    repair_prompt,
                )
                output = "\n".join(captured_logs.output)
                self.assertIn(f"reason={reason}", output)
                self.assertIn(f"excerptCount={count}", output)
                self.assertNotIn("That's easy for me", output)
                self.assertNotIn("Sentence 0.", output)

    def test_conversation_embeddings_does_not_repair_structural_excerpts(self):
        invalid_candidates = (
            {"excerpts": None},
            {"excerpts": "I cook every day."},
            {"excerpts": {"value": "I cook every day."}},
            {"excerpts": [123]},
            {"excerpts": [True]},
        )

        for invalid_candidate in invalid_candidates:
            with self.subTest(invalid_candidate=invalid_candidate):
                fake_openai = FakeOpenAI(
                    contents=[json.dumps(invalid_candidate)],
                )

                response = self._post(
                    "/api/v1/free-talk/conversation-embeddings",
                    valid_conversation_embeddings_payload(),
                    fake_openai,
                )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "AI_RESPONSE_INVALID",
                )
                self.assertEqual(len(fake_openai.completions.calls), 1)
                self.assertEqual(len(fake_openai.embeddings.calls), 0)

    def test_conversation_embeddings_rejects_invalid_excerpts_after_repair(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps({"excerpts": []}),
                json.dumps({"excerpts": ["   "]}),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            valid_conversation_embeddings_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertEqual(len(fake_openai.completions.calls), 2)
        self.assertEqual(len(fake_openai.embeddings.calls), 0)

    def test_conversation_embeddings_limits_too_many_excerpts_after_repair(self):
        repaired_excerpts = [f"Sentence {index}." for index in range(5)]
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps({"excerpts": repaired_excerpts}),
                json.dumps({"excerpts": repaired_excerpts}),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            valid_conversation_embeddings_payload(),
            fake_openai,
        )

        expected_excerpts = repaired_excerpts[:4]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                excerpt["excerptText"]
                for excerpt in response.json()["data"]["excerpts"]
            ],
            expected_excerpts,
        )
        self.assertEqual(
            fake_openai.embeddings.calls[0]["input"],
            expected_excerpts,
        )
        self.assertEqual(len(fake_openai.completions.calls), 2)

    def test_conversation_embeddings_rejects_wrong_dimensions(self):
        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            valid_conversation_embeddings_payload(),
            FakeOpenAI(
                contents=[json.dumps({"excerpts": ["That's easy for me."]})],
                embedding_vectors=[[0.1] * 1535],
            ),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_conversation_embeddings_reorders_vectors_by_index(self):
        first_vector = [0.1] * 1536
        second_vector = [0.2] * 1536
        fake_openai = FakeOpenAI(
            contents=[json.dumps({"excerpts": ["First sentence.", "Second one."]})],
            embedding_vectors=[second_vector, first_vector],
            embedding_indices=[1, 0],
        )

        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            valid_conversation_embeddings_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        excerpts = response.json()["data"]["excerpts"]
        self.assertEqual(excerpts[0]["excerptText"], "First sentence.")
        self.assertEqual(excerpts[0]["embedding"], first_vector)
        self.assertEqual(excerpts[1]["embedding"], second_vector)

    def test_conversation_embeddings_rejects_duplicate_embedding_indices(self):
        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            valid_conversation_embeddings_payload(),
            FakeOpenAI(
                contents=[json.dumps({"excerpts": ["First sentence.", "Second one."]})],
                embedding_vectors=[[0.1] * 1536, [0.2] * 1536],
                embedding_indices=[0, 0],
            ),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_conversation_embeddings_rejects_non_contiguous_embedding_indices(self):
        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            valid_conversation_embeddings_payload(),
            FakeOpenAI(
                contents=[json.dumps({"excerpts": ["First sentence.", "Second one."]})],
                embedding_vectors=[[0.1] * 1536, [0.2] * 1536],
                embedding_indices=[0, 2],
            ),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_conversation_embeddings_maps_embedding_failure_to_503(self):
        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            valid_conversation_embeddings_payload(),
            FakeOpenAI(
                contents=[json.dumps({"excerpts": ["That's easy for me."]})],
                embedding_error=RuntimeError("provider unavailable"),
            ),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")

    def test_conversation_embeddings_rejects_invalid_extraction_json(self):
        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            valid_conversation_embeddings_payload(),
            FakeOpenAI(contents=["not json"]),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_conversation_embeddings_requires_user_message_in_history(self):
        payload = valid_conversation_embeddings_payload()
        payload["conversationHistory"] = [payload["conversationHistory"][0]]

        response = self._post(
            "/api/v1/free-talk/conversation-embeddings",
            payload,
            FakeOpenAI(),
        )

        self.assertEqual(response.status_code, 400)

    def test_memory_query_embedding_returns_fixed_dimension_vector(self):
        fake_openai = FakeOpenAI()
        response = self._post(
            "/api/v1/free-talk/memory-query-embedding",
            {"query": " weekend plans "},
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["embeddingModel"],
            "openai/text-embedding-3-small",
        )
        self.assertEqual(len(response.json()["data"]["embedding"]), 1536)
        self.assertEqual(fake_openai.embeddings.calls[0]["input"], ["weekend plans"])

    def test_memory_query_embedding_rejects_blank_and_oversized_query(self):
        for query in ("   ", "x" * 2001):
            with self.subTest(query_length=len(query)):
                fake_openai = FakeOpenAI()
                response = self._post(
                    "/api/v1/free-talk/memory-query-embedding",
                    {"query": query},
                    fake_openai,
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(len(fake_openai.embeddings.calls), 0)

    def test_memory_query_embedding_maps_provider_failure_to_503(self):
        response = self._post(
            "/api/v1/free-talk/memory-query-embedding",
            {"query": "weekend plans"},
            FakeOpenAI(embedding_error=RuntimeError("provider unavailable")),
        )

        self.assertEqual(response.status_code, 503)

    def test_memory_query_embedding_rejects_invalid_dimension(self):
        response = self._post(
            "/api/v1/free-talk/memory-query-embedding",
            {"query": "weekend plans"},
            FakeOpenAI(embedding_vectors=[[0.1] * 1535]),
        )

        self.assertEqual(response.status_code, 502)

    def test_memory_candidates_returns_normalized_candidates_and_embeddings(self):
        fake_openai = FakeOpenAI(
            contents=[json.dumps(valid_memory_candidate_completion())],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        candidate = response.json()["data"]["candidates"][0]
        self.assertEqual(candidate["candidateIndex"], 0)
        self.assertEqual(
            response.json()["data"]["extractorVersion"],
            "memory-candidate-v2",
        )
        self.assertEqual(candidate["embeddingModel"], "openai/text-embedding-3-small")
        self.assertEqual(len(candidate["embedding"]), 1536)
        self.assertEqual(
            fake_openai.embeddings.calls[0]["model"],
            "openai/text-embedding-3-small",
        )

        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn("PROFILE is a stable user fact", system_prompt)
        self.assertIn("EVENT is a concrete past or future occurrence", system_prompt)
        self.assertIn("EPISODE is a shared experience", system_prompt)
        self.assertIn("Do not classify a fact as EPISODE merely", system_prompt)
        self.assertIn("Never keep relative time expressions", system_prompt)
        self.assertIn("'today', 'yesterday', 'tomorrow'", system_prompt)
        self.assertIn("Preserve relevant named entities and participants", system_prompt)
        self.assertIn("copy the request baseLocale exactly", system_prompt)

    def test_memory_candidates_rejects_ai_message_as_source(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    valid_memory_candidate_completion(sourceMessageIds=[3001]),
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertEqual(len(fake_openai.embeddings.calls), 0)

    def test_memory_candidates_rejects_non_contiguous_candidate_index(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    {
                        "candidates": [
                            valid_memory_candidate_completion()["candidates"][0]
                            | {"candidateIndex": 1},
                        ],
                    },
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_memory_candidates_allows_empty_candidate_list(self):
        fake_openai = FakeOpenAI(contents=[json.dumps({"candidates": []})])

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"],
            {
                "candidates": [],
                "extractorVersion": "memory-candidate-v2",
            },
        )
        self.assertEqual(len(fake_openai.embeddings.calls), 0)

    def test_memory_candidates_rejects_locale_mismatch_without_embedding_call(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    valid_memory_candidate_completion(contentLocale="EN"),
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(fake_openai.embeddings.calls), 0)

    def test_memory_candidates_rejects_naive_validity_time(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    valid_memory_candidate_completion(
                        validFrom="2026-08-25T20:10:00",
                    ),
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(fake_openai.embeddings.calls), 0)

    def test_memory_candidates_rejects_malformed_json_without_repair(self):
        fake_openai = FakeOpenAI(
            contents=[
                "not json",
                json.dumps(valid_memory_candidate_completion()),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_memory_candidates_rejects_missing_fields_without_repair(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps({"candidates": [{}]}),
                json.dumps(valid_memory_candidate_completion()),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_memory_candidates_does_not_repair_type_errors(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    valid_memory_candidate_completion(candidateIndex="zero"),
                ),
                json.dumps(valid_memory_candidate_completion()),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_memory_candidates_trims_content_before_length_validation(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    valid_memory_candidate_completion(content="x" * 500 + " "),
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-candidates",
            valid_memory_candidates_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["candidates"][0]["content"]), 500)

    def test_memory_resolution_returns_resolution_for_each_candidate(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    {
                        "resolutions": [
                            {
                                "candidateIndex": 0,
                                "operation": "SUPERSEDE",
                                "supersededMemoryIds": [77],
                            },
                        ],
                    },
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-resolution",
            valid_memory_resolution_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["resolutions"][0]["operation"],
            "SUPERSEDE",
        )
        self.assertEqual(
            fake_openai.completions.calls[0]["response_format"],
            {"type": "json_object"},
        )
        system_prompt = fake_openai.completions.calls[0]["messages"][0]["content"]
        self.assertIn(
            "candidateIndex, operation, and supersededMemoryIds",
            system_prompt,
        )
        self.assertIn("resolutions array", system_prompt)
        self.assertIn("exactly one object for every candidateIndex", system_prompt)

    def test_memory_resolution_rejects_missing_candidate_resolution(self):
        fake_openai = FakeOpenAI(contents=[json.dumps({"resolutions": []})])

        response = self._post(
            "/api/v1/free-talk/memory-resolution",
            valid_memory_resolution_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_memory_resolution_rejects_unknown_superseded_memory(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    {
                        "resolutions": [
                            {
                                "candidateIndex": 0,
                                "operation": "SUPERSEDE",
                                "supersededMemoryIds": [999],
                            },
                        ],
                    },
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-resolution",
            valid_memory_resolution_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_memory_resolution_rejects_superseded_ids_for_ignore(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    {
                        "resolutions": [
                            {
                                "candidateIndex": 0,
                                "operation": "IGNORE",
                                "supersededMemoryIds": [77],
                            },
                        ],
                    },
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-resolution",
            valid_memory_resolution_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_memory_resolution_rejects_memory_from_another_candidate(self):
        payload = valid_memory_resolution_payload()
        payload["candidates"].append(
            {
                "candidateIndex": 1,
                "content": "사용자는 새 직장에 적응 중이다.",
                "memoryType": "EVENT",
                "sourceMessageIds": [3002],
                "observedAt": "2026-08-29T19:20:00+09:00",
                "comparableMemories": [
                    {
                        "memoryId": 88,
                        "content": "사용자는 새 직장을 시작했다.",
                        "validFrom": "2026-08-25T20:10:00+09:00",
                        "validTo": None,
                        "observedAt": "2026-08-25T20:10:00+09:00",
                    },
                ],
            },
        )
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    {
                        "resolutions": [
                            {
                                "candidateIndex": 0,
                                "operation": "SUPERSEDE",
                                "supersededMemoryIds": [88],
                            },
                            {
                                "candidateIndex": 1,
                                "operation": "ADD",
                                "supersededMemoryIds": [],
                            },
                        ],
                    },
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-resolution",
            payload,
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_memory_resolution_rejects_missing_fields_without_repair(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps({}),
                json.dumps(
                    {
                        "resolutions": [
                            {
                                "candidateIndex": 0,
                                "operation": "SUPERSEDE",
                                "supersededMemoryIds": [77],
                            },
                        ],
                    },
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-resolution",
            valid_memory_resolution_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_memory_resolution_does_not_repair_type_errors(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    {
                        "resolutions": [
                            {
                                "candidateIndex": 0,
                                "operation": "INVALID",
                                "supersededMemoryIds": [],
                            },
                        ],
                    },
                ),
                json.dumps(
                    {
                        "resolutions": [
                            {
                                "candidateIndex": 0,
                                "operation": "SUPERSEDE",
                                "supersededMemoryIds": [77],
                            },
                        ],
                    },
                ),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/memory-resolution",
            valid_memory_resolution_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_openapi_exposes_all_free_talk_generation_routes(self):
        paths = self._app().openapi()["paths"]

        for path in (
            "/api/v1/free-talk/opening",
            "/api/v1/free-talk/turn",
            "/api/v1/free-talk/inner-thought",
            "/api/v1/free-talk/closing",
            "/api/v1/free-talk/expression-recommendations",
            "/api/v1/free-talk/conversation-embeddings",
            "/api/v1/free-talk/memory-candidates",
            "/api/v1/free-talk/memory-resolution",
            "/api/v1/free-talk/memory-query-embedding",
        ):
            with self.subTest(path=path):
                self.assertIn(path, paths)
        self.assertNotIn("/api/v1/free-talk/expression-learning-content", paths)
        self.assertNotIn("/api/v1/free-talk/embeddings", paths)

    def test_openapi_exposes_closing_title_contract(self):
        schemas = self._app().openapi()["components"]["schemas"]

        self.assertIn(
            "extractorVersion",
            schemas["MemoryCandidatesResponse"]["properties"],
        )
        self.assertNotIn("sensitivity", schemas["MemoryCandidate"]["properties"])
        self.assertIn(
            "titleGenerationRequired",
            schemas["FreeTalkClosingRequest"]["properties"],
        )
        self.assertIn(
            "inferredTitle",
            schemas["FreeTalkClosingResponse"]["properties"],
        )
        self.assertIn("memoryContext", schemas["FreeTalkOpeningRequest"]["properties"])
        for field in ("validFrom", "validTo", "observedAt"):
            self.assertIn(field, schemas["MemoryContext"]["properties"])
        self.assertIn("usedMemoryIds", schemas["FreeTalkOpeningResponse"]["properties"])
        self.assertIn("embedding", schemas["MemoryQueryEmbeddingResponse"]["properties"])
