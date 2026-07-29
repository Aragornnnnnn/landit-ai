# 프리톡 대화 생성 API의 HTTP 계약을 검증하는 unittest 모듈
import json
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import Settings
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
    }
    result.update(overrides)
    return result


def closing_completion(**overrides):
    result = {
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
        self.assertEqual(len(fake_openai.completions.calls), 1)

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

    def test_turn_rejects_korean_or_english_feedback_style_inner_thought(self):
        prohibited_inner_thoughts = (
            "문법을 교정하면 더 자연스러워질 텐데.",
            "Your grammar needs correction and feedback.",
        )

        for inner_thought in prohibited_inner_thoughts:
            with self.subTest(inner_thought=inner_thought):
                response = self._post(
                    "/api/v1/free-talk/inner-thought",
                    valid_inner_thought_payload(),
                    FakeOpenAI(
                        contents=[
                            json.dumps(
                                inner_thought_completion(innerThought=inner_thought),
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
        invalid_titles = (None, "Weekend 주말", "123")

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
                self.assertEqual(len(fake_openai.completions.calls), 1)

    def test_closing_rejects_question_form_message(self):
        question_messages = (
            "Would you like to talk again?",
            "Would you like to talk again? 😊",
        )

        for message in question_messages:
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
                    response.json()["error"]["code"], "AI_RESPONSE_INVALID"
                )

    def test_closing_rejects_feedback_style_inner_thought(self):
        response = self._post(
            "/api/v1/free-talk/inner-thought",
            valid_inner_thought_payload(),
            FakeOpenAI(
                contents=[
                    json.dumps(
                        inner_thought_completion(
                            innerThought="문법을 교정하면 더 자연스러워질 텐데.",
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

    def test_openapi_exposes_all_free_talk_generation_routes(self):
        paths = self._app().openapi()["paths"]

        for path in (
            "/api/v1/free-talk/opening",
            "/api/v1/free-talk/turn",
            "/api/v1/free-talk/inner-thought",
            "/api/v1/free-talk/closing",
        ):
            with self.subTest(path=path):
                self.assertIn(path, paths)
