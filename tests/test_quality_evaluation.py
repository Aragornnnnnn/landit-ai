# LAN-138 실제 모델 평가 도구의 결과 요약을 검증하는 unittest 모듈
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import Settings
from app.conversation.application.next_message_service import AiResponseInvalidError
from app.models.conversation import (
    FeedbackStatus,
    InnerThoughtResponse,
    MessageFeedbackData,
    MessageFeedbackResponse,
    MessageFeedbackScoreEvidence,
)
from scripts.evaluate_conversation_quality import evaluate_cases, main


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


class QualityEvaluationTests(unittest.TestCase):
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
        self.assertIn("dealbreaker", roommate_case["forbiddenFeedbackTerms"])

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
                    return_value=SimpleNamespace(openrouter_model="openai/test-model"),
                ),
                patch(
                    "scripts.evaluate_conversation_quality.evaluate_cases",
                    return_value=[],
                ),
            ):
                main()

            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["model"], "openai/test-model")
        self.assertEqual(report["casesFile"], str(cases_path))
        self.assertEqual(report["casesSha256"], hashlib.sha256(b"[]").hexdigest())
        self.assertEqual(report["runs"], 2)
        self.assertEqual(report["kind"], "closing")
        self.assertEqual(report["results"], [])
        datetime.fromisoformat(report["evaluatedAt"])

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
