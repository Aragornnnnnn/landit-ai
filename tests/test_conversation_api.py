# 대화 생성 API의 HTTP 계약을 검증하는 unittest 모듈
import json
import re
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

from app.conversation.application import next_message_service
from app.conversation.application.next_message_service import (
    MessageFeedbackNotReadyError,
    clear_message_feedback_cache,
    get_cached_message_feedback,
    get_expected_message_feedbacks,
)
from app.core.config import Settings
from app.main import create_app
from app.models import conversation as conversation_models
from app.models.conversation import (
    EvaluationContextType,
    FeedbackStatus,
    MessageFeedbackRequest,
)


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


def valid_inner_thought_payload():
    payload = valid_next_message_payload()
    payload.pop("nextQuestion")
    return payload


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
            "title": "친구에게 이유 묻기",
            "briefing": "친구가 개인 정보를 물어보는 상황입니다.",
            "conversationGoal": "개인 정보가 필요한 이유를 자연스럽게 확인합니다.",
            "counterpartRole": "friend",
            "serviceAudience": "KOREAN_LEARNER",
        },
        "evaluationContext": {
            "type": "AI_MESSAGE",
            "content": "Can I have your phone number?",
            "translatedContent": "전화번호 좀 알려줄래?",
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
        "scoreEvidence": {
            "contextFit": 2,
            "clarity": 2,
            "languageAccuracy": 2,
        },
        "baseLocaleAnalogy": '"피자를 좋아해요. 매워서요"라고 이유를 바로 붙여 말하는 것과 같아요.',
        "positiveFeedback": None,
        "feedbackDetail": "좋아하는 음식과 이유를 because로 자연스럽게 연결했어요.",
        "correctionExpression": None,
        "correctionReason": None,
        "benchmarkMessage": "이유를 자연스럽게 붙여 말했어요.",
    }


def needs_improvement_message_feedback(message_id=1003):
    return {
        "messageId": message_id,
        "feedbackType": "NEEDS_IMPROVEMENT",
        "scoreEvidence": {
            "contextFit": 2,
            "clarity": 2,
            "languageAccuracy": 1,
        },
        "baseLocaleAnalogy": '"피자를 좋아해요. 매워서"라고 이유를 끝맺지 못한 것과 같아요.',
        "positiveFeedback": "좋아하는 음식과 이유를 함께 말하려는 시도는 좋아요.",
        "feedbackDetail": None,
        "correctionExpression": "I like pizza because it is spicy.",
        "correctionReason": "because 뒤에 주어와 동사가 있는 절을 붙이면 이유가 완전하게 전달돼요.",
        "benchmarkMessage": None,
    }


def message_feedback_candidate(feedback):
    candidate = dict(feedback)
    candidate.pop("messageId", None)
    candidate.pop("feedbackType", None)
    return candidate


def message_feedback_copy(feedback):
    copy = message_feedback_candidate(feedback)
    copy.pop("scoreEvidence", None)
    return copy


def partial_hobby_feedback(message_id=1001):
    return {
        "messageId": message_id,
        "feedbackType": "NEEDS_IMPROVEMENT",
        "scoreEvidence": {
            "contextFit": 1,
            "clarity": 2,
            "languageAccuracy": 2,
        },
        "baseLocaleAnalogy": '"조깅은 좋아하지만 왜 좋은지는 말 안 할게"라고 일부만 답하는 것과 같아요.',
        "positiveFeedback": "좋아하는 활동을 분명하게 말했어요.",
        "feedbackDetail": None,
        "correctionExpression": "I like jogging because [your reason].",
        "correctionReason": "좋아하는 활동에는 답했지만 이유가 빠졌어요. [your reason]에 조깅을 좋아하는 이유를 넣어 보세요.",
        "benchmarkMessage": None,
    }



def message_feedback_responses(feedback, user_message):
    del user_message
    candidate = dict(feedback)
    candidate.pop("messageId", None)
    candidate.pop("feedbackType", None)
    copy = dict(candidate)
    copy.pop("scoreEvidence", None)
    return [json.dumps(candidate), json.dumps(copy)]


def multiple_hobby_questions_payload():
    payload = valid_message_feedback_payload()
    payload["evaluationContext"] = {
        "type": "AI_MESSAGE",
        "content": "What are you into? What do you love about it?",
        "translatedContent": "무엇을 좋아해? 그것의 어떤 점이 좋아?",
    }
    payload["userMessage"] = "I like jogging."
    return payload


class FakeCompletions:
    def __init__(
        self,
        content=None,
        error=None,
        *,
        contents=None,
        errors=None,
        message_feedback=None,
    ):
        self.contents = list(contents) if contents is not None else [content]
        self.errors = list(errors) if errors is not None else [error]
        self.message_feedback = message_feedback
        self.kwargs = None
        self.calls = []

    def create(self, **kwargs):
        self.kwargs = kwargs
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        error = self.errors[index] if index < len(self.errors) else None
        if error is not None:
            raise error
        if self.message_feedback is not None:
            user_prompt = kwargs["messages"][1]["content"]
            user_message = user_prompt.rsplit(
                "User utterance: ",
                maxsplit=1,
            )[-1].splitlines()[0]
            feedback_contents = message_feedback_responses(
                self.message_feedback,
                user_message,
            )
            content = feedback_contents[min(index, len(feedback_contents) - 1)]
        else:
            content = self.contents[index] if index < len(self.contents) else self.contents[-1]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                ),
            ],
        )


class FakeOpenAI:
    def __init__(
        self,
        content=None,
        error=None,
        *,
        contents=None,
        errors=None,
        message_feedback=None,
    ):
        self.completions = FakeCompletions(
            content=content,
            error=error,
            contents=contents,
            errors=errors,
            message_feedback=message_feedback,
        )
        self.chat = SimpleNamespace(completions=self.completions)


class NextMessageApiTests(unittest.TestCase):
    def test_next_message_returns_ai_message_and_uses_fixed_question_prompt(self):
        ai_response = {
            "aiMessage": "Sounds tasty. Do you cook often?",
            "translatedMessage": "맛있겠다. 요리는 자주 해?",
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
        self.assertNotIn("innerThought", messages[0]["content"])

    def test_next_message_rejects_inner_thought_fields(self):
        fake_openai = FakeOpenAI(
            content=json.dumps(
                {
                    "aiMessage": "Sounds tasty. Do you cook often?",
                    "translatedMessage": "맛있겠다. 요리는 자주 해?",
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


class InnerThoughtApiTests(unittest.TestCase):
    def test_inner_thought_returns_request_identifiers_and_private_reaction(self):
        ai_response = {
            "innerThought": "매운 피자를 좋아하는구나. 취향이 확실해서 좀 재밌네.",
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
                "/api/v1/conversation/inner-thought",
                json=valid_inner_thought_payload(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "data": {
                    "sessionId": 100,
                    "messageId": 1001,
                    **ai_response,
                },
                "error": None,
            },
        )
        messages = fake_openai.completions.kwargs["messages"]
        self.assertIn("Counterpart role: friend", messages[1]["content"])
        self.assertIn(
            "Last user message: USER turn 1 message 1001: I like pizza because it is spicy.",
            messages[1]["content"],
        )
        self.assertNotIn("Next fixed question", messages[1]["content"])
        self.assertIn(
            "Do not mention expression quality, sentence quality, grammar, naturalness, or study feedback inside innerThought.",
            messages[0]["content"],
        )
        self.assertIn(
            "Do not use innerThought to preview the next topic, next fixed question, or a future scenario beat.",
            messages[0]["content"],
        )

    def test_inner_thought_invalid_ai_response_returns_502(self):
        invalid_responses = [
            {"innerThought": "매운 피자를 좋아하는구나."},
            {
                "innerThought": "매운 피자를 좋아하는구나.",
                "innerThoughtType": "UNKNOWN",
            },
            {
                "sessionId": 999,
                "messageId": 999,
                "innerThought": "매운 피자를 좋아하는구나.",
                "innerThoughtType": "GOOD",
            },
        ]
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        for ai_response in invalid_responses:
            with self.subTest(ai_response=ai_response):
                fake_openai = FakeOpenAI(content=json.dumps(ai_response))
                with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
                    response = make_client(app).post(
                        "/api/v1/conversation/inner-thought",
                        json=valid_inner_thought_payload(),
                    )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "AI_RESPONSE_INVALID",
                )

    def test_inner_thought_generation_failure_returns_503(self):
        fake_openai = FakeOpenAI(error=RuntimeError("network failed"))
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/inner-thought",
                json=valid_inner_thought_payload(),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")

    def test_inner_thought_rejects_empty_history(self):
        payload = valid_inner_thought_payload()
        payload["conversationHistory"] = []
        app = create_app(make_settings())

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/inner-thought",
                json=payload,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        openai_class.assert_not_called()

    def test_inner_thought_rejects_mismatched_submitted_history(self):
        payload = valid_inner_thought_payload()
        payload["submittedMessageId"] = 9999
        app = create_app(make_settings())

        with patch("app.core.openai_client.OpenAI") as openai_class:
            response = make_client(app).post(
                "/api/v1/conversation/inner-thought",
                json=payload,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        openai_class.assert_not_called()


class MessageFeedbackApiTests(unittest.TestCase):
    def setUp(self):
        clear_message_feedback_cache()

    def test_message_feedback_rejects_written_form_feedback_reason(self):
        payload = needs_improvement_message_feedback(1001)
        payload.pop("scoreEvidence")
        payload["correctionExpression"] = "Hi, my name is Sangmin."
        payload["correctionReason"] = (
            "인사 뒤에 쉼표를 넣고 이름을 대문자로 쓰면 자연스러워요."
        )
        feedback = conversation_models.MessageFeedbackData.model_validate(payload)

        with self.assertRaisesRegex(
            next_message_service.AiResponseInvalidError,
            "message_feedback_written_form_feedback",
        ):
            next_message_service._validate_spoken_message_feedback(
                feedback,
                "hi my name is sangmin",
            )

    def test_message_feedback_rejects_case_and_punctuation_only_correction(self):
        payload = needs_improvement_message_feedback(1001)
        payload.pop("scoreEvidence")
        payload["correctionExpression"] = "Hi, my name is Sangmin."
        payload["correctionReason"] = "이름을 자연스럽게 소개할 수 있어요."
        feedback = conversation_models.MessageFeedbackData.model_validate(payload)

        with self.assertRaisesRegex(
            next_message_service.AiResponseInvalidError,
            "message_feedback_spoken_form_only",
        ):
            next_message_service._validate_spoken_message_feedback(
                feedback,
                "hi my name is sangmin",
            )

    def test_message_feedback_repairs_case_and_punctuation_only_candidate(self):
        invalid_candidate = message_feedback_candidate(
            needs_improvement_message_feedback(1001),
        )
        invalid_candidate["scoreEvidence"] = {
            "contextFit": 2,
            "clarity": 2,
            "languageAccuracy": 1,
        }
        invalid_candidate["correctionExpression"] = "Hi, my name is Sangmin."
        invalid_candidate["correctionReason"] = "이름을 대문자로 쓰고 쉼표를 넣어 보세요."
        valid_candidate = message_feedback_candidate(good_message_feedback(1001))
        valid_copy = message_feedback_copy(good_message_feedback(1001))
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(invalid_candidate),
                json.dumps(valid_candidate),
                json.dumps(valid_copy),
            ],
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

        self.assertEqual(response.status_code, 202)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertEqual(entry.feedback.feedbackType.value, "GOOD")
        self.assertTrue(entry.candidate_was_repaired)

    def test_message_feedback_keeps_like_infinitive_gerund_alternative_good(self):
        candidate = message_feedback_candidate(
            needs_improvement_message_feedback(1001),
        )
        candidate["scoreEvidence"] = {
            "contextFit": 2,
            "clarity": 2,
            "languageAccuracy": 1,
        }
        candidate["baseLocaleAnalogy"] = "표현은 맞지만 다른 형태를 권한 상황이에요."
        candidate["correctionExpression"] = "I like watching Formula One."
        candidate["correctionReason"] = "like watching이 더 자연스럽게 들릴 수 있어요."
        copy = message_feedback_copy(good_message_feedback(1001))
        fake_openai = FakeOpenAI(
            contents=[json.dumps(candidate), json.dumps(copy)],
        )
        payload = valid_message_feedback_payload()
        payload["evaluationContext"]["content"] = (
            "What do you enjoy doing in your free time?"
        )
        payload["userMessage"] = "I like to watch Formula One."
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=payload,
            )

        self.assertEqual(response.status_code, 202)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertEqual(entry.feedback.feedbackType.value, "GOOD")
        self.assertEqual(entry.score_evidence.languageAccuracy, 2)
        self.assertIsNone(entry.feedback.correctionExpression)
        self.assertIsNone(entry.feedback.correctionReason)
        self.assertFalse(entry.candidate_was_repaired)

    def test_message_feedback_keeps_prefixed_placeholder_unchanged(self):
        normalized = next_message_service._normalize_message_feedback_placeholders(
            {"correctionExpression": "I enjoy [your hobby]."},
        )

        self.assertEqual(
            normalized["correctionExpression"],
            "I enjoy [your hobby].",
        )

    def test_message_feedback_uses_generic_candidate_until_copy_rewrites_it(self):
        candidate = message_feedback_candidate(
            needs_improvement_message_feedback(1001),
        )
        candidate["correctionExpression"] = (
            "Hi, my name is Sangmin. I enjoy [your information]."
        )
        copy = message_feedback_copy(needs_improvement_message_feedback(1001))
        copy["correctionExpression"] = (
            "Hi, my name is Sangmin. I enjoy [your hobby]."
        )
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(candidate),
                json.dumps(copy),
            ],
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

        self.assertEqual(response.status_code, 202)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertFalse(entry.candidate_was_repaired)
        self.assertIn("[your hobby]", entry.feedback.correctionExpression)

    def test_message_feedback_repairs_generic_copy_placeholder(self):
        candidate = message_feedback_candidate(
            needs_improvement_message_feedback(1001),
        )
        invalid_copy = message_feedback_copy(needs_improvement_message_feedback(1001))
        invalid_copy["correctionExpression"] = (
            "Hi, my name is Sangmin. I enjoy [your information]."
        )
        valid_copy = message_feedback_copy(needs_improvement_message_feedback(1001))
        valid_copy["correctionExpression"] = (
            "Hi, my name is Sangmin. I enjoy [your hobby]."
        )
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(candidate),
                json.dumps(invalid_copy),
                json.dumps(valid_copy),
            ],
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

        self.assertEqual(response.status_code, 202)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertTrue(entry.copy_was_repaired)
        self.assertIn("[your hobby]", entry.feedback.correctionExpression)

    def test_message_feedback_completes_missing_positive_feedback_for_clear_needs_candidate(self):
        candidate = message_feedback_candidate(
            needs_improvement_message_feedback(1001),
        )
        candidate["scoreEvidence"] = {
            "contextFit": 0,
            "clarity": 2,
            "languageAccuracy": 2,
        }
        candidate["positiveFeedback"] = None
        copy = message_feedback_copy(needs_improvement_message_feedback(1001))
        fake_openai = FakeOpenAI(
            contents=[json.dumps(candidate), json.dumps(copy)],
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

        self.assertEqual(response.status_code, 202)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertFalse(entry.candidate_was_repaired)
        self.assertIsNotNone(entry.feedback.positiveFeedback)

    def test_message_feedback_accepts_contextual_placeholder(self):
        payload = needs_improvement_message_feedback(1001)
        payload.pop("scoreEvidence")
        payload["correctionExpression"] = "I have [your travel document]."
        feedback = conversation_models.MessageFeedbackData.model_validate(payload)

        next_message_service._validate_spoken_message_feedback(
            feedback,
            "My aircon bill is very high.",
        )

    def test_message_feedback_accepts_spoken_word_correction(self):
        payload = needs_improvement_message_feedback(1001)
        payload.pop("scoreEvidence")
        payload["correctionExpression"] = "I don't like pizza."
        payload["correctionReason"] = "부정할 때 don't를 넣어 뜻을 분명히 해요."
        feedback = conversation_models.MessageFeedbackData.model_validate(payload)

        next_message_service._validate_spoken_message_feedback(
            feedback,
            "I no like pizza",
        )

    def test_message_feedback_assembles_good_from_score_and_discards_needs_fields(self):
        content = conversation_models.MessageFeedbackContent.model_validate(
            {
                "baseLocaleAnalogy": "질문에 맞게 자연스럽게 답했어요.",
                "positiveFeedback": "이 값은 제거되어야 해요.",
                "feedbackDetail": "핵심을 자연스럽게 전달했어요.",
                "correctionExpression": "Written-only correction.",
                "correctionReason": "이 값도 제거되어야 해요.",
                "benchmarkMessage": "질문에 맞는 핵심을 자연스럽게 전달했어요.",
            },
        )
        score_evidence = conversation_models.MessageFeedbackScoreEvidence(
            contextFit=2,
            clarity=2,
            languageAccuracy=2,
        )

        feedback = next_message_service._assemble_message_feedback(
            content,
            message_id=1001,
            score_evidence=score_evidence,
        )

        self.assertEqual(feedback.messageId, 1001)
        self.assertEqual(feedback.feedbackType.value, "GOOD")
        self.assertIsNone(feedback.positiveFeedback)
        self.assertIsNone(feedback.correctionExpression)
        self.assertIsNone(feedback.correctionReason)

    def test_message_feedback_assembles_needs_from_score_and_discards_good_fields(self):
        content = conversation_models.MessageFeedbackContent.model_validate(
            {
                "baseLocaleAnalogy": "질문의 일부만 답한 상황이에요.",
                "positiveFeedback": "핵심 단어를 말한 점은 좋아요.",
                "feedbackDetail": "이 값은 제거되어야 해요.",
                "correctionExpression": "I like [your hobby] because [your reason].",
                "correctionReason": "빠진 이유를 덧붙여 보세요.",
                "benchmarkMessage": "이 값도 제거되어야 해요.",
            },
        )
        score_evidence = conversation_models.MessageFeedbackScoreEvidence(
            contextFit=1,
            clarity=2,
            languageAccuracy=2,
        )

        feedback = next_message_service._assemble_message_feedback(
            content,
            message_id=1001,
            score_evidence=score_evidence,
        )

        self.assertEqual(feedback.messageId, 1001)
        self.assertEqual(feedback.feedbackType.value, "NEEDS_IMPROVEMENT")
        self.assertIsNone(feedback.feedbackDetail)
        self.assertIsNone(feedback.benchmarkMessage)

    def test_message_feedback_locks_type_from_candidate_score_evidence(self):
        candidate = message_feedback_candidate(
            needs_improvement_message_feedback(1001),
        )
        copy = message_feedback_copy(needs_improvement_message_feedback(1001))
        fake_openai = FakeOpenAI(
            contents=[json.dumps(candidate), json.dumps(copy)],
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

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(fake_openai.completions.calls), 2)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertEqual(entry.feedback.feedbackType.value, "NEEDS_IMPROVEMENT")
        self.assertEqual(entry.score_evidence.contextFit, 2)
        self.assertFalse(entry.candidate_was_repaired)
        self.assertFalse(entry.copy_was_repaired)
        self.assertFalse(entry.copy_was_fallback)

    def test_message_feedback_normalizes_type_only_candidate_fields_without_repair(self):
        candidate = message_feedback_candidate(good_message_feedback(1001))
        candidate["positiveFeedback"] = "이 값은 서버가 제거해요."
        copy = message_feedback_copy(good_message_feedback(1001))
        fake_openai = FakeOpenAI(
            contents=[json.dumps(candidate), json.dumps(copy)],
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

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(fake_openai.completions.calls), 2)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertEqual(entry.feedback.feedbackType.value, "GOOD")
        self.assertIsNone(entry.feedback.positiveFeedback)
        self.assertFalse(entry.candidate_was_repaired)

    def test_message_feedback_repairs_invalid_candidate_once(self):
        invalid_candidate = message_feedback_candidate(good_message_feedback(1001))
        invalid_candidate.pop("feedbackDetail")
        valid_candidate = message_feedback_candidate(good_message_feedback(1001))
        copy = message_feedback_copy(good_message_feedback(1001))
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(invalid_candidate),
                json.dumps(valid_candidate),
                json.dumps(copy),
            ],
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

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(fake_openai.completions.calls), 3)
        self.assertTrue(
            next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
            .candidate_was_repaired,
        )

    def test_message_feedback_candidate_repair_failure_returns_502_without_cache(self):
        invalid_candidate = message_feedback_candidate(good_message_feedback(1001))
        invalid_candidate.pop("feedbackDetail")
        fake_openai = FakeOpenAI(
            contents=[json.dumps(invalid_candidate), json.dumps(invalid_candidate)],
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
        self.assertEqual(len(fake_openai.completions.calls), 2)
        self.assertIsNone(get_cached_message_feedback(100, 1001))

    def test_message_feedback_repairs_invalid_copy_once(self):
        candidate = message_feedback_candidate(good_message_feedback(1001))
        invalid_copy = message_feedback_copy(good_message_feedback(1001))
        invalid_copy.pop("feedbackDetail")
        valid_copy = message_feedback_copy(good_message_feedback(1001))
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(candidate),
                json.dumps(invalid_copy),
                json.dumps(valid_copy),
            ],
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

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(fake_openai.completions.calls), 3)
        self.assertTrue(
            next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
            .copy_was_repaired,
        )

    def test_message_feedback_uses_candidate_after_copy_repair_fails(self):
        candidate = message_feedback_candidate(good_message_feedback(1001))
        invalid_copy = message_feedback_copy(good_message_feedback(1001))
        invalid_copy.pop("feedbackDetail")
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(candidate),
                json.dumps(invalid_copy),
                json.dumps(invalid_copy),
            ],
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

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(fake_openai.completions.calls), 3)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertEqual(entry.feedback.feedbackType.value, "GOOD")
        self.assertTrue(entry.copy_was_fallback)

    def test_message_feedback_uses_candidate_after_copy_generation_fails(self):
        candidate = message_feedback_candidate(good_message_feedback(1001))
        fake_openai = FakeOpenAI(
            contents=[json.dumps(candidate)],
            errors=[None, RuntimeError("copy unavailable")],
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

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(fake_openai.completions.calls), 2)
        entry = next_message_service._get_expected_message_feedback_entries(100, [1001])[0]
        self.assertEqual(entry.feedback.feedbackType.value, "GOOD")
        self.assertTrue(entry.copy_was_fallback)

    def test_message_feedback_first_generation_failure_returns_503_without_cache(self):
        fake_openai = FakeOpenAI(error=RuntimeError("candidate unavailable"))
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
        self.assertEqual(len(fake_openai.completions.calls), 1)
        self.assertIsNone(get_cached_message_feedback(100, 1001))

    def test_message_feedback_prompts_lock_score_and_type_to_server(self):
        candidate_prompt = next_message_service._message_feedback_system_prompt(
            EvaluationContextType.AI_MESSAGE,
        )
        copy_prompt = next_message_service._message_feedback_review_system_prompt(
            EvaluationContextType.AI_MESSAGE,
        )

        self.assertNotIn('"messageId":1', candidate_prompt)
        self.assertNotIn('"feedbackType":"GOOD or NEEDS_IMPROVEMENT"', candidate_prompt)
        self.assertIn('"scoreEvidence"', candidate_prompt)
        self.assertNotIn('"messageId":1', copy_prompt)
        self.assertNotIn('"feedbackType":"GOOD or NEEDS_IMPROVEMENT"', copy_prompt)
        self.assertNotIn('"scoreEvidence"', copy_prompt)
        self.assertIn("Do not make capitalization, punctuation", copy_prompt)
        self.assertIn("Do not mention capitalization, commas, periods", copy_prompt)
        self.assertIn("[your travel document]", candidate_prompt)
        self.assertIn("[your travel document]", copy_prompt)
        self.assertIn("I like reading a book", candidate_prompt)
        self.assertIn("This is so cool", candidate_prompt)

    def test_message_feedback_repair_prompt_explains_generic_placeholder(self):
        request = conversation_models.MessageFeedbackRequest.model_validate(
            valid_message_feedback_payload(),
        )
        error = next_message_service.AiResponseInvalidError(
            "message_feedback_generic_placeholder",
        )
        prompt = next_message_service._message_feedback_repair_user_prompt(
            request,
            {"correctionExpression": "I enjoy [your information]."},
            error,
        )
        feedback_data = good_message_feedback(1001)
        feedback_data.pop("scoreEvidence")
        copy_prompt = next_message_service._message_feedback_review_repair_user_prompt(
            request,
            conversation_models.MessageFeedbackData.model_validate(
                feedback_data,
            ),
            conversation_models.MessageFeedbackScoreEvidence(
                contextFit=2,
                clarity=2,
                languageAccuracy=2,
            ),
            [],
            {"correctionExpression": "I enjoy [your information]."},
            error,
        )

        self.assertIn("[your hobby]", prompt)
        self.assertIn("generic placeholder", prompt)
        self.assertIn("[your hobby]", copy_prompt)
        self.assertIn("generic placeholder", copy_prompt)

    def test_message_feedback_rejects_non_integer_score_evidence(self):
        invalid_candidate = message_feedback_candidate(
            needs_improvement_message_feedback(1001),
        )
        invalid_candidate["scoreEvidence"]["contextFit"] = "2"
        fake_openai = FakeOpenAI(
            contents=[json.dumps(invalid_candidate), json.dumps(invalid_candidate)],
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
        self.assertIsNone(get_cached_message_feedback(100, 1001))

    def test_message_feedback_generates_feedback_and_returns_preparing(self):
        ai_response = {
            "messageId": 1001,
            "feedbackType": "GOOD",
            "scoreEvidence": {
                "contextFit": 2,
                "clarity": 2,
                "languageAccuracy": 2,
            },
            "baseLocaleAnalogy": '"왜 그게 필요한데?"라고 친구에게 이유를 자연스럽게 묻는 것과 같아요.',
            "positiveFeedback": None,
            "feedbackDetail": "친구에게 필요한 이유를 가볍게 확인하는 자연스러운 구어체예요.",
            "correctionExpression": None,
            "correctionReason": None,
            "benchmarkMessage": "필요한 이유를 자연스럽게 확인했어요.",
            "detectedPatterns": [],
        }
        fake_openai = FakeOpenAI(message_feedback=ai_response)
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
        candidate_messages = fake_openai.completions.calls[0]["messages"]
        review_messages = fake_openai.completions.calls[1]["messages"]
        self.assertIn("Feedback Task", candidate_messages[0]["content"])
        self.assertIn("baseLocaleAnalogy", candidate_messages[0]["content"])
        self.assertIn("Counterpart role: friend", candidate_messages[1]["content"])
        self.assertIn("User utterance: why do you wanna know that?", candidate_messages[1]["content"])
        self.assertIn("Review Task", review_messages[0]["content"])
        self.assertIn("scoreEvidence and feedbackType are locked by the server", review_messages[0]["content"])
        self.assertIn("Candidate JSON", review_messages[1]["content"])
        cached_feedback = get_cached_message_feedback(100, 1001)
        self.assertIsNotNone(cached_feedback)
        self.assertEqual(cached_feedback.feedbackType, "GOOD")
        self.assertIsNone(cached_feedback.correctionExpression)

    def test_message_feedback_accepts_user_opening_instruction(self):
        ai_response = {
            "messageId": 1001,
            "feedbackType": "GOOD",
            "scoreEvidence": {
                "contextFit": 2,
                "clarity": 2,
                "languageAccuracy": 2,
            },
            "baseLocaleAnalogy": '"아이스 아메리카노 한 잔 주세요"라고 자연스럽게 주문하는 것과 같아요.',
            "positiveFeedback": None,
            "feedbackDetail": "원하는 음료를 공손하게 주문해서 점원이 바로 이해할 수 있어요.",
            "correctionExpression": None,
            "correctionReason": None,
            "benchmarkMessage": None,
        }
        fake_openai = FakeOpenAI(message_feedback=ai_response)
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
        judgement_messages = fake_openai.completions.calls[0]["messages"]
        self.assertIn("Feedback Task", judgement_messages[0]["content"])
        self.assertIn(
            "Evaluation context type: SCENARIO_OPENING_INSTRUCTION",
            judgement_messages[0]["content"],
        )
        self.assertIn(
            "Evaluation context type: SCENARIO_OPENING_INSTRUCTION",
            judgement_messages[1]["content"],
        )
        self.assertIn(
            "점원에게 먼저 주문하고 싶은 음료를 말해보세요.",
            judgement_messages[1]["content"],
        )
        self.assertIn("Counterpart role: cafe staff", judgement_messages[1]["content"])
        self.assertIn("Can I get an iced americano?", judgement_messages[1]["content"])

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
        self.assertNotIn("MessageFeedbackEvaluation", schemas)
        self.assertNotIn("MessageFeedbackScoreEvidence", schemas)

    def test_message_feedback_generates_and_caches_good_feedback(self):
        ai_response = {
            "messageId": 1001,
            "feedbackType": "GOOD",
            "scoreEvidence": {
                "contextFit": 2,
                "clarity": 2,
                "languageAccuracy": 2,
            },
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
        fake_openai = FakeOpenAI(message_feedback=ai_response)
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

    def test_message_feedback_overwrites_benchmark_from_verified_catalog_pattern(self):
        ai_response = good_message_feedback()
        ai_response["benchmarkMessage"] = "질문 의도를 자연스럽게 확인했어요."
        ai_response["detectedPatterns"] = [
            {
                "errorType": "informal_question",
                "status": "correct",
                "evidence": "why do you wanna know that?",
            },
        ]
        fake_openai = FakeOpenAI(message_feedback=ai_response)
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )
        catalog = {
            "informal_question": {
                "description": "친구에게 이유를 자연스럽게 묻는 구어체 질문",
                "gamifiable": True,
                "benchmarkMessage": "검증된 정량 benchmark 문구예요.",
                "source": "Landit 검증 출처",
                "sourceVerified": True,
            },
        }

        with (
            patch.object(
                next_message_service,
                "_BENCHMARK_PATTERN_CATALOG",
                catalog,
                create=True,
            ),
            patch("app.core.openai_client.OpenAI", return_value=fake_openai),
        ):
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=valid_message_feedback_payload(),
            )

        self.assertEqual(response.status_code, 202)
        cached_feedback = get_cached_message_feedback(100, 1001)
        self.assertIsNotNone(cached_feedback)
        self.assertEqual(
            cached_feedback.benchmarkMessage,
            "검증된 정량 benchmark 문구예요.",
        )

    def test_message_feedback_uses_saynow_article_catalog_benchmark(self):
        ai_response = good_message_feedback()
        ai_response["benchmarkMessage"] = "관사를 자연스럽게 사용했어요."
        ai_response["detectedPatterns"] = [
            {
                "errorType": "article_a_omission",
                "status": "correct",
                "evidence": "an apple",
            },
        ]
        payload = valid_message_feedback_payload()
        payload["userMessage"] = "I ate an apple because I was hungry."
        fake_openai = FakeOpenAI(message_feedback=ai_response)
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=payload,
            )

        self.assertEqual(response.status_code, 202)
        cached_feedback = get_cached_message_feedback(100, 1001)
        self.assertIsNotNone(cached_feedback)
        self.assertEqual(
            cached_feedback.benchmarkMessage,
            "한국인의 79%가 틀리는 a/an을 정확히 썼어요",
        )

    def test_catalog_benchmark_requires_evidence_from_user_utterance(self):
        catalog = {
            "informal_question": {
                "description": "친구에게 이유를 자연스럽게 묻는 구어체 질문",
                "gamifiable": True,
                "benchmarkMessage": "검증된 정량 benchmark 문구예요.",
                "source": "Landit 검증 출처",
                "sourceVerified": True,
            },
        }
        detected_patterns = [
            {
                "errorType": "informal_question",
                "status": "correct",
                "evidence": "what do you need it for",
            },
        ]

        with patch.object(
            next_message_service,
            "_BENCHMARK_PATTERN_CATALOG",
            catalog,
            create=True,
        ):
            benchmark_message = (
                next_message_service._benchmark_message_from_detected_patterns(
                    detected_patterns,
                    "why do you wanna know that?",
                )
            )

        self.assertIsNone(benchmark_message)

    def test_catalog_benchmark_uses_catalog_pattern_with_user_evidence(self):
        catalog = {
            "tense_aspect": {
                "description": "시제·상",
                "gamifiable": True,
                "benchmarkMessage": "불규칙 과거형을 정확히 사용했어요.",
                "exampleRight": "I ate dinner.",
            },
        }
        detected_patterns = [
            {
                "errorType": "tense_aspect",
                "status": "correct",
                "evidence": "like",
            },
        ]

        with patch.object(
            next_message_service,
            "_BENCHMARK_PATTERN_CATALOG",
            catalog,
            create=True,
        ):
            benchmark_message = (
                next_message_service._benchmark_message_from_detected_patterns(
                    detected_patterns,
                    "I like to watch Formula One.",
                )
            )

        self.assertEqual(
            benchmark_message,
            "불규칙 과거형을 정확히 사용했어요.",
        )

    def test_message_feedback_keeps_nonquantitative_catalog_copy_without_pattern(self):
        feedback_data = good_message_feedback(1001)
        feedback_data.pop("scoreEvidence")
        feedback = conversation_models.MessageFeedbackData.model_validate(feedback_data)
        catalog = {
            "tense_aspect": {
                "description": "시제·상",
                "gamifiable": True,
                "benchmarkMessage": "불규칙 과거형을 정확히 사용했어요.",
                "exampleRight": "I ate dinner.",
            },
        }
        feedback = feedback.model_copy(
            update={"benchmarkMessage": "불규칙 과거형을 정확히 사용했어요."},
        )

        with patch.object(
            next_message_service,
            "_BENCHMARK_PATTERN_CATALOG",
            catalog,
            create=True,
        ):
            processed = next_message_service._postprocess_message_feedback_benchmark(
                feedback,
                [],
                "I like to watch Formula One.",
            )

        self.assertEqual(processed.benchmarkMessage, "불규칙 과거형을 정확히 사용했어요.")

    def test_message_feedback_uses_default_for_unverified_quantitative_benchmark(self):
        ai_response = good_message_feedback()
        ai_response["benchmarkMessage"] = "한국인의 23%가 놓치는 이유 연결을 챙겼어요."
        ai_response["detectedPatterns"] = []
        fake_openai = FakeOpenAI(message_feedback=ai_response)
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
        self.assertEqual(
            cached_feedback.benchmarkMessage,
            "질문에 맞는 핵심을 자연스럽게 전달했어요.",
        )

    def test_message_feedback_uses_default_for_unverified_benchmark_source_claim(self):
        ai_response = good_message_feedback()
        ai_response["benchmarkMessage"] = "조사에 따르면 이유를 덧붙인 표현이에요."
        ai_response["detectedPatterns"] = []
        fake_openai = FakeOpenAI(message_feedback=ai_response)
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
        self.assertEqual(
            cached_feedback.benchmarkMessage,
            "질문에 맞는 핵심을 자연스럽게 전달했어요.",
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

    def test_message_feedback_rejects_internal_policy_in_correction_reason(self):
        ai_response = {
            "messageId": 1001,
            "feedbackType": "NEEDS_IMPROVEMENT",
            "scoreEvidence": {
                "contextFit": 1,
                "clarity": 2,
                "languageAccuracy": 2,
            },
            "baseLocaleAnalogy": '"이름만 말하고 소개는 생략했어요"라고 답하는 것과 같아요.',
            "positiveFeedback": "이름을 자연스럽게 소개한 점은 좋아요.",
            "feedbackDetail": None,
            "correctionExpression": "Hi, my name is Sangmin. I enjoy [your hobby].",
            "correctionReason": "없는 사실을 만들지 않고 질문에 충분히 답할 수 있어요.",
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
        self.assertIsNone(get_cached_message_feedback(100, 1001))

    def test_message_feedback_mismatched_message_id_returns_502(self):
        ai_response = {
            "messageId": 9999,
            "feedbackType": "GOOD",
            "scoreEvidence": {
                "contextFit": 2,
                "clarity": 2,
                "languageAccuracy": 2,
            },
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
        self.assertEqual(len(fake_openai.completions.calls), 1)

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
            "scoreEvidence": {
                "contextFit": 2,
                "clarity": 2,
                "languageAccuracy": 2,
            },
            "baseLocaleAnalogy": '"피자를 좋아해요. 매워서요"라고 이유를 바로 붙여 말하는 것과 같아요.',
            "positiveFeedback": None,
            "feedbackDetail": "좋아하는 음식과 이유를 because로 자연스럽게 연결했어요.",
            "correctionExpression": None,
            "correctionReason": None,
            "benchmarkMessage": None,
            "detectedPatterns": [],
        }
        fake_openai = FakeOpenAI(message_feedback=ai_response)
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
        fake_openai = FakeOpenAI(message_feedback=feedback)
        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            response = make_client(app).post(
                "/api/v1/conversation/message-feedback",
                json=payload,
            )
        self.assertEqual(response.status_code, 202)

    def _request_session_feedback(self, app, expected_message_ids):
        payload = valid_session_feedback_payload()
        payload["expectedMessageIds"] = expected_message_ids
        fake_openai = FakeOpenAI(
            content=json.dumps(
                {
                    "sessionId": 100,
                    "highlightMessage": "대화 의도를 정확히 전달했어요.",
                    "summaryMessage": "상황에 맞게 대화를 이어갔어요.",
                },
            ),
        )
        with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
            return make_client(app).post(
                "/api/v1/conversation/session-feedback",
                json=payload,
            )

    def test_session_feedback_scores_context_appropriate_message_at_100(self):
        app = self._app()
        self._cache_feedback(app, good_message_feedback(1001), user_message="Saturday.")

        response = self._request_session_feedback(app, [1001])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["nativeScore"], 100)
        self.assertEqual(response.json()["data"]["starRating"], 3.0)

    def test_session_feedback_scores_minor_language_issue_at_85(self):
        app = self._app()
        self._cache_feedback(
            app,
            needs_improvement_message_feedback(1001),
            user_message="I like pizza because spicy.",
        )

        response = self._request_session_feedback(app, [1001])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["nativeScore"], 85)
        self.assertEqual(response.json()["data"]["starRating"], 2.5)

    def test_session_feedback_scores_irrelevant_clear_message_at_60(self):
        app = self._app()
        feedback = needs_improvement_message_feedback(1001)
        feedback["scoreEvidence"] = {
            "contextFit": 0,
            "clarity": 2,
            "languageAccuracy": 2,
        }
        self._cache_feedback(app, feedback, user_message="I like soccer.")

        response = self._request_session_feedback(app, [1001])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["nativeScore"], 60)
        self.assertEqual(response.json()["data"]["starRating"], 1.5)

    def test_session_feedback_floors_low_message_score_at_50(self):
        app = self._app()
        feedback = needs_improvement_message_feedback(1001)
        feedback["scoreEvidence"] = {
            "contextFit": 0,
            "clarity": 0,
            "languageAccuracy": 0,
        }
        self._cache_feedback(app, feedback, user_message="...")

        response = self._request_session_feedback(app, [1001])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["nativeScore"], 50)
        self.assertEqual(response.json()["data"]["starRating"], 1.0)

    def test_session_feedback_combines_raw_average_and_good_rate_for_three_messages(self):
        app = self._app()
        perfect = good_message_feedback(1001)
        minor_issue = needs_improvement_message_feedback(1003)
        irrelevant = needs_improvement_message_feedback(1005)
        irrelevant["scoreEvidence"] = {
            "contextFit": 0,
            "clarity": 2,
            "languageAccuracy": 2,
        }
        self._cache_feedback(app, perfect)
        self._cache_feedback(app, minor_issue)
        self._cache_feedback(app, irrelevant)

        response = self._request_session_feedback(app, [1001, 1003, 1005])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["nativeScore"], 67)
        self.assertEqual(response.json()["data"]["starRating"], 2.0)

    def test_session_feedback_lowers_score_when_three_messages_need_improvement(self):
        app = self._app()
        self._cache_feedback(app, needs_improvement_message_feedback(1001))
        self._cache_feedback(app, needs_improvement_message_feedback(1003))
        self._cache_feedback(app, needs_improvement_message_feedback(1005))

        response = self._request_session_feedback(app, [1001, 1003, 1005])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["nativeScore"], 60)
        self.assertEqual(response.json()["data"]["starRating"], 1.5)

    def test_session_feedback_uses_one_third_good_rate_in_final_score(self):
        app = self._app()
        self._cache_feedback(app, good_message_feedback(1001))
        self._cache_feedback(app, needs_improvement_message_feedback(1003))
        self._cache_feedback(app, needs_improvement_message_feedback(1005))

        response = self._request_session_feedback(app, [1001, 1003, 1005])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["nativeScore"], 73)
        self.assertEqual(response.json()["data"]["starRating"], 2.0)

    def test_session_feedback_uses_two_thirds_good_rate_in_final_score(self):
        app = self._app()
        self._cache_feedback(app, good_message_feedback(1001))
        self._cache_feedback(app, good_message_feedback(1003))
        self._cache_feedback(app, needs_improvement_message_feedback(1005))

        response = self._request_session_feedback(app, [1001, 1003, 1005])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["nativeScore"], 87)
        self.assertEqual(response.json()["data"]["starRating"], 2.5)

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
            user_message="I like pizza because spicy.",
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
        self.assertEqual(body["data"]["nativeScore"], 93)
        self.assertEqual(body["data"]["starRating"], 3.0)
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
            "I like pizza because it is spicy.",
        )
        self.assertNotIn(
            "scoreEvidence",
            body["data"]["messageFeedbacks"][0],
        )
        self.assertNotIn(
            "detectedPatterns",
            body["data"]["messageFeedbacks"][0],
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
    def test_closing_prompt_forbids_meta_closing_and_uses_scenario_context(self):
        prompt = next_message_service._closing_message_system_prompt()

        self.assertIn(
            "Do not announce that the conversation, scenario, practice, or session is ending.",
            prompt,
        )
        self.assertIn(
            "Stay inside the counterpart role and the concrete situation until the final word.",
            prompt,
        )
        self.assertIn(
            "Do not introduce a new topic, question, or additional conversational turn.",
            prompt,
        )
        self.assertNotIn("Do not continue the scenario.", prompt)
        self.assertNotIn("Let's wrap up here.", prompt)
        self.assertNotIn("Let's pause here.", prompt)
        self.assertNotIn("여기서 마무리하자.", prompt)
        self.assertIn("Take your time deciding about the party.", prompt)
        self.assertIn("no onions in your order", prompt)
        self.assertNotIn("Thanks for being honest with me.", prompt)
        self.assertNotIn("I'll give you some space.", prompt)
        self.assertNotIn("상황을 마무리해도", prompt)

    def test_meta_closing_classifier_rejects_only_conversation_endings(self):
        rejected_values = (
            "Let’s wrap up here.",
            "We should wrap up here.",
            "This concludes our conversation.",
            "오늘 대화는 여기까지 할게.",
            "그러면 여기서 대화를 마칠게요.",
            "그러면 여기서 대화를 끝내자.",
        )
        allowed_values = (
            "Let's wrap up the gifts before the party.",
            "오늘 선물 포장은 여기서 마무리하자.",
            "Let's end the trip with dinner by the sea.",
        )

        for value in rejected_values:
            with self.subTest(value=value):
                self.assertTrue(next_message_service._looks_like_meta_closing(value))
        for value in allowed_values:
            with self.subTest(value=value):
                self.assertFalse(next_message_service._looks_like_meta_closing(value))

    def test_closing_message_meta_wrap_up_returns_502(self):
        fake_openai = FakeOpenAI(
            content=json.dumps(
                {
                    "aiMessage": "Got it. Let's wrap up here.",
                    "translatedMessage": "알겠어. 여기서 대화를 마무리하자.",
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
