# LAN-138 실제 모델 평가 도구의 결과 요약을 검증하는 unittest 모듈
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import Settings
from app.conversation.application.next_message_service import (
    AiGenerationFailedError,
    AiResponseInvalidError,
)
from app.models.conversation import (
    FeedbackStatus,
    InnerThoughtResponse,
    MessageFeedbackAdjudicationEvidence,
    MessageFeedbackData,
    MessageFeedbackResponse,
    MessageFeedbackScoreEvidence,
    SessionFeedbackResponse,
)
from scripts.evaluate_conversation_quality import (
    _feedback_session_message_result,
    evaluate_cases,
    main,
)


def closing_case():
    return {
        "caseId": "closing-meta-wrap-up",
        "kind": "closing",
        "expectedContextTerms": ["quiet", "조용"],
        "payload": {
            "sessionId": 100,
            "submittedMessageId": 1007,
            "submittedTurnNumber": 4,
            "scenario": {
                "scenarioId": 10,
                "title": "기숙사에서 조용히 해달라고 말하기",
                "briefing": "룸메이트에게 밤에 조용히 해달라고 말하는 상황입니다.",
                "conversationGoal": "불편함을 공격적이지 않게 전달합니다.",
                "counterpartRole": "roommate",
            },
            "conversationHistory": [
                {
                    "messageId": 1006,
                    "turnNumber": 4,
                    "role": "AI",
                    "content": "What do you want me to do?",
                },
                {
                    "messageId": 1007,
                    "turnNumber": 4,
                    "role": "USER",
                    "content": "Could you keep it down at night?",
                },
            ],
            "closingReason": "GOAL_COMPLETED",
            "goalCompletionStatus": "COMPLETED",
        },
    }


def feedback_case():
    return {
        "caseId": "feedback-natural-colloquial",
        "kind": "message-feedback",
        "expectedFeedbackType": "GOOD",
        "expectedContextFit": 2,
        "expectedMessageScoreRange": [100, 100],
        "payload": {
            "sessionId": 200,
            "messageId": 2001,
            "turnNumber": 1,
            "messageSequence": 2,
            "scenario": {
                "scenarioId": 20,
                "title": "친구와 약속 잡기",
                "briefing": "친구와 주말 약속을 잡는 상황입니다.",
                "conversationGoal": "제안에 자연스럽게 답합니다.",
                "counterpartRole": "friend",
            },
            "evaluationContext": {
                "type": "AI_MESSAGE",
                "content": "Do you want to watch a movie this weekend?",
            },
            "userMessage": "Yeah, sounds good to me.",
        },
    }


def inner_thought_case():
    return {
        "caseId": "inner-thought-short-answer",
        "kind": "inner-thought",
        "expectedInnerThoughtTypes": ["NORMAL"],
        "requiredAnyTerms": ["짧", "무뚝뚝"],
        "forbiddenTerms": ["다행", "친절"],
        "payload": {
            "sessionId": 300,
            "submittedMessageId": 3001,
            "submittedTurnNumber": 1,
            "scenario": {
                "scenarioId": 30,
                "title": "주말 약속 잡기",
                "briefing": "룸메이트와 주말 약속을 잡습니다.",
                "conversationGoal": "가능한 요일을 정합니다.",
                "counterpartRole": "roommate",
            },
            "conversationHistory": [
                {
                    "messageId": 3000,
                    "turnNumber": 1,
                    "role": "AI",
                    "content": "Does Saturday or Sunday work better for you?",
                },
                {
                    "messageId": 3001,
                    "turnNumber": 1,
                    "role": "USER",
                    "content": "Saturday.",
                },
            ],
        },
    }


def feedback_session_case():
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "lan_175_feedback_session_case.json"
    )
    return json.loads(fixture_path.read_text(encoding="utf-8"))[0]


class QualityEvaluationTests(unittest.TestCase):
    def test_lan_175_session_fixture_preserves_supplied_messages(self):
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "lan_175_feedback_session_case.json"
        )

        self.assertTrue(fixture_path.exists())
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case["kind"], "feedback-session")
        self.assertEqual(
            [payload["messageId"] for payload in case["messageFeedbackPayloads"]],
            [60, 62, 64],
        )
        self.assertEqual(
            [
                (
                    payload["evaluationContext"]["content"],
                    payload["userMessage"],
                )
                for payload in case["messageFeedbackPayloads"]
            ],
            [
                (
                    "Hey, you're my roommate, right?! I'm Charlie, nice to meet you! "
                    "What's your name? Tell me a little about yourself!",
                    "Hello, Charlie. Nice to meet you. I am Sunny, and I'm from Korea, "
                    "South Korea. And, yeah, nice to meet you.",
                ),
                (
                    "Nice to meet you, Sunny. What are you into? What do you love about it?",
                    "I'm into reading books and sometimes I take a picture and draw pictures "
                    "So, yeah, I love these because I really love creating something, and I I "
                    "really like reading something.",
                ),
                (
                    "That sounds really creative. I'm obsessed with Korea! Tell me your "
                    "must-visit spots and why I should go!",
                    "Oh, you are interested in Korea. I live in Busan, and then I just yeah. "
                    "Came here. And I think Haeundae and Kijang and Kwangwala Beach is is so "
                    "really good. So yeah. And if you wanna go to city city views, I think "
                    "it's really good for Seoul because it's so it's so so many hotspot places "
                    "in there and but Busan is so really unique and so really fantastic. City "
                    "in Korea.",
                ),
            ],
        )
        self.assertEqual(
            [boundary["expectedFeedbackType"] for boundary in case["expectedMessages"]],
            ["GOOD", "GOOD", "NEEDS_IMPROVEMENT"],
        )
        self.assertEqual(case["expectedNativeScoreRange"], [83, 87])
        self.assertEqual(case["expectedStarRating"], 2.5)

    def test_feedback_session_result_records_messages_summary_and_latency(self):
        feedbacks = [
            MessageFeedbackData(
                messageId=60,
                feedbackType="GOOD",
                baseLocaleAnalogy='"이름과 출신을 소개했어요"라고 말하는 것과 같아요.',
                feedbackDetail="이름과 출신을 자연스럽게 소개했어요.",
            ),
            MessageFeedbackData(
                messageId=62,
                feedbackType="GOOD",
                baseLocaleAnalogy='"취미와 이유를 말했어요"라고 답하는 것과 같아요.',
                feedbackDetail="취미와 좋아하는 이유를 모두 전달했어요.",
            ),
            MessageFeedbackData(
                messageId=64,
                feedbackType="NEEDS_IMPROVEMENT",
                baseLocaleAnalogy='"여러 장소를 추천했어요"라고 말하는 것과 같아요.',
                positiveFeedback="여행지와 이유를 여러 개 말했어요.",
                correctionExpression=(
                    "Haeundae, Kijang, and Gwangalli Beach are really good."
                ),
                correctionReason="복수 주어에는 is 대신 are를 사용해요.",
            ),
        ]
        evidences = [
            MessageFeedbackScoreEvidence(
                contextFit=2,
                clarity=2,
                languageAccuracy=2,
            ),
            MessageFeedbackScoreEvidence(
                contextFit=2,
                clarity=2,
                languageAccuracy=2,
            ),
            MessageFeedbackScoreEvidence(
                contextFit=2,
                clarity=2,
                languageAccuracy=1,
            ),
        ]
        adjudication_evidences = [
            MessageFeedbackAdjudicationEvidence(
                coverageEvidence=[
                    {
                        "requestExcerpt": "Tell me a little about yourself!",
                        "answerExcerpt": "I am Sunny, and I'm from Korea",
                        "status": "ANSWERED",
                    },
                ],
                ignoredSpeechArtifacts=[],
                actionableIssues=[],
            ),
            MessageFeedbackAdjudicationEvidence(
                coverageEvidence=[
                    {
                        "requestExcerpt": "What are you into?",
                        "answerExcerpt": "I'm into reading books",
                        "status": "ANSWERED",
                    },
                ],
                ignoredSpeechArtifacts=["I I"],
                actionableIssues=[],
            ),
            MessageFeedbackAdjudicationEvidence(
                coverageEvidence=[
                    {
                        "requestExcerpt": "Tell me your must-visit spots",
                        "answerExcerpt": "Haeundae and Kijang",
                        "status": "ANSWERED",
                    },
                ],
                ignoredSpeechArtifacts=["is is"],
                actionableIssues=[
                    {
                        "dimension": "LANGUAGE_ACCURACY",
                        "sourceExcerpt": (
                            "Haeundae and Kijang and Kwangwala Beach is"
                        ),
                        "correctionExcerpt": (
                            "Haeundae, Kijang, and Gwangalli Beach are"
                        ),
                        "rule": (
                            "subject-verb agreement requires a plural verb"
                        ),
                    },
                ],
            ),
        ]
        entries = [
            SimpleNamespace(
                feedback=feedback,
                score_evidence=evidence,
                adjudication_evidence=adjudication_evidence,
                candidate_was_repaired=False,
                copy_was_repaired=False,
                copy_was_fallback=False,
            )
            for feedback, evidence, adjudication_evidence in zip(
                feedbacks,
                evidences,
                adjudication_evidences,
                strict=True,
            )
        ]
        session_response = SessionFeedbackResponse(
            sessionId=14,
            nativeScore=87,
            starRating=2.5,
            highlightMessage="자기소개와 취미를 자연스럽게 이어 간 사람",
            summaryMessage="자기소개와 취미는 자연스러웠고 수 일치를 다듬으면 좋아요.",
            messageFeedbacks=feedbacks,
        )

        with (
            patch(
                "scripts.evaluate_conversation_quality.generate_message_feedback",
                return_value=MessageFeedbackResponse(
                    sessionId=14,
                    messageId=60,
                    feedbackStatus=FeedbackStatus.PREPARING,
                ),
            ),
            patch(
                "scripts.evaluate_conversation_quality._get_expected_message_feedback_entries",
                return_value=entries,
            ),
            patch(
                "scripts.evaluate_conversation_quality.generate_session_feedback",
                return_value=session_response,
            ),
        ):
            results = evaluate_cases(
                [feedback_session_case()],
                runs=1,
                kind="feedback-session",
                settings=Settings(_env_file=None),
            )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(
            [message["feedbackType"] for message in result["messageResults"]],
            ["GOOD", "GOOD", "NEEDS_IMPROVEMENT"],
        )
        self.assertEqual(
            [message["messageScore"] for message in result["messageResults"]],
            [100, 100, 85],
        )
        self.assertTrue(result["messageExpectationsMatched"])
        self.assertEqual(result["nativeScore"], 87)
        self.assertTrue(result["nativeScoreWithinExpectation"])
        self.assertTrue(result["starRatingMatchesExpectation"])
        self.assertEqual(result["foundForbiddenSessionTerms"], [])
        self.assertEqual(len(result["messageLatenciesMs"]), 3)
        self.assertTrue(all(value >= 0 for value in result["messageLatenciesMs"]))
        self.assertGreaterEqual(result["sessionFeedbackLatencyMs"], 0)
        self.assertGreaterEqual(result["totalLatencyMs"], 0)
        self.assertIsNone(result["validationError"])

    def test_feedback_session_result_records_generation_error(self):
        with patch(
            "scripts.evaluate_conversation_quality.generate_message_feedback",
            side_effect=AiGenerationFailedError("test failure"),
        ):
            results = evaluate_cases(
                [feedback_session_case()],
                runs=1,
                kind="feedback-session",
                settings=Settings(_env_file=None),
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["validationError"], "AiGenerationFailedError")
        self.assertEqual(results[0]["validationReason"], "test failure")
        self.assertGreaterEqual(results[0]["totalLatencyMs"], 0)

    def test_feedback_session_requires_grammar_reason_in_correction_reason(self):
        feedback = MessageFeedbackData(
            messageId=64,
            feedbackType="NEEDS_IMPROVEMENT",
            baseLocaleAnalogy='"여러 장소를 추천했어요"라고 말하는 것과 같아요.',
            positiveFeedback="여행지를 구체적으로 추천했어요.",
            correctionExpression=(
                "Haeundae, Kijang, and Gwangalli Beach are really good."
            ),
            correctionReason="동사 형태를 맞추면 더 자연스러워요.",
        )
        entry = SimpleNamespace(
            feedback=feedback,
            score_evidence=MessageFeedbackScoreEvidence(
                contextFit=2,
                clarity=2,
                languageAccuracy=1,
            ),
            adjudication_evidence=MessageFeedbackAdjudicationEvidence(
                coverageEvidence=[
                    {
                        "requestExcerpt": "Tell me your must-visit spots",
                        "answerExcerpt": "Haeundae, Kijang",
                        "status": "ANSWERED",
                    },
                ],
                ignoredSpeechArtifacts=[],
                actionableIssues=[
                    {
                        "dimension": "LANGUAGE_ACCURACY",
                        "sourceExcerpt": (
                            "Haeundae, Kijang, and Gwangalli Beach is"
                        ),
                        "correctionExcerpt": (
                            "Haeundae, Kijang, and Gwangalli Beach are"
                        ),
                        "rule": (
                            "subject-verb agreement requires a plural verb"
                        ),
                    },
                ],
            ),
            candidate_was_repaired=False,
            copy_was_repaired=False,
            copy_was_fallback=False,
        )

        result = _feedback_session_message_result(
            entry,
            {
                "expectedFeedbackType": "NEEDS_IMPROVEMENT",
                "expectedMessageScoreRange": [70, 85],
                "requiredAnyCorrectionReasonTerms": [
                    "복수 주어",
                    "주어-동사",
                    "수 일치",
                ],
            },
        )

        self.assertFalse(result["requiredAnyCorrectionReasonTermMatched"])
        self.assertFalse(result["expectationMatched"])

    def test_feedback_session_result_validates_adjudication_evidence(self):
        feedback = MessageFeedbackData(
            messageId=62,
            feedbackType="NEEDS_IMPROVEMENT",
            baseLocaleAnalogy='"취미를 설명했어요"라고 말하는 것과 같아요.',
            positiveFeedback="취미와 이유를 함께 설명했어요.",
            correctionExpression="I really like reading.",
            correctionReason="표현을 더 간결하게 말하면 좋아요.",
        )
        entry = SimpleNamespace(
            feedback=feedback,
            score_evidence=MessageFeedbackScoreEvidence(
                contextFit=1,
                clarity=2,
                languageAccuracy=1,
            ),
            adjudication_evidence=MessageFeedbackAdjudicationEvidence(
                coverageEvidence=[
                    {
                        "requestExcerpt": "What are you into?",
                        "answerExcerpt": None,
                        "status": "MISSING",
                    },
                ],
                ignoredSpeechArtifacts=[],
                actionableIssues=[
                    {
                        "dimension": "LANGUAGE_ACCURACY",
                        "sourceExcerpt": "I I",
                        "correctionExcerpt": "I",
                        "rule": "Avoid repeated words.",
                    },
                ],
            ),
            candidate_was_repaired=False,
            copy_was_repaired=False,
            copy_was_fallback=False,
        )

        result = _feedback_session_message_result(
            entry,
            {
                "expectedFeedbackType": "NEEDS_IMPROVEMENT",
                "expectedMessageScoreRange": [65, 65],
                "expectedMissingCoverageCount": 0,
                "expectedActionableIssueDimensions": [],
                "forbiddenActionableSourceTerms": ["I I"],
                "requiredAnyActionableRuleTerms": ["subject-verb", "agreement"],
            },
        )

        self.assertFalse(result["missingCoverageCountMatchesExpectation"])
        self.assertFalse(result["actionableIssueDimensionsMatchExpectation"])
        self.assertEqual(result["foundForbiddenActionableSourceTerms"], ["I I"])
        self.assertFalse(result["requiredAnyActionableRuleTermMatched"])
        self.assertFalse(result["expectationMatched"])

    def test_lan_166_scoring_fixture_covers_reported_score_boundaries(self):
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "lan_166_scoring_cases.json"
        )

        self.assertTrue(fixture_path.exists())
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        cases_by_id = {case["caseId"]: case for case in cases}

        expected_ranges = {
            "lan166-partial-multi-question-duration": [50, 50],
            "lan166-partial-multi-question-party": [65, 65],
            "lan166-short-context-complete-food": [100, 100],
            "lan166-harsh-roommate-boundary": [65, 85],
            "lan166-unnatural-word-choice-boundary": [85, 85],
            "lan166-valid-alternative-question-answer": [100, 100],
            "lan166-session-113-cleaning-no-answer": [80, 80],
            "lan166-session-113-daily-rhythm-partial": [80, 80],
            "lan166-session-113-roommate-dealbreakers-partial": [80, 80],
        }
        self.assertEqual(set(cases_by_id), set(expected_ranges))
        for case_id, expected_range in expected_ranges.items():
            self.assertEqual(
                cases_by_id[case_id]["expectedMessageScoreRange"],
                expected_range,
            )

    def test_lan_167_fixture_covers_feedback_quality_boundaries(self):
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "lan_167_feedback_quality_cases.json"
        )

        self.assertTrue(fixture_path.exists())
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        cases_by_id = {case["caseId"]: case for case in cases}

        self.assertEqual(
            set(cases_by_id),
            {
                "lan167-capitalization-and-period-only",
                "lan167-meaning-neutral-filler",
                "lan167-valid-like-to-watch",
                "lan167-partial-self-introduction",
                "lan167-off-topic-answer",
                "lan167-partial-hobby-reason",
                "lan167-preserve-unknown-reason",
                "lan167-cleaning-unknown-answer",
                "lan167-daily-rhythm-one-missing-part",
                "lan167-ambiguous-roommate-no",
            },
        )
        written_form_case = cases_by_id["lan167-capitalization-and-period-only"]
        self.assertEqual(
            written_form_case["forbiddenFeedbackTerms"],
            [
                "대문자",
                "소문자",
                "쉼표",
                "마침표",
                "문장부호",
                "capitalization",
                "uppercase",
                "lowercase",
                "comma",
                "period",
                "punctuation",
                "full stop",
            ],
        )
        introduction_case = cases_by_id["lan167-partial-self-introduction"]
        self.assertEqual(
            introduction_case["requiredCorrectionPlaceholders"],
            ["[your hobby]"],
        )
        self.assertIn("없는 사실", introduction_case["forbiddenFeedbackTerms"])
        hobby_case = cases_by_id["lan167-partial-hobby-reason"]
        self.assertEqual(
            hobby_case["requiredCorrectionPlaceholders"],
            ["[your reason]"],
        )
        reading_case = cases_by_id["lan167-preserve-unknown-reason"]
        self.assertIn("relax", reading_case["forbiddenFeedbackTerms"])
        self.assertEqual(
            {
                case_id: case["expectedContextFit"]
                for case_id, case in cases_by_id.items()
            },
            {
                "lan167-capitalization-and-period-only": 2,
                "lan167-meaning-neutral-filler": 2,
                "lan167-valid-like-to-watch": 2,
                "lan167-partial-self-introduction": 1,
                "lan167-off-topic-answer": 0,
                "lan167-partial-hobby-reason": 1,
                "lan167-preserve-unknown-reason": 2,
                "lan167-cleaning-unknown-answer": 1,
                "lan167-daily-rhythm-one-missing-part": 1,
                "lan167-ambiguous-roommate-no": 1,
            },
        )
        cleaning_case = cases_by_id["lan167-cleaning-unknown-answer"]
        self.assertEqual(
            cleaning_case["requiredCorrectionPlaceholders"],
            ["[your preferred way]"],
        )
        daily_rhythm_case = cases_by_id["lan167-daily-rhythm-one-missing-part"]
        self.assertEqual(
            daily_rhythm_case["requiredCorrectionPlaceholders"],
            ["[your bedtime]"],
        )
        roommate_case = cases_by_id["lan167-ambiguous-roommate-no"]
        self.assertEqual(
            roommate_case.get("requiredCorrectionPlaceholders"),
            ["[your dealbreakers]"],
        )
        self.assertNotIn("forbiddenFeedbackTerms", roommate_case)

    def test_lan_169_fixture_covers_inner_thought_tone_boundaries(self):
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "lan_169_inner_thought_quality_cases.json"
        )

        self.assertTrue(fixture_path.exists())
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        cases_by_id = {case["caseId"]: case for case in cases}

        self.assertEqual(
            set(cases_by_id),
            {
                "lan169-short-no",
                "lan169-short-saturday",
                "lan169-unknown-answer",
                "lan169-unexplained-recommendation",
                "lan169-repeated-refusal",
                "lan169-harsh-boundary",
                "lan169-directed-profanity",
                "lan169-natural-routine-answer",
            },
        )
        self.assertEqual(
            cases_by_id["lan169-directed-profanity"][
                "expectedInnerThoughtTypes"
            ],
            ["BAD"],
        )
        self.assertEqual(
            cases_by_id["lan169-natural-routine-answer"][
                "expectedInnerThoughtTypes"
            ],
            ["GOOD"],
        )
        self.assertIn(
            "떠오르",
            cases_by_id["lan169-unknown-answer"]["requiredAnyTerms"],
        )
        self.assertIn(
            "단호",
            cases_by_id["lan169-short-no"]["requiredAnyTerms"],
        )
        self.assertIn(
            "서운",
            cases_by_id["lan169-harsh-boundary"]["requiredAnyTerms"],
        )
        self.assertIn(
            "아침",
            cases_by_id["lan169-natural-routine-answer"]["requiredAnyTerms"],
        )
        self.assertIn(
            "공격",
            cases_by_id["lan169-directed-profanity"]["requiredAnyTerms"],
        )

    def test_main_records_reproducible_execution_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            cases_path = Path(directory) / "cases.json"
            output_path = Path(directory) / "results.json"
            cases_path.write_text("[]", encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "evaluate_conversation_quality.py",
                        "--cases",
                        str(cases_path),
                        "--runs",
                        "2",
                        "--kind",
                        "closing",
                        "--output",
                        str(output_path),
                    ],
                ),
                patch(
                    "scripts.evaluate_conversation_quality.Settings",
                    return_value=SimpleNamespace(
                        openrouter_model="openai/test-model",
                        openrouter_review_model="openai/review-model",
                        message_feedback_review_enabled=False,
                    ),
                ),
                patch(
                    "scripts.evaluate_conversation_quality.evaluate_cases",
                    return_value=[],
                ),
            ):
                main()

            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["model"], "openai/test-model")
        self.assertEqual(report["reviewModel"], "openai/review-model")
        self.assertFalse(report["messageFeedbackReviewEnabled"])
        self.assertEqual(report["casesFile"], str(cases_path))
        self.assertEqual(report["casesSha256"], hashlib.sha256(b"[]").hexdigest())
        self.assertEqual(report["runs"], 2)
        self.assertEqual(report["kind"], "closing")
        self.assertEqual(report["results"], [])
        datetime.fromisoformat(report["evaluatedAt"])

    def test_direct_script_imports_app_from_its_own_repository(self):
        repository_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import evaluate_conversation_quality\n"
                    "from app.conversation.application import "
                    "next_message_service\n"
                    "print(next_message_service.__file__)"
                ),
            ],
            cwd=repository_root / "scripts",
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            Path(completed.stdout.strip()).resolve(),
            repository_root
            / "app"
            / "conversation"
            / "application"
            / "next_message_service.py",
        )

    def test_closing_result_detects_meta_wrap_up_through_real_generation_path(self):
        with patch(
            "app.conversation.application.next_message_service._request_json_completion",
            return_value={
                "aiMessage": "I understand. Let’s wrap up here.",
                "translatedMessage": "알겠어. 여기서 마무리하자.",
                "innerThought": "부탁한 내용은 이해했다.",
                "innerThoughtType": "NORMAL",
            },
        ):
            try:
                results = evaluate_cases(
                    [closing_case()],
                    runs=1,
                    kind="closing",
                    settings=Settings(_env_file=None),
                )
            except AiResponseInvalidError:
                self.fail("quality evaluation must inspect candidates before policy rejection")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["caseId"], "closing-meta-wrap-up")
        self.assertTrue(results[0]["hasMetaClosing"])
        self.assertFalse(results[0]["hasQuestion"])

    def test_closing_result_compares_expected_context_terms(self):
        with patch(
            "app.conversation.application.next_message_service._request_json_completion",
            return_value={
                "aiMessage": "Thanks for being honest with me.",
                "translatedMessage": "솔직하게 말해줘서 고마워.",
                "innerThought": "무슨 뜻인지는 알겠다.",
                "innerThoughtType": "NORMAL",
            },
        ):
            results = evaluate_cases(
                [closing_case()],
                runs=1,
                kind="closing",
                settings=Settings(_env_file=None),
            )

        self.assertFalse(results[0].get("matchesExpectedContext", True))

    def test_inner_thought_result_checks_type_and_text_expectations(self):
        with patch(
            "scripts.evaluate_conversation_quality.generate_inner_thought",
            return_value=InnerThoughtResponse(
                sessionId=300,
                messageId=3001,
                innerThought="토요일이 좋다는 건 알겠는데, 대답이 꽤 짧네.",
                innerThoughtType="NORMAL",
            ),
        ):
            try:
                results = evaluate_cases(
                    [inner_thought_case()],
                    runs=1,
                    kind="inner-thought",
                    settings=Settings(_env_file=None),
                )
            except ValueError as exc:
                self.fail(str(exc))

        self.assertEqual(results[0]["innerThoughtType"], "NORMAL")
        self.assertTrue(results[0]["expectedTypeMatched"])
        self.assertTrue(results[0]["requiredTermMatched"])
        self.assertEqual(results[0]["foundForbiddenTerms"], [])

    def test_feedback_result_compares_expected_type(self):
        feedback = MessageFeedbackData(
            messageId=2001,
            feedbackType="GOOD",
            baseLocaleAnalogy='"그래, 좋지"라고 자연스럽게 답하는 것과 같아요.',
            feedbackDetail="친구의 제안에 자연스럽게 동의했어요.",
        )
        response = MessageFeedbackResponse(
            sessionId=200,
            messageId=2001,
            feedbackStatus=FeedbackStatus.PREPARING,
        )
        score_evidence = MessageFeedbackScoreEvidence(
            contextFit=2,
            clarity=2,
            languageAccuracy=2,
        )
        with (
            patch(
                "scripts.evaluate_conversation_quality.generate_message_feedback",
                return_value=response,
            ),
            patch(
                "scripts.evaluate_conversation_quality._get_expected_message_feedback_entries",
                return_value=[
                    SimpleNamespace(
                        feedback=feedback,
                        score_evidence=score_evidence,
                        candidate_was_repaired=True,
                        copy_was_repaired=False,
                        copy_was_fallback=True,
                    ),
                ],
            ),
        ):
            results = evaluate_cases(
                [feedback_case()],
                runs=1,
                kind="message-feedback",
                settings=Settings(_env_file=None),
            )

        self.assertEqual(results[0]["feedbackType"], "GOOD")
        self.assertEqual(results[0]["expectedFeedbackType"], "GOOD")
        self.assertTrue(results[0]["feedbackTypeMatchesExpectation"])
        self.assertEqual(results[0]["expectedContextFit"], 2)
        self.assertTrue(results[0]["contextFitMatchesExpectation"])
        self.assertEqual(
            results[0]["finalFeedback"]["feedbackType"],
            "GOOD",
        )
        self.assertTrue(results[0]["expectedFeedbackTypeMatched"])
        self.assertTrue(results[0]["expectedScoreRangeMatched"])
        self.assertIn("scoreEvidence", results[0])
        self.assertEqual(
            results[0]["scoreEvidence"],
            {"contextFit": 2, "clarity": 2, "languageAccuracy": 2},
        )
        self.assertEqual(results[0]["messageScore"], 100)
        self.assertTrue(results[0]["candidateWasRepaired"])
        self.assertFalse(results[0]["copyWasRepaired"])
        self.assertTrue(results[0]["copyWasFallback"])
        self.assertNotIn("reviewWasFallback", results[0])
        self.assertEqual(results[0]["expectedMessageScoreRange"], [100, 100])
        self.assertTrue(results[0]["messageScoreWithinExpectation"])

    def test_feedback_result_checks_required_placeholders_and_forbidden_terms(self):
        case = feedback_case()
        case["expectedFeedbackType"] = "NEEDS_IMPROVEMENT"
        case["expectedMessageScoreRange"] = [80, 80]
        case["requiredCorrectionPlaceholders"] = ["[your hobby]"]
        case["forbiddenFeedbackTerms"] = ["Seoul", "없는 사실"]
        feedback = MessageFeedbackData(
            messageId=2001,
            feedbackType="NEEDS_IMPROVEMENT",
            baseLocaleAnalogy='"이름만 말하고 소개는 덧붙이지 않았어요"라고 답하는 것과 같아요.',
            positiveFeedback="이름을 자연스럽게 소개한 점은 좋아요.",
            correctionExpression="Hi, my name is Sangmin. I enjoy [your hobby].",
            correctionReason="[your hobby]에 평소 좋아하는 활동을 넣어 소개를 완성해 보세요.",
        )
        response = MessageFeedbackResponse(
            sessionId=200,
            messageId=2001,
            feedbackStatus=FeedbackStatus.PREPARING,
        )
        score_evidence = MessageFeedbackScoreEvidence(
            contextFit=1,
            clarity=2,
            languageAccuracy=2,
        )
        with (
            patch(
                "scripts.evaluate_conversation_quality.generate_message_feedback",
                return_value=response,
            ),
            patch(
                "scripts.evaluate_conversation_quality._get_expected_message_feedback_entries",
                return_value=[
                    SimpleNamespace(
                        feedback=feedback,
                        score_evidence=score_evidence,
                        candidate_was_repaired=False,
                        copy_was_repaired=False,
                        copy_was_fallback=False,
                    ),
                ],
            ),
        ):
            results = evaluate_cases(
                [case],
                runs=1,
                kind="message-feedback",
                settings=Settings(_env_file=None),
            )

        self.assertIn("missingRequiredCorrectionPlaceholders", results[0])
        self.assertEqual(results[0]["missingRequiredCorrectionPlaceholders"], [])
        self.assertEqual(results[0]["foundForbiddenFeedbackTerms"], [])
        self.assertTrue(results[0]["feedbackTextMatchesExpectation"])

    def test_feedback_result_checks_required_placeholder_prefixes(self):
        case = feedback_case()
        case["expectedFeedbackType"] = "NEEDS_IMPROVEMENT"
        case["expectedMessageScoreRange"] = [60, 60]
        case["requiredCorrectionPlaceholderPrefixes"] = ["[your travel "]
        feedback = MessageFeedbackData(
            messageId=2001,
            feedbackType="NEEDS_IMPROVEMENT",
            baseLocaleAnalogy=(
                '"필요한 증빙이 무엇인지는 말하지 않았어요"라고 '
                "질문의 일부만 답하는 것과 같아요."
            ),
            positiveFeedback="문장을 끝까지 말한 점은 좋아요.",
            correctionExpression="I have [your travel document].",
            correctionReason="여행 계획을 보여 줄 수 있는 자료를 넣어 답해 보세요.",
        )
        score_evidence = MessageFeedbackScoreEvidence(
            contextFit=0,
            clarity=2,
            languageAccuracy=2,
        )

        with (
            patch(
                "scripts.evaluate_conversation_quality.generate_message_feedback",
                return_value=MessageFeedbackResponse(
                    sessionId=200,
                    messageId=2001,
                    feedbackStatus=FeedbackStatus.PREPARING,
                ),
            ),
            patch(
                "scripts.evaluate_conversation_quality._get_expected_message_feedback_entries",
                return_value=[
                    SimpleNamespace(
                        feedback=feedback,
                        score_evidence=score_evidence,
                        candidate_was_repaired=False,
                        copy_was_repaired=False,
                        copy_was_fallback=False,
                    ),
                ],
            ),
        ):
            results = evaluate_cases(
                [case],
                runs=1,
                kind="message-feedback",
                settings=Settings(_env_file=None),
            )

        self.assertEqual(
            results[0]["missingRequiredCorrectionPlaceholderPrefixes"],
            [],
        )
        self.assertTrue(results[0]["feedbackTextMatchesExpectation"])

    def test_feedback_result_allows_actual_data_without_expected_type(self):
        case = feedback_case()
        del case["expectedFeedbackType"]
        feedback = MessageFeedbackData(
            messageId=2001,
            feedbackType="GOOD",
            baseLocaleAnalogy='"그래, 좋아"라고 자연스럽게 동의하는 것과 같아요.',
            feedbackDetail="친구의 제안에 자연스럽게 동의했어요.",
        )
        score_evidence = MessageFeedbackScoreEvidence(
            contextFit=2,
            clarity=2,
            languageAccuracy=2,
        )

        with (
            patch(
                "scripts.evaluate_conversation_quality.generate_message_feedback",
                return_value=MessageFeedbackResponse(
                    sessionId=200,
                    messageId=2001,
                    feedbackStatus=FeedbackStatus.PREPARING,
                ),
            ),
            patch(
                "scripts.evaluate_conversation_quality._get_expected_message_feedback_entries",
                return_value=[
                    SimpleNamespace(
                        feedback=feedback,
                        score_evidence=score_evidence,
                        candidate_was_repaired=False,
                        copy_was_repaired=False,
                        copy_was_fallback=False,
                    ),
                ],
            ),
        ):
            results = evaluate_cases(
                [case],
                runs=1,
                kind="message-feedback",
                settings=Settings(_env_file=None),
            )

        self.assertIsNone(results[0]["expectedFeedbackType"])
        self.assertIsNone(results[0]["feedbackTypeMatchesExpectation"])
        self.assertIsNone(results[0]["expectedFeedbackTypeMatched"])

    def test_feedback_result_records_invalid_judgement_without_aborting_batch(self):
        with patch(
            "scripts.evaluate_conversation_quality.generate_message_feedback",
            side_effect=AiResponseInvalidError("test_validation_reason"),
        ):
            results = evaluate_cases(
                [feedback_case()],
                runs=1,
                kind="message-feedback",
                settings=Settings(_env_file=None),
            )

        self.assertEqual(results[0]["validationError"], "AiResponseInvalidError")
        self.assertEqual(results[0]["validationReason"], "test_validation_reason")
        self.assertIsNone(results[0]["finalFeedback"])
