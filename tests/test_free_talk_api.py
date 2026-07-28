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
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )


class FakeOpenAI:
    def __init__(self, *, contents=None, error=None):
        self.completions = FakeCompletions(contents=contents, error=error)
        self.chat = SimpleNamespace(completions=self.completions)


def valid_opening_payload():
    return {
        "sessionId": 300,
        "targetLocale": "EN",
        "baseLocale": "KR",
        "partnerDisplayName": "Harper",
        "accentLocale": "EN_US",
        "topic": {
            "topicId": 2,
            "title": "주말 계획",
            "promptDescription": "Ask about the user's upcoming weekend plans.",
        },
    }


def valid_turn_payload(**overrides):
    payload = {
        "sessionId": 300,
        "submittedMessageId": 3002,
        "submittedTurnNumber": 1,
        "targetLocale": "EN",
        "baseLocale": "KR",
        "partnerDisplayName": "Harper",
        "accentLocale": "EN_US",
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
        "submittedMessageId": 3010,
        "submittedTurnNumber": 5,
        "targetLocale": "EN",
        "baseLocale": "KR",
        "partnerDisplayName": "Harper",
        "accentLocale": "EN_US",
        "closingReason": "USER_CONFIRMED",
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


def opening_completion(**overrides):
    result = {
        "aiMessage": "Do you have any plans for the weekend?",
        "translatedMessage": "이번 주말에 무슨 계획 있어?",
        "emotion": "HAPPY",
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
        "innerThought": "친구들과 등산을 간다니 꽤 기대하고 있나 보네.",
        "innerThoughtType": "BAD",
        "answerCoverage": "COMPLETE",
        "relationshipTone": "WARM",
        "directedAttack": False,
    }
    result.update(overrides)
    return result


def closing_completion(**overrides):
    result = {
        "aiMessage": "No problem. It was great talking with you.",
        "translatedMessage": "그럼. 이야기해서 즐거웠어.",
        "emotion": "HAPPY",
        "innerThought": "이제 가봐야 하나 보네. 즐겁게 얘기해서 좋았다.",
        "innerThoughtType": "BAD",
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


def expression_recommendation(**overrides):
    recommendation = {
        "displayOrder": 1,
        "sourceType": "EXISTING",
        "existingExpressionId": 1,
        "targetExpressionText": "There's nothing like",
        "baseExpressionMeaningText": "~만 한 게 없다",
        "usageSummary": "좋아하는 경험을 강조할 때 사용",
        "contextualExample": {
            "sentenceText": "There's nothing like hiking with friends.",
            "sentenceTranslation": "친구들과 등산하는 것만 한 게 없어.",
        },
    }
    recommendation.update(overrides)
    return recommendation


def valid_expression_learning_content_payload(**overrides):
    payload = {
        "sessionId": 300,
        "targetLocale": "EN",
        "baseLocale": "KR",
        "expressions": [
            {
                "targetExpressionText": "I'm up for that",
                "baseExpressionMeaningText": "좋아, 그거 하자",
                "usageSummary": "제안에 동의할 때 사용",
            },
        ],
    }
    payload.update(overrides)
    return payload


def expression_learning_content(**overrides):
    content = {
        "targetExpressionText": "I'm up for that",
        "baseExpressionMeaningText": "좋아, 그거 하자",
        "usageSummary": "제안에 동의할 때 사용",
        "usageDescription": "친근한 대화에서 제안을 흔쾌히 받아들일 때 사용합니다.",
        "representativeQuestionText": "Do you want to go hiking?",
        "representativeQuestionTranslation": "등산 갈래?",
        "representativeSentenceText": "I'm up for that.",
        "representativeSentenceTranslation": "좋아, 그거 하자.",
        "representativeSentenceWords": ["I'm", "up", "for", "that"],
        "representativeSentenceWordChoices": ["that", "I'm", "to", "up", "for"],
        "representativeImageUrl": None,
        "practiceExamples": [
            {
                "imageUrl": None,
                "sentenceText": "I'm up for trying that new cafe.",
                "sentenceWords": [
                    "I'm",
                    "up",
                    "for",
                    "trying",
                    "that",
                    "new",
                    "cafe",
                ],
                "highlightingPart": "I'm up for",
                "practiceQuestion": "Want to try that new cafe?",
                "sentenceTranslation": "그 새 카페 가보는 거 좋아.",
                "sentenceWordChoices": [
                    "new",
                    "trying",
                    "I'm",
                    "to",
                    "up",
                    "cafe",
                    "for",
                    "that",
                ],
                "practiceQuestionTranslation": "새 카페 가볼래?",
            }
            for _ in range(4)
        ],
    }
    content.update(overrides)
    return content


class FreeTalkApiTests(unittest.TestCase):
    def _app(self):
        return create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

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
            opening_completion(),
        )
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_opening_maps_blank_or_invalid_enum_llm_response_to_502(self):
        invalid_responses = (
            opening_completion(aiMessage="   "),
            opening_completion(emotion="EXCITED"),
        )

        for completion in invalid_responses:
            with self.subTest(completion=completion):
                response = self._post(
                    "/api/v1/free-talk/opening",
                    valid_opening_payload(),
                    FakeOpenAI(contents=[json.dumps(completion)]),
                )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_turn_normal_returns_real_derived_inner_thought_type(self):
        fake_openai = FakeOpenAI(contents=[json.dumps(normal_turn_completion())])
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["innerThoughtType"], "GOOD")
        self.assertEqual(
            response.json()["data"]["aiMessage"],
            "That sounds fun! Where are you going hiking?",
        )
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_turn_rejects_korean_or_english_feedback_style_inner_thought(self):
        prohibited_inner_thoughts = (
            "문법을 교정하면 더 자연스러워질 텐데.",
            "Your grammar needs correction and feedback.",
        )

        for inner_thought in prohibited_inner_thoughts:
            with self.subTest(inner_thought=inner_thought):
                response = self._post(
                    "/api/v1/free-talk/turn",
                    valid_turn_payload(),
                    FakeOpenAI(
                        contents=[
                            json.dumps(
                                normal_turn_completion(innerThought=inner_thought),
                            ),
                        ],
                    ),
                )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "AI_RESPONSE_INVALID",
                )

    def test_turn_requires_korean_inferred_title_on_first_user_turn(self):
        invalid_titles = (None, "Weekend 주말")

        for title in invalid_titles:
            with self.subTest(title=title):
                response = self._post(
                    "/api/v1/free-talk/turn",
                    valid_turn_payload(),
                    FakeOpenAI(
                        contents=[
                            json.dumps(normal_turn_completion(inferredTitle=title)),
                        ],
                    ),
                )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "AI_RESPONSE_INVALID",
                )

    def test_turn_rejects_inferred_title_after_first_user_turn(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(isFirstUserTurn=False),
            FakeOpenAI(contents=[json.dumps(normal_turn_completion())]),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

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
                            innerThought=None,
                            innerThoughtType=None,
                            answerCoverage=None,
                            relationshipTone=None,
                            directedAttack=None,
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
                "inferredTitle": "주말 등산 이야기",
                "aiMessage": None,
                "translatedMessage": None,
                "emotion": None,
                "innerThought": None,
                "innerThoughtType": None,
            },
        )

    def test_turn_rejects_generated_fields_when_exit_intent_is_detected(self):
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

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_turn_continue_after_exit_declined_skips_exit_rejudgment(self):
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
                            userExitIntentDetected=True,
                            inferredTitle=None,
                        ),
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["userExitIntentDetected"])
        self.assertIsNone(response.json()["data"]["inferredTitle"])

    def test_closing_supports_both_reasons_and_derives_inner_thought_type(self):
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
                self.assertEqual(response.json()["data"]["innerThoughtType"], "GOOD")
                self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_closing_rejects_question_form_message(self):
        response = self._post(
            "/api/v1/free-talk/closing",
            valid_closing_payload(),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        closing_completion(
                            aiMessage="Would you like to talk again?",
                        ),
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_closing_rejects_feedback_session_meta_or_new_topic_content(self):
        prohibited_messages = (
            "Please review your feedback.",
            "This session has ended.",
            "By the way, let's talk about movies next time.",
        )

        for message in prohibited_messages:
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

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "AI_RESPONSE_INVALID",
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

    def test_expression_recommendations_returns_one_or_three_recommendations(self):
        for count in (1, 3):
            with self.subTest(count=count):
                recommendations = [
                    expression_recommendation(displayOrder=index)
                    for index in range(1, count + 1)
                ]
                fake_openai = FakeOpenAI(
                    contents=[json.dumps({"recommendations": recommendations})],
                )

                response = self._post(
                    "/api/v1/free-talk/expression-recommendations",
                    valid_expression_recommendations_payload(),
                    fake_openai,
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()["data"]["recommendations"]), count)
                self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_expression_recommendations_supports_existing_and_new_sources(self):
        cases = (
            (
                expression_recommendation(),
                valid_expression_recommendations_payload(),
                "EXISTING",
            ),
            (
                expression_recommendation(
                    sourceType="NEW",
                    existingExpressionId=None,
                    targetExpressionText="I'm up for that",
                    baseExpressionMeaningText="좋아, 그거 하자",
                ),
                valid_expression_recommendations_payload(existingExpressions=[]),
                "NEW",
            ),
        )

        for recommendation, payload, source_type in cases:
            with self.subTest(source_type=source_type):
                response = self._post(
                    "/api/v1/free-talk/expression-recommendations",
                    payload,
                    FakeOpenAI(
                        contents=[json.dumps({"recommendations": [recommendation]})],
                    ),
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["data"]["recommendations"][0]["sourceType"],
                    source_type,
                )

    def test_expression_recommendations_rejects_unknown_existing_expression_id(self):
        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        {
                            "recommendations": [
                                expression_recommendation(existingExpressionId=999),
                            ],
                        },
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_expression_recommendations_rejects_changed_existing_expression_content(self):
        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        {
                            "recommendations": [
                                expression_recommendation(
                                    usageSummary="다른 표현의 용법 설명",
                                ),
                            ],
                        },
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_expression_recommendations_rejects_direct_feedback_language(self):
        prohibited_summaries = (
            "Your grammar is incorrect.",
            "Correct your grammar before using it.",
            "Your grammar is wrong; correct it this way.",
            "Your score is low.",
            "This is feedback on your mistakes.",
        )

        for usage_summary in prohibited_summaries:
            with self.subTest(usage_summary=usage_summary):
                response = self._post(
                    "/api/v1/free-talk/expression-recommendations",
                    valid_expression_recommendations_payload(existingExpressions=[]),
                    FakeOpenAI(
                        contents=[
                            json.dumps(
                                {
                                    "recommendations": [
                                        expression_recommendation(
                                            sourceType="NEW",
                                            existingExpressionId=None,
                                            usageSummary=usage_summary,
                                        ),
                                    ],
                                },
                            ),
                        ],
                    ),
                )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "AI_RESPONSE_INVALID",
                )

    def test_expression_recommendations_allows_natural_usage_description(self):
        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(existingExpressions=[]),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        {
                            "recommendations": [
                                expression_recommendation(
                                    sourceType="NEW",
                                    existingExpressionId=None,
                                    usageSummary="A natural way to enthusiastically agree.",
                                ),
                            ],
                        },
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)

    def test_expression_recommendations_allows_score_a_goal_expression(self):
        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(existingExpressions=[]),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        {
                            "recommendations": [
                                expression_recommendation(
                                    sourceType="NEW",
                                    existingExpressionId=None,
                                    targetExpressionText="score a goal",
                                    baseExpressionMeaningText="골을 넣다",
                                    usageSummary="Use it when talking about sports.",
                                ),
                            ],
                        },
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)

    def test_expression_recommendations_allows_feedback_request_expression(self):
        response = self._post(
            "/api/v1/free-talk/expression-recommendations",
            valid_expression_recommendations_payload(existingExpressions=[]),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        {
                            "recommendations": [
                                expression_recommendation(
                                    sourceType="NEW",
                                    existingExpressionId=None,
                                    targetExpressionText="I need your feedback",
                                    baseExpressionMeaningText="네 의견이 필요해",
                                    usageSummary="Use it to ask someone for their opinion.",
                                    contextualExample={
                                        "sentenceText": "I need your feedback on this plan.",
                                        "sentenceTranslation": "이 계획에 대한 네 의견이 필요해.",
                                    },
                                ),
                            ],
                        },
                    ),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)

    def test_expression_learning_content_returns_complete_text_only_content(self):
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(
                    {"expressions": [expression_learning_content()]},
                ),
            ],
        )
        response = self._post(
            "/api/v1/free-talk/expression-learning-content",
            valid_expression_learning_content_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 200)
        content = response.json()["data"]["expressions"][0]
        self.assertIsNone(content["representativeImageUrl"])
        self.assertEqual(len(content["practiceExamples"]), 4)
        self.assertTrue(
            all(example["imageUrl"] is None for example in content["practiceExamples"]),
        )
        self.assertIn(
            "expressions in the input order",
            fake_openai.completions.calls[0]["messages"][0]["content"],
        )

    def test_expression_learning_content_rejects_invalid_response_without_retry(self):
        invalid_content = expression_learning_content()
        invalid_content["practiceExamples"] = invalid_content["practiceExamples"][:3]
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps({"expressions": [invalid_content]}),
            ],
        )

        response = self._post(
            "/api/v1/free-talk/expression-learning-content",
            valid_expression_learning_content_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_invalid_ai_response_without_message_is_not_rendered_as_none(self):
        self.assertEqual(str(AiResponseInvalidError()), "")

    def test_expression_learning_content_rejects_invalid_json_without_retry(self):
        fake_openai = FakeOpenAI(
            contents=["not json"],
        )

        response = self._post(
            "/api/v1/free-talk/expression-learning-content",
            valid_expression_learning_content_payload(),
            fake_openai,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_expression_learning_content_maps_generation_failure_to_503(self):
        response = self._post(
            "/api/v1/free-talk/expression-learning-content",
            valid_expression_learning_content_payload(),
            FakeOpenAI(error=RuntimeError("provider unavailable")),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")

    def test_sdk_failure_maps_to_generation_failed(self):
        response = self._post(
            "/api/v1/free-talk/opening",
            valid_opening_payload(),
            FakeOpenAI(error=RuntimeError("provider unavailable")),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")

    def test_invalid_json_contract_maps_to_response_invalid(self):
        response = self._post(
            "/api/v1/free-talk/turn",
            valid_turn_payload(),
            FakeOpenAI(contents=["not json"]),
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_openapi_exposes_all_free_talk_generation_routes(self):
        paths = self._app().openapi()["paths"]

        for path in (
            "/api/v1/free-talk/opening",
            "/api/v1/free-talk/turn",
            "/api/v1/free-talk/closing",
            "/api/v1/free-talk/expression-recommendations",
            "/api/v1/free-talk/expression-learning-content",
        ):
            with self.subTest(path=path):
                self.assertIn(path, paths)
