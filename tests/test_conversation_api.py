# 다음 AI 메시지 생성 API의 HTTP 계약을 검증하는 unittest 모듈
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


def valid_next_message_payload():
    return {
        "sessionId": 100,
        "submittedMessageId": 1001,
        "submittedTurnNumber": 1,
        "scenario": {
            "scenarioId": 10,
            "title": "음식에 대한 대화하기",
            "briefing": "좋아하는 음식과 최근에 먹은 음식에 대해 이야기합니다.",
            "conversationGoal": "내 취향과 경험을 영어로 설명해봅니다.",
            "counterpartRole": "friend",
            "serviceAudience": "KOREAN_LEARNER",
        },
        "conversationHistory": [
            {
                "messageId": 1000,
                "turnNumber": 1,
                "role": "AI",
                "content": "What food do you like? Why do you like it?",
                "translatedContent": "좋아하는 음식이 있어? 왜 좋아해?",
            },
            {
                "messageId": 1001,
                "turnNumber": 1,
                "role": "USER",
                "content": "I like pizza because it is spicy.",
                "translatedContent": None,
            },
        ],
        "nextQuestion": {
            "questionId": 2000,
            "sequence": 2,
            "questionEn": "Do you cook often?",
            "questionKo": "요리는 자주 해?",
        },
    }


def valid_closing_message_payload():
    return {
        "sessionId": 100,
        "submittedMessageId": 1007,
        "submittedTurnNumber": 4,
        "scenario": {
            "scenarioId": 10,
            "title": "기숙사에서 조용히 해달라고 말하기",
            "briefing": "룸메이트에게 밤에 조용히 해달라고 말하는 상황입니다.",
            "conversationGoal": "불편함을 공격적이지 않게 전달하고 조용히 해달라고 요청합니다.",
            "counterpartRole": "roommate",
            "serviceAudience": "KOREAN_LEARNER",
        },
        "conversationHistory": [
            {
                "messageId": 1006,
                "turnNumber": 4,
                "role": "AI",
                "content": "What do you want me to do?",
                "translatedContent": "내가 어떻게 해주면 좋겠어?",
            },
            {
                "messageId": 1007,
                "turnNumber": 4,
                "role": "USER",
                "content": "Could you keep it down at night? I have an early class tomorrow.",
                "translatedContent": None,
            },
        ],
        "closingReason": "GOAL_COMPLETED",
        "goalCompletionStatus": "COMPLETED",
    }


class FakeCompletions:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                ),
            ],
        )


class FakeOpenAI:
    def __init__(self, content=None, error=None):
        self.completions = FakeCompletions(content=content, error=error)
        self.chat = SimpleNamespace(completions=self.completions)


class NextMessageApiTests(unittest.TestCase):
    def test_next_message_returns_ai_message_and_uses_fixed_question_prompt(self):
        ai_response = {
            "aiMessage": "Sounds tasty. Do you cook often?",
            "translatedMessage": "맛있겠다. 요리는 자주 해?",
            "innerThought": "매운 피자를 좋아한다고 이유까지 말해주네. 대화하기 편하다.",
            "innerThoughtType": "GOOD",
            "goalCompletionStatus": "PARTIAL",
        }
        fake_openai = FakeOpenAI(content=json.dumps(ai_response))
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/next-message",
                json=valid_next_message_payload(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "data": ai_response,
                "error": None,
            },
        )
        self.assertEqual(fake_openai.completions.kwargs["model"], "openrouter-test-model")
        messages = fake_openai.completions.kwargs["messages"]
        self.assertIn("Counterpart role: friend", messages[1]["content"])
        self.assertIn(
            "Scenario conversation goal: 내 취향과 경험을 영어로 설명해봅니다.",
            messages[1]["content"],
        )
        self.assertIn(
            "AI turn 1 message 1000: What food do you like? Why do you like it?",
            messages[1]["content"],
        )
        self.assertIn(
            "USER turn 1 message 1001: I like pizza because it is spicy.",
            messages[1]["content"],
        )
        self.assertIn("Next fixed question ID: 2000", messages[1]["content"])
        self.assertIn("Next fixed question sequence: 2", messages[1]["content"])
        self.assertIn(
            "Next fixed question English: Do you cook often?",
            messages[1]["content"],
        )
        self.assertIn(
            "Next fixed question Korean: 요리는 자주 해?",
            messages[1]["content"],
        )
        self.assertIn(
            "Use the provided next fixed question as the question part of aiMessage.",
            messages[0]["content"],
        )

    def test_next_message_invalid_ai_response_returns_502(self):
        fake_openai = FakeOpenAI(content='{"aiMessage":"Only one field"}')
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/next-message",
                json=valid_next_message_payload(),
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "AI_RESPONSE_INVALID",
                    "message": "AI 응답 형식이 올바르지 않습니다.",
                },
            },
        )

    def test_next_message_without_fixed_question_returns_502(self):
        fake_openai = FakeOpenAI(
            content=json.dumps(
                {
                    "aiMessage": "Sounds tasty. What else do you like?",
                    "translatedMessage": "맛있겠다. 또 뭘 좋아해?",
                    "innerThought": "매운 피자를 좋아한다고 이유까지 말해주네.",
                    "innerThoughtType": "GOOD",
                    "goalCompletionStatus": "PARTIAL",
                },
            ),
        )
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/next-message",
                json=valid_next_message_payload(),
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_next_message_generation_failure_returns_503(self):
        fake_openai = FakeOpenAI(error=RuntimeError("network failed"))
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/next-message",
                json=valid_next_message_payload(),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "AI_GENERATION_FAILED",
                    "message": "AI 응답 생성에 실패했습니다.",
                },
            },
        )

    def test_next_message_rejects_mismatched_submitted_history(self):
        payload = valid_next_message_payload()
        payload["submittedMessageId"] = 9999
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/next-message",
                json=payload,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        openai_class.assert_not_called()

    def test_closing_message_returns_final_ai_message_and_prompt_context(self):
        ai_response = {
            "aiMessage": "Sure, I'll keep it down tonight. Good luck with your class tomorrow.",
            "translatedMessage": "물론이야, 오늘 밤은 조용히 할게. 내일 수업 잘 다녀와.",
            "innerThought": "정중하게 부탁했네. 상황도 분명해서 바로 맞춰주면 되겠다.",
            "innerThoughtType": "GOOD",
        }
        fake_openai = FakeOpenAI(content=json.dumps(ai_response))
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/closing-message",
                json=valid_closing_message_payload(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "data": ai_response,
                "error": None,
            },
        )
        messages = fake_openai.completions.kwargs["messages"]
        self.assertIn("Do not ask a new follow-up question.", messages[0]["content"])
        self.assertIn("Closing reason: GOAL_COMPLETED", messages[1]["content"])
        self.assertIn("Goal completion status: COMPLETED", messages[1]["content"])
        self.assertIn("Counterpart role: roommate", messages[1]["content"])
        self.assertIn("Last AI message: AI turn 4 message 1006", messages[1]["content"])
        self.assertIn("Last user message: USER turn 4 message 1007", messages[1]["content"])
        self.assertIn(
            "USER turn 4 message 1007: Could you keep it down at night?",
            messages[1]["content"],
        )

    def test_closing_message_tail_question_returns_502(self):
        fake_openai = FakeOpenAI(
            content=json.dumps(
                {
                    "aiMessage": "Sure, I'll keep it down tonight. Anything else?",
                    "translatedMessage": "물론이야, 오늘 밤은 조용히 할게. 또 필요한 거 있어?",
                    "innerThought": "정중하게 부탁했네.",
                    "innerThoughtType": "GOOD",
                },
            ),
        )
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/closing-message",
                json=valid_closing_message_payload(),
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_closing_message_invalid_ai_response_returns_502(self):
        fake_openai = FakeOpenAI(content='{"aiMessage":"Only one field"}')
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/closing-message",
                json=valid_closing_message_payload(),
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_closing_message_generation_failure_returns_503(self):
        fake_openai = FakeOpenAI(error=RuntimeError("network failed"))
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/closing-message",
                json=valid_closing_message_payload(),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "AI_GENERATION_FAILED",
                    "message": "대화 종료 메시지 생성에 실패했습니다.",
                },
            },
        )

    def test_closing_message_rejects_mismatched_submitted_history(self):
        payload = valid_closing_message_payload()
        payload["submittedMessageId"] = 9999
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/closing-message",
                json=payload,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        openai_class.assert_not_called()
