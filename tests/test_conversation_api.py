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


def message_feedback_judgement(
    message_id=1001,
    *,
    context_fit=2,
    clarity=2,
    language_accuracy=2,
    core_asks=None,
    stated_facts=None,
):
    return {
        "messageId": message_id,
        "coreAsks": (
            [
                {
                    "ask": "say what activity you like",
                    "addressed": True,
                    "evidence": "jogging",
                    "requiredPlaceholder": None,
                },
            ]
            if core_asks is None
            else core_asks
        ),
        "statedFacts": ["jogging"] if stated_facts is None else stated_facts,
        "scoreEvidence": {
            "contextFit": context_fit,
            "clarity": clarity,
            "languageAccuracy": language_accuracy,
        },
    }


def message_feedback_copy(message_id=1001):
    return {
        "messageId": message_id,
        "baseLocaleAnalogy": '"조깅은 좋아하지만 왜 좋은지는 말 안 한 것과 같아요.',
        "positiveFeedback": "좋아하는 활동을 분명하게 말했어요.",
        "feedbackDetail": None,
        "correctionExpression": "I like jogging because [your reason].",
        "correctionReason": "좋아하는 이유가 빠졌어요. [your reason]에 이유를 넣어 보세요.",
        "benchmarkMessage": None,
        "detectedPatterns": [],
    }


def message_feedback_responses(feedback, user_message):
    score_evidence = feedback["scoreEvidence"]
    correction_expression = feedback.get("correctionExpression") or ""
    placeholder_match = re.search(r"\[your [a-z][a-z ]*\]", correction_expression)
    placeholder = placeholder_match.group(0) if placeholder_match else None
    context_fit = score_evidence["contextFit"]
    if context_fit == 2:
        core_asks = [
            {
                "ask": "respond to the evaluation context",
                "addressed": True,
                "evidence": user_message,
                "requiredPlaceholder": None,
            },
        ]
    elif context_fit == 1:
        core_asks = [
            {
                "ask": "answer one part of the evaluation context",
                "addressed": True,
                "evidence": user_message,
                "requiredPlaceholder": None,
            },
            {
                "ask": "answer the remaining part of the evaluation context",
                "addressed": False,
                "evidence": None,
                "requiredPlaceholder": placeholder,
            },
        ]
    else:
        core_asks = [
            {
                "ask": "respond to the evaluation context",
                "addressed": False,
                "evidence": None,
                "requiredPlaceholder": placeholder,
            },
        ]
    judgement = {
        "messageId": feedback["messageId"],
        "coreAsks": core_asks,
        "statedFacts": [user_message],
        "scoreEvidence": score_evidence,
    }
    copy = {
        key: value
        for key, value in feedback.items()
        if key not in {"feedbackType", "scoreEvidence"}
    }
    return [json.dumps(judgement), json.dumps(copy)]


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

    def test_feedback_status_uses_frontend_contract_values(self):
        self.assertEqual(
            {status.value for status in FeedbackStatus},
            {"PREPARING", "COMPLETED", "FAILED"},
        )

    def test_message_feedback_judgement_rejects_invalid_core_ask_contracts(self):
        judgement_model = getattr(
            conversation_models,
            "MessageFeedbackJudgement",
            None,
        )
        self.assertIsNotNone(judgement_model)

        invalid_cases = [
            ("empty core asks", message_feedback_judgement(core_asks=[])),
            (
                "answered without evidence",
                message_feedback_judgement(
                    core_asks=[
                        {
                            "ask": "say what activity you like",
                            "addressed": True,
                            "evidence": None,
                            "requiredPlaceholder": None,
                        },
                    ],
                ),
            ),
            (
                "unanswered with evidence",
                message_feedback_judgement(
                    core_asks=[
                        {
                            "ask": "say why you like it",
                            "addressed": False,
                            "evidence": "because it is fun",
                            "requiredPlaceholder": "[your reason]",
                        },
                    ],
                ),
            ),
            (
                "invalid placeholder",
                message_feedback_judgement(
                    core_asks=[
                        {
                            "ask": "say why you like it",
                            "addressed": False,
                            "evidence": None,
                            "requiredPlaceholder": "[A reason]",
                        },
                    ],
                ),
            ),
            (
                "answered with placeholder",
                message_feedback_judgement(
                    core_asks=[
                        {
                            "ask": "say what activity you like",
                            "addressed": True,
                            "evidence": "jogging",
                            "requiredPlaceholder": "[your hobby]",
                        },
                    ],
                ),
            ),
            (
                "non-integer score",
                message_feedback_judgement(context_fit="2"),
            ),
        ]

        for case_name, payload in invalid_cases:
            with self.subTest(case_name=case_name):
                with self.assertRaises(ValueError):
                    judgement_model.model_validate(payload)

    def test_message_feedback_judgement_requires_request_grounded_evidence_and_context_fit(self):
        parser = getattr(
            next_message_service,
            "_parse_message_feedback_judgement",
            None,
        )
        feedback_type_from_evidence = getattr(
            next_message_service,
            "_feedback_type_from_score_evidence",
            None,
        )
        self.assertIsNotNone(parser)
        self.assertIsNotNone(feedback_type_from_evidence)

        request = MessageFeedbackRequest.model_validate(
            multiple_hobby_questions_payload(),
        )
        partial_judgement = message_feedback_judgement(
            context_fit=1,
            core_asks=[
                {
                    "ask": "say what activity you like",
                    "addressed": True,
                    "evidence": "jogging",
                    "requiredPlaceholder": None,
                },
                {
                    "ask": "say why you like it",
                    "addressed": False,
                    "evidence": None,
                    "requiredPlaceholder": "[your reason]",
                },
            ],
        )

        judgement = parser(partial_judgement, request)

        self.assertEqual(judgement.scoreEvidence.contextFit, 1)
        self.assertEqual(
            feedback_type_from_evidence(judgement.scoreEvidence).value,
            "NEEDS_IMPROVEMENT",
        )

        invalid_cases = [
            (
                "evidence outside user utterance",
                message_feedback_judgement(
                    context_fit=1,
                    core_asks=[
                        {
                            "ask": "say what activity you like",
                            "addressed": True,
                            "evidence": "reading",
                            "requiredPlaceholder": None,
                        },
                        {
                            "ask": "say why you like it",
                            "addressed": False,
                            "evidence": None,
                            "requiredPlaceholder": "[your reason]",
                        },
                    ],
                ),
            ),
            (
                "stated fact outside user utterance",
                message_feedback_judgement(
                    context_fit=1,
                    core_asks=partial_judgement["coreAsks"],
                    stated_facts=["relaxing"],
                ),
            ),
            (
                "partial answer marked complete",
                message_feedback_judgement(
                    context_fit=2,
                    core_asks=partial_judgement["coreAsks"],
                ),
            ),
        ]
        for case_name, invalid_judgement in invalid_cases:
            with self.subTest(case_name=case_name):
                with self.assertRaises(next_message_service.AiResponseInvalidError):
                    parser(invalid_judgement, request)

    def test_message_feedback_server_assigns_request_message_id_when_llm_omits_it(self):
        request = MessageFeedbackRequest.model_validate(
            multiple_hobby_questions_payload(),
        )
        judgement_data = message_feedback_judgement(
            context_fit=1,
            core_asks=[
                {
                    "ask": "say what activity you like",
                    "addressed": True,
                    "evidence": "jogging",
                    "requiredPlaceholder": None,
                },
                {
                    "ask": "say why you like it",
                    "addressed": False,
                    "evidence": None,
                    "requiredPlaceholder": "[your reason]",
                },
            ],
        )
        judgement_data.pop("messageId")
        copy_data = message_feedback_copy()
        copy_data.pop("messageId")

        judgement = next_message_service._parse_message_feedback_judgement(
            judgement_data,
            request,
        )
        feedback, _, _ = next_message_service._parse_and_assemble_message_feedback_copy(
            copy_data,
            judgement,
            request,
        )

        self.assertEqual(feedback.messageId, request.messageId)

    def test_message_feedback_locks_judgement_while_generating_copy(self):
        judgement = message_feedback_judgement(
            context_fit=1,
            core_asks=[
                {
                    "ask": "say what activity you like",
                    "addressed": True,
                    "evidence": "jogging",
                    "requiredPlaceholder": None,
                },
                {
                    "ask": "say why you like it",
                    "addressed": False,
                    "evidence": None,
                    "requiredPlaceholder": "[your reason]",
                },
            ],
        )
        fake_openai = FakeOpenAI(
            contents=[json.dumps(judgement), json.dumps(message_feedback_copy())],
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
                json=multiple_hobby_questions_payload(),
            )

        self.assertEqual(response.status_code, 202)
        cached_feedback = get_cached_message_feedback(100, 1001)
        self.assertIsNotNone(cached_feedback)
        self.assertEqual(cached_feedback.feedbackType, "NEEDS_IMPROVEMENT")
        self.assertEqual(
            cached_feedback.correctionExpression,
            "I like jogging because [your reason].",
        )
        self.assertEqual(len(fake_openai.completions.calls), 2)
        self.assertIn(
            "Judgement Task",
            fake_openai.completions.calls[0]["messages"][0]["content"],
        )
        self.assertIn(
            "Copy Task",
            fake_openai.completions.calls[1]["messages"][0]["content"],
        )
        self.assertIn(
            "Authoritative judgement",
            fake_openai.completions.calls[1]["messages"][1]["content"],
        )

    def test_message_feedback_discards_copy_fields_for_the_other_locked_type(self):
        request = MessageFeedbackRequest.model_validate(
            valid_message_feedback_payload(),
        )
        judgement = next_message_service._parse_message_feedback_judgement(
            {
                "messageId": 1001,
                "coreAsks": [
                    {
                        "ask": "ask why personal information is needed",
                        "addressed": True,
                        "evidence": "why do you wanna know that?",
                        "requiredPlaceholder": None,
                    },
                ],
                "statedFacts": ["why do you wanna know that?"],
                "scoreEvidence": {
                    "contextFit": 2,
                    "clarity": 2,
                    "languageAccuracy": 2,
                },
            },
            request,
        )
        invalid_good_copy = {
            "messageId": 1001,
            "baseLocaleAnalogy": '"왜 필요한데?"라고 묻는 것과 같아요.',
            "positiveFeedback": "자연스럽게 물었어요.",
            "feedbackDetail": "필요한 이유를 확인했어요.",
            "correctionExpression": None,
            "correctionReason": None,
            "benchmarkMessage": None,
        }

        feedback, _, _ = next_message_service._parse_and_assemble_message_feedback_copy(
            invalid_good_copy,
            judgement,
            request,
        )

        self.assertEqual(feedback.feedbackType.value, "GOOD")
        self.assertIsNone(feedback.positiveFeedback)

    def test_message_feedback_repairs_invalid_copy_once(self):
        judgement = message_feedback_judgement(
            context_fit=1,
            core_asks=[
                {
                    "ask": "say what activity you like",
                    "addressed": True,
                    "evidence": "jogging",
                    "requiredPlaceholder": None,
                },
                {
                    "ask": "say why you like it",
                    "addressed": False,
                    "evidence": None,
                    "requiredPlaceholder": "[your reason]",
                },
            ],
        )
        invalid_copy = message_feedback_copy()
        invalid_copy["correctionExpression"] = "I like jogging."
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(judgement),
                json.dumps(invalid_copy),
                json.dumps(message_feedback_copy()),
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
                json=multiple_hobby_questions_payload(),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(fake_openai.completions.calls), 3)
        self.assertIn(
            "Copy Repair Task",
            fake_openai.completions.calls[2]["messages"][0]["content"],
        )

    def test_message_feedback_rejects_invalid_copy_after_one_repair(self):
        judgement = message_feedback_judgement(
            context_fit=1,
            core_asks=[
                {
                    "ask": "say what activity you like",
                    "addressed": True,
                    "evidence": "jogging",
                    "requiredPlaceholder": None,
                },
                {
                    "ask": "say why you like it",
                    "addressed": False,
                    "evidence": None,
                    "requiredPlaceholder": "[your reason]",
                },
            ],
        )
        invalid_copy = message_feedback_copy()
        invalid_copy["correctionReason"] = "Add your reason."
        fake_openai = FakeOpenAI(
            contents=[
                json.dumps(judgement),
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
                json=multiple_hobby_questions_payload(),
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(fake_openai.completions.calls), 3)
        self.assertIsNone(get_cached_message_feedback(100, 1001))

    def test_judgement_prompt_keeps_meaning_neutral_speaking_features_out_of_scoring(self):
        prompt = next_message_service._message_feedback_judgement_system_prompt(
            EvaluationContextType.AI_MESSAGE,
        )

        self.assertIn("Judgement Task", prompt)
        self.assertIn(
            "A short noun phrase can fully answer a what-question.",
            prompt,
        )
        self.assertIn(
            "An answer that clearly satisfies either branch of an or-question has contextFit=2.",
            prompt,
        )
        self.assertIn(
            "Do not mark a clear and context-appropriate casual utterance as NEEDS_IMPROVEMENT solely because it sounds direct.",
            prompt,
        )
        self.assertIn(
            "Do not lower any score for capitalization, punctuation, a meaning-neutral filler",
            prompt,
        )
        self.assertIn(
            "A hostile or dismissive reply can have languageAccuracy=1",
            prompt,
        )

    def test_copy_prompt_exposes_verified_catalog_patterns_only(self):
        catalog = {
            "informal_question": {
                "description": "친구에게 이유를 자연스럽게 묻는 구어체 질문",
                "gamifiable": True,
                "benchmarkMessage": "검증된 정량 benchmark 문구예요.",
                "source": "Landit 검증 출처",
                "sourceVerified": True,
            },
        }

        with patch.object(
            next_message_service,
            "_BENCHMARK_PATTERN_CATALOG",
            catalog,
            create=True,
        ):
            prompt = next_message_service._message_feedback_copy_system_prompt(
                EvaluationContextType.AI_MESSAGE,
            )

        self.assertIn("Copy Task", prompt)
        self.assertIn("Detected Pattern Catalog", prompt)
        self.assertIn('"errorType":"informal_question"', prompt)

    def test_message_feedback_accepts_internal_score_evidence(self):
        ai_response = good_message_feedback()
        ai_response["scoreEvidence"] = {
            "contextFit": 2,
            "clarity": 2,
            "languageAccuracy": 2,
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
        self.assertNotIn("scoreEvidence", response.json()["data"])
        self.assertIsNotNone(get_cached_message_feedback(100, 1001))

    def test_message_feedback_rejects_score_evidence_inconsistent_with_type(self):
        inconsistent_responses = [
            (
                good_message_feedback(),
                {"contextFit": 2, "clarity": 2, "languageAccuracy": 1},
            ),
            (
                needs_improvement_message_feedback(1001),
                {"contextFit": 2, "clarity": 2, "languageAccuracy": 2},
            ),
        ]
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        for ai_response, score_evidence in inconsistent_responses:
            with self.subTest(feedback_type=ai_response["feedbackType"]):
                ai_response["scoreEvidence"] = score_evidence
                fake_openai = FakeOpenAI(content=json.dumps(ai_response))
                with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
                    response = make_client(app).post(
                        "/api/v1/conversation/message-feedback",
                        json=valid_message_feedback_payload(),
                    )

                self.assertEqual(response.status_code, 502)
                self.assertIsNone(get_cached_message_feedback(100, 1001))

    def test_message_feedback_rejects_non_integer_score_evidence(self):
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            ),
        )

        for invalid_score in ["2", 2.0, True]:
            with self.subTest(invalid_score=invalid_score):
                ai_response = needs_improvement_message_feedback(1001)
                ai_response["scoreEvidence"]["contextFit"] = invalid_score
                fake_openai = FakeOpenAI(content=json.dumps(ai_response))
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
        judgement_messages = fake_openai.completions.calls[0]["messages"]
        copy_messages = fake_openai.completions.calls[1]["messages"]
        self.assertIn("Judgement Task", judgement_messages[0]["content"])
        self.assertIn(
            "scenario title, briefing, and conversation goal provide context",
            judgement_messages[0]["content"],
        )
        self.assertIn(
            "Missing one core ask alone must not lower languageAccuracy",
            judgement_messages[0]["content"],
        )
        self.assertIn(
            "tell a little about yourself -> [your hobby]",
            judgement_messages[0]["content"],
        )
        self.assertNotIn("baseLocaleAnalogy", judgement_messages[0]["content"])
        self.assertIn("Counterpart role: friend", judgement_messages[1]["content"])
        self.assertIn("Message ID: 1001", judgement_messages[1]["content"])
        self.assertIn("Message sequence: 2", judgement_messages[1]["content"])
        self.assertIn(
            "User utterance: why do you wanna know that?",
            judgement_messages[1]["content"],
        )
        self.assertIn("Copy Task", copy_messages[0]["content"])
        self.assertIn("baseLocaleAnalogy", copy_messages[0]["content"])
        self.assertIn(
            "Do not treat capitalization, punctuation, a neutral filler",
            copy_messages[0]["content"],
        )
        self.assertIn(
            'Never return the string "null"',
            copy_messages[0]["content"],
        )
        self.assertIn("Authoritative judgement", copy_messages[1]["content"])
        self.assertIn("Locked feedback type: GOOD", copy_messages[1]["content"])
        self.assertIn(
            "Locked GOOD requirements: feedbackDetail must be a Korean explanation",
            copy_messages[1]["content"],
        )
        self.assertIn(
            "Never fill an unanswered personal fact with a concrete example",
            copy_messages[0]["content"],
        )
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
        self.assertIn("Judgement Task", judgement_messages[0]["content"])
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
