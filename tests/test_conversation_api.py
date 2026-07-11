# 대화 생성 API의 HTTP 계약을 검증하는 unittest 모듈
import json
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

from app.conversation.application.next_message_service import (
    MessageFeedbackNotReadyError,
    clear_message_feedback_cache,
    get_cached_message_feedback,
    get_expected_message_feedbacks,
)
from app.core.config import Settings
from app.main import create_app
from app.models.conversation import FeedbackStatus, MessageFeedbackRequest


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


def valid_message_feedback_payload():
    return {
        "sessionId": 100,
        "messageId": 1001,
        "turnNumber": 1,
        "messageSequence": 2,
        "scenario": {
            "scenarioId": 10,
            "title": "음식에 대한 대화하기",
            "briefing": "좋아하는 음식과 최근에 먹은 음식에 대해 이야기합니다.",
            "conversationGoal": "내 취향과 경험을 영어로 설명해봅니다.",
            "counterpartRole": "friend",
            "serviceAudience": "KOREAN_LEARNER",
        },
        "evaluationContext": {
            "type": "AI_MESSAGE",
            "content": "What food do you like? Why do you like it?",
            "translatedContent": "좋아하는 음식이 있어? 왜 좋아해?",
        },
        "userMessage": "why do you wanna know that?",
    }


def valid_opening_message_feedback_payload():
    return {
        "sessionId": 100,
        "messageId": 1001,
        "turnNumber": 1,
        "messageSequence": 1,
        "scenario": {
            "scenarioId": 10,
            "title": "카페에서 음료 주문하기",
            "briefing": "카페 점원에게 원하는 음료를 주문합니다.",
            "conversationGoal": "원하는 음료를 자연스럽고 공손하게 주문합니다.",
            "counterpartRole": "cafe staff",
            "serviceAudience": "KOREAN_LEARNER",
        },
        "evaluationContext": {
            "type": "SCENARIO_OPENING_INSTRUCTION",
            "content": "점원에게 먼저 주문하고 싶은 음료를 말해보세요.",
            "translatedContent": None,
        },
        "userMessage": "Can I get an iced americano?",
    }


def valid_session_feedback_payload():
    return {
        "sessionId": 100,
        "scenario": {
            "scenarioId": 10,
            "title": "음식에 대한 대화하기",
            "briefing": "좋아하는 음식과 최근에 먹은 음식에 대해 이야기합니다.",
            "conversationGoal": "내 취향과 경험을 영어로 설명해봅니다.",
            "counterpartRole": "friend",
            "serviceAudience": "KOREAN_LEARNER",
        },
        "expectedMessageIds": [1001, 1003],
    }


def good_message_feedback(message_id=1001):
    return {
        "messageId": message_id,
        "feedbackType": "GOOD",
        "baseLocaleAnalogy": '"피자를 좋아해요. 매워서요"라고 이유를 바로 붙여 말하는 것과 같아요.',
        "positiveFeedback": None,
        "feedbackDetail": "좋아하는 음식과 이유를 because로 자연스럽게 연결했어요.",
        "correctionExpression": None,
        "correctionReason": None,
        "benchmarkMessage": "한국인의 23%가 놓치는 이유 연결을 챙긴 사람.",
    }


def needs_improvement_message_feedback(message_id=1003):
    return {
        "messageId": message_id,
        "feedbackType": "NEEDS_IMPROVEMENT",
        "baseLocaleAnalogy": '"그걸 왜 알고 싶은데?"라고 살짝 방어적으로 되묻는 것과 같아요.',
        "positiveFeedback": "상대의 질문 의도를 확인하려고 한 시도는 좋아요.",
        "feedbackDetail": None,
        "correctionExpression": "I was just curious why you asked.",
        "correctionReason": "why do you wanna know that?은 상황에 따라 따지는 느낌으로 들릴 수 있어요.",
        "benchmarkMessage": None,
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


class MessageFeedbackApiTests(unittest.TestCase):
    def setUp(self):
        clear_message_feedback_cache()

    def test_feedback_status_uses_frontend_contract_values(self):
        self.assertEqual(
            {status.value for status in FeedbackStatus},
            {"PREPARING", "COMPLETED", "FAILED"},
        )

    def test_message_feedback_generates_feedback_and_returns_preparing(self):
        ai_response = {
            "messageId": 1001,
            "feedbackType": "NEEDS_IMPROVEMENT",
            "baseLocaleAnalogy": '"그걸 왜 알고 싶은데?"라고 살짝 방어적으로 되묻는 것과 같아요.',
            "positiveFeedback": "상대의 질문 의도를 확인하려고 한 시도는 좋아요.",
            "feedbackDetail": None,
            "correctionExpression": "I was just curious why you asked.",
            "correctionReason": "why do you wanna know that?은 상황에 따라 따지는 느낌으로 들릴 수 있어요.",
            "benchmarkMessage": None,
            "detectedPatterns": [],
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
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "data": {
                    "sessionId": 100,
                    "messageId": 1001,
                    "feedbackStatus": "PREPARING",
                },
                "error": None,
            },
        )
        messages = fake_openai.completions.kwargs["messages"]
        self.assertIn("AI_MESSAGE Policy", messages[0]["content"])
        self.assertIn(
            "Relevance to the AI message is an actionable issue",
            messages[0]["content"],
        )
        self.assertNotIn("SCENARIO_OPENING_INSTRUCTION Policy", messages[0]["content"])
        self.assertIn("AI_MESSAGE Feedback Examples", messages[0]["content"])
        self.assertIn("Why do you wanna know that?", messages[0]["content"])
        self.assertNotIn(
            "SCENARIO_OPENING_INSTRUCTION Feedback Examples",
            messages[0]["content"],
        )
        self.assertNotIn("I like soccer.", messages[0]["content"])
        self.assertIn("Counterpart role: friend", messages[1]["content"])
        self.assertIn("Message ID: 1001", messages[1]["content"])
        self.assertIn("Message sequence: 2", messages[1]["content"])
        self.assertIn(
            "User utterance: why do you wanna know that?",
            messages[1]["content"],
        )
        self.assertIn("baseLocaleAnalogy", messages[0]["content"])
        cached_feedback = get_cached_message_feedback(100, 1001)
        self.assertIsNotNone(cached_feedback)
        self.assertEqual(cached_feedback.feedbackType, "NEEDS_IMPROVEMENT")
        self.assertEqual(
            cached_feedback.correctionExpression,
            "I was just curious why you asked.",
        )

    def test_message_feedback_accepts_user_opening_instruction(self):
        ai_response = {
            "messageId": 1001,
            "feedbackType": "GOOD",
            "baseLocaleAnalogy": '"아이스 아메리카노 한 잔 주세요"라고 자연스럽게 주문하는 것과 같아요.',
            "positiveFeedback": None,
            "feedbackDetail": "원하는 음료를 공손하게 주문해서 점원이 바로 이해할 수 있어요.",
            "correctionExpression": None,
            "correctionReason": None,
            "benchmarkMessage": None,
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
                "/api/v1/conversation/message-feedback",
                json=valid_opening_message_feedback_payload(),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["data"]["feedbackStatus"], "PREPARING")
        messages = fake_openai.completions.kwargs["messages"]
        self.assertIn(
            "SCENARIO_OPENING_INSTRUCTION Policy",
            messages[0]["content"],
        )
        self.assertIn(
            "Opening instruction fulfillment is an actionable issue",
            messages[0]["content"],
        )
        self.assertNotIn("AI_MESSAGE Policy", messages[0]["content"])
        self.assertIn(
            "SCENARIO_OPENING_INSTRUCTION Feedback Examples",
            messages[0]["content"],
        )
        self.assertIn("I like soccer.", messages[0]["content"])
        self.assertNotIn("AI_MESSAGE Feedback Examples", messages[0]["content"])
        self.assertNotIn("Why do you wanna know that?", messages[0]["content"])
        self.assertIn(
            "Evaluation context type: SCENARIO_OPENING_INSTRUCTION",
            messages[1]["content"],
        )
        self.assertIn(
            "점원에게 먼저 주문하고 싶은 음료를 말해보세요.",
            messages[1]["content"],
        )
        self.assertIn("Counterpart role: cafe staff", messages[1]["content"])
        self.assertIn("Can I get an iced americano?", messages[1]["content"])

    def test_opening_instruction_rejects_turn_after_first_turn(self):
        payload = valid_opening_message_feedback_payload()
        payload["turnNumber"] = 2
        app = create_app(make_settings())

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=payload,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        openai_class.assert_not_called()

    def test_opening_instruction_does_not_require_fixed_message_sequence(self):
        payload = valid_opening_message_feedback_payload()
        payload["messageSequence"] = 5

        request = MessageFeedbackRequest.model_validate(payload)

        self.assertEqual(request.messageSequence, 5)

    def test_opening_instruction_rejects_translated_content(self):
        payload = valid_opening_message_feedback_payload()
        payload["evaluationContext"]["translatedContent"] = "Order a drink first."
        app = create_app(make_settings())

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=payload,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        openai_class.assert_not_called()

    def test_message_feedback_openapi_uses_evaluation_context_contract(self):
        schemas = create_app(make_settings()).openapi()["components"]["schemas"]
        request_schema = schemas["MessageFeedbackRequest"]

        self.assertIn("evaluationContext", request_schema["properties"])
        self.assertIn("userMessage", request_schema["properties"])
        self.assertNotIn("messageContext", request_schema["properties"])
        self.assertEqual(
            schemas["EvaluationContextType"]["enum"],
            ["AI_MESSAGE", "SCENARIO_OPENING_INSTRUCTION"],
        )

    def test_message_feedback_generates_and_caches_good_feedback(self):
        ai_response = {
            "messageId": 1001,
            "feedbackType": "GOOD",
            "baseLocaleAnalogy": '"피자를 좋아해요. 매워서요"라고 이유를 바로 붙여 말하는 것과 같아요.',
            "positiveFeedback": None,
            "feedbackDetail": "좋아하는 음식과 이유를 because로 자연스럽게 연결했어요.",
            "correctionExpression": None,
            "correctionReason": None,
            "benchmarkMessage": "이유를 자연스럽게 붙여 말했어요.",
            "detectedPatterns": [
                {
                    "errorType": "because_clause",
                    "status": "correct",
                    "evidence": "because it is spicy",
                },
            ],
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
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
            )

        self.assertEqual(response.status_code, 202)
        cached_feedback = get_cached_message_feedback(100, 1001)
        self.assertIsNotNone(cached_feedback)
        self.assertEqual(cached_feedback.feedbackType, "GOOD")
        self.assertIsNone(cached_feedback.positiveFeedback)
        self.assertIsNone(cached_feedback.correctionExpression)
        self.assertEqual(
            get_expected_message_feedbacks(100, [1001]),
            [cached_feedback],
        )

    def test_message_feedback_invalid_ai_response_returns_502(self):
        fake_openai = FakeOpenAI(
            content=json.dumps(
                {
                    "messageId": 1001,
                    "feedbackType": "NEEDS_IMPROVEMENT",
                    "baseLocaleAnalogy": '"그걸 왜 알고 싶은데?"라고 살짝 방어적으로 되묻는 것과 같아요.',
                    "positiveFeedback": "상대의 질문 의도를 확인하려고 한 시도는 좋아요.",
                    "feedbackDetail": None,
                    "correctionExpression": None,
                    "correctionReason": "상황에 따라 따지는 느낌으로 들릴 수 있어요.",
                    "benchmarkMessage": None,
                    "detectedPatterns": [],
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
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertIsNone(get_cached_message_feedback(100, 1001))

    def test_message_feedback_mismatched_message_id_returns_502(self):
        ai_response = {
            "messageId": 9999,
            "feedbackType": "GOOD",
            "baseLocaleAnalogy": '"피자를 좋아해요. 매워서요"라고 이유를 바로 붙여 말하는 것과 같아요.',
            "positiveFeedback": None,
            "feedbackDetail": "좋아하는 음식과 이유를 because로 자연스럽게 연결했어요.",
            "correctionExpression": None,
            "correctionReason": None,
            "benchmarkMessage": None,
            "detectedPatterns": [],
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
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_message_feedback_generation_failure_returns_503(self):
        fake_openai = FakeOpenAI(error=RuntimeError("network failed"))
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
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

    def test_message_feedback_missing_model_returns_503(self):
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model=None,
            ),
        )

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")
        openai_class.assert_not_called()

    def test_message_feedback_cache_expires_and_reports_missing_entries(self):
        ai_response = {
            "messageId": 1001,
            "feedbackType": "GOOD",
            "baseLocaleAnalogy": '"피자를 좋아해요. 매워서요"라고 이유를 바로 붙여 말하는 것과 같아요.',
            "positiveFeedback": None,
            "feedbackDetail": "좋아하는 음식과 이유를 because로 자연스럽게 연결했어요.",
            "correctionExpression": None,
            "correctionReason": None,
            "benchmarkMessage": None,
            "detectedPatterns": [],
        }
        fake_openai = FakeOpenAI(content=json.dumps(ai_response))
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with (
            patch("app.core.openai_client.OpenAI", return_value=fake_openai),
            patch(
                "app.conversation.application.next_message_service._cache_now",
                return_value=100.0,
            ),
        ):
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
            )

        self.assertEqual(response.status_code, 202)
        self.assertIsNotNone(get_cached_message_feedback(100, 1001, now=100.0))
        self.assertIsNone(get_cached_message_feedback(100, 1001, now=10901.0))
        with self.assertRaises(MessageFeedbackNotReadyError) as context:
            get_expected_message_feedbacks(100, [1001], now=10901.0)
        self.assertEqual(context.exception.missing_message_ids, [1001])


class SessionFeedbackApiTests(unittest.TestCase):
    def setUp(self):
        clear_message_feedback_cache()

    def _app(self):
        return create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

    def _cache_feedback(self, app, feedback, *, user_message=None):
        payload = valid_message_feedback_payload()
        payload["messageId"] = feedback["messageId"]
        if user_message is not None:
            payload["userMessage"] = user_message
        fake_openai = FakeOpenAI(content=json.dumps(feedback))
        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=payload,
            )
        self.assertEqual(response.status_code, 202)

    def test_session_feedback_returns_summary_score_star_and_cached_feedbacks(self):
        app = self._app()
        self._cache_feedback(
            app,
            good_message_feedback(1001),
            user_message="I like pizza because it is spicy.",
        )
        self._cache_feedback(
            app,
            needs_improvement_message_feedback(1003),
            user_message="why do you wanna know that?",
        )
        ai_response = {
            "sessionId": 100,
            "highlightMessage": "한국인의 23%가 놓치는 이유 연결을 챙긴 사람.",
            "summaryMessage": "전체적으로 의도 전달이 명확했고 이유를 덧붙이려는 점이 좋았어요.",
            "nativeScore": 100,
            "starRating": 3.0,
            "messageFeedbacks": [],
        }
        fake_openai = FakeOpenAI(content=json.dumps(ai_response))

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/session-feedback",
                json=valid_session_feedback_payload(),
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["success"], True)
        self.assertIsNone(body["error"])
        self.assertEqual(body["data"]["sessionId"], 100)
        self.assertEqual(body["data"]["nativeScore"], 64)
        self.assertEqual(body["data"]["starRating"], 1.5)
        self.assertEqual(
            body["data"]["highlightMessage"],
            "한국인의 23%가 놓치는 이유 연결을 챙긴 사람.",
        )
        self.assertEqual(
            body["data"]["summaryMessage"],
            "전체적으로 의도 전달이 명확했고 이유를 덧붙이려는 점이 좋았어요.",
        )
        self.assertEqual(
            [feedback["messageId"] for feedback in body["data"]["messageFeedbacks"]],
            [1001, 1003],
        )
        self.assertEqual(
            body["data"]["messageFeedbacks"][0]["feedbackType"],
            "GOOD",
        )
        self.assertEqual(
            body["data"]["messageFeedbacks"][1]["correctionExpression"],
            "I was just curious why you asked.",
        )
        self.assertIsNone(get_cached_message_feedback(100, 1001))
        self.assertIsNone(get_cached_message_feedback(100, 1003))
        messages = fake_openai.completions.kwargs["messages"]
        self.assertIn("Session ID: 100", messages[1]["content"])
        self.assertIn("Expected message IDs: [1001, 1003]", messages[1]["content"])
        self.assertIn("Cached message feedback counts: GOOD=1, NEEDS_IMPROVEMENT=1", messages[1]["content"])
        self.assertIn("summaryMessage", messages[0]["content"])

    def test_session_feedback_rejects_invalid_expected_message_ids(self):
        payload = valid_session_feedback_payload()
        payload["expectedMessageIds"] = [1001, 1001]
        app = self._app()

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/session-feedback",
                json=payload,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        openai_class.assert_not_called()

    def test_session_feedback_not_ready_returns_409_without_missing_ids(self):
        app = self._app()

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/session-feedback",
                json=valid_session_feedback_payload(),
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "MESSAGE_FEEDBACK_NOT_READY",
                    "message": "메시지별 피드백이 아직 준비되지 않았습니다.",
                },
            },
        )
        self.assertNotIn("missingMessageIds", response.text)
        openai_class.assert_not_called()

    def test_session_feedback_invalid_ai_response_returns_502_and_preserves_cache(self):
        app = self._app()
        self._cache_feedback(app, good_message_feedback(1001))
        payload = valid_session_feedback_payload()
        payload["expectedMessageIds"] = [1001]
        fake_openai = FakeOpenAI(
            content=json.dumps(
                {
                    "sessionId": 100,
                    "highlightMessage": "한국인의 23%가 놓치는 이유 연결을 챙긴 사람.",
                },
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/session-feedback",
                json=payload,
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
        self.assertIsNotNone(get_cached_message_feedback(100, 1001))

    def test_session_feedback_generation_failure_returns_503_and_preserves_cache(self):
        app = self._app()
        self._cache_feedback(app, good_message_feedback(1001))
        payload = valid_session_feedback_payload()
        payload["expectedMessageIds"] = [1001]
        fake_openai = FakeOpenAI(error=RuntimeError("network failed"))

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/session-feedback",
                json=payload,
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")
        self.assertEqual(
            response.json()["error"]["message"],
            "세션 최종 피드백 생성에 실패했습니다.",
        )
        self.assertIsNotNone(get_cached_message_feedback(100, 1001))

    def test_session_feedback_missing_model_returns_503_and_preserves_cache(self):
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )
        self._cache_feedback(app, good_message_feedback(1001))
        app.state.settings = make_settings(
            openrouter_api_key="test-openrouter-key",
            openrouter_model=None,
        )
        payload = valid_session_feedback_payload()
        payload["expectedMessageIds"] = [1001]

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/session-feedback",
                json=payload,
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")
        self.assertIsNotNone(get_cached_message_feedback(100, 1001))
        openai_class.assert_not_called()


class ClosingMessageApiTests(unittest.TestCase):
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
