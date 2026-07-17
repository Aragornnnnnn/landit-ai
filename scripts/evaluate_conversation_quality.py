# LAN-138 대화 품질 사례를 실제 모델로 반복 평가하는 스크립트
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from app.conversation.application.next_message_service import (
    AiGenerationFailedError,
    AiResponseInvalidError,
    MessageFeedbackNotReadyError,
    _get_expected_message_feedback_entries,
    _generate_closing_message_candidate,
    _looks_like_meta_closing,
    _looks_like_question,
    _message_score_from_evidence,
    clear_message_feedback_cache,
    generate_inner_thought,
    generate_message_feedback,
    generate_session_feedback,
)
from app.core.config import Settings
from app.models.conversation import (
    ClosingMessageRequest,
    InnerThoughtRequest,
    MessageFeedbackRequest,
    SessionFeedbackRequest,
)


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("quality cases must be a JSON array")
    return data


def evaluate_cases(
    cases: list[dict[str, Any]],
    *,
    runs: int,
    kind: str,
    settings: Settings,
) -> list[dict[str, Any]]:
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if kind not in {
        "all",
        "closing",
        "inner-thought",
        "message-feedback",
        "feedback-session",
    }:
        raise ValueError(
            "kind must be all, closing, inner-thought, message-feedback, "
            "or feedback-session",
        )

    results: list[dict[str, Any]] = []
    for case in cases:
        case_kind = case["kind"]
        if kind != "all" and case_kind != kind:
            continue
        for run in range(1, runs + 1):
            results.append(_evaluate_case(case, run=run, settings=settings))
    return results


def _evaluate_case(
    case: dict[str, Any],
    *,
    run: int,
    settings: Settings,
) -> dict[str, Any]:
    if case["kind"] == "closing":
        return _evaluate_closing_case(case, run=run, settings=settings)
    if case["kind"] == "inner-thought":
        return _evaluate_inner_thought_case(case, run=run, settings=settings)
    if case["kind"] == "message-feedback":
        return _evaluate_feedback_case(case, run=run, settings=settings)
    if case["kind"] == "feedback-session":
        return _evaluate_feedback_session_case(case, run=run, settings=settings)
    raise ValueError(f"unsupported quality case kind: {case['kind']}")


def _evaluate_closing_case(
    case: dict[str, Any],
    *,
    run: int,
    settings: Settings,
) -> dict[str, Any]:
    response = _generate_closing_message_candidate(
        ClosingMessageRequest.model_validate(case["payload"]),
        settings,
    )
    text = f"{response.aiMessage}\n{response.translatedMessage}"
    expected_context_terms = case["expectedContextTerms"]
    return {
        "caseId": case["caseId"],
        "kind": "closing",
        "run": run,
        "aiMessage": response.aiMessage,
        "translatedMessage": response.translatedMessage,
        "innerThoughtType": response.innerThoughtType,
        "hasQuestion": any(
            _looks_like_question(value)
            for value in (response.aiMessage, response.translatedMessage)
        ),
        "hasMetaClosing": _looks_like_meta_closing(text),
        "matchesExpectedContext": any(
            term.casefold() in text.casefold()
            for term in expected_context_terms
        ),
    }


def _evaluate_inner_thought_case(
    case: dict[str, Any],
    *,
    run: int,
    settings: Settings,
) -> dict[str, Any]:
    response = generate_inner_thought(
        InnerThoughtRequest.model_validate(case["payload"]),
        settings,
    )
    inner_thought = response.innerThought
    expected_types = case["expectedInnerThoughtTypes"]
    required_terms = case["requiredAnyTerms"]
    forbidden_terms = case["forbiddenTerms"]
    found_forbidden_terms = [
        term
        for term in forbidden_terms
        if term.casefold() in inner_thought.casefold()
    ]
    return {
        "caseId": case["caseId"],
        "kind": "inner-thought",
        "run": run,
        "innerThought": inner_thought,
        "innerThoughtType": response.innerThoughtType.value,
        "expectedInnerThoughtTypes": expected_types,
        "expectedTypeMatched": response.innerThoughtType.value in expected_types,
        "requiredAnyTerms": required_terms,
        "requiredTermMatched": any(
            term.casefold() in inner_thought.casefold()
            for term in required_terms
        ),
        "forbiddenTerms": forbidden_terms,
        "foundForbiddenTerms": found_forbidden_terms,
    }


def _evaluate_feedback_case(
    case: dict[str, Any],
    *,
    run: int,
    settings: Settings,
) -> dict[str, Any]:
    request = MessageFeedbackRequest.model_validate(case["payload"])
    clear_message_feedback_cache()
    try:
        generate_message_feedback(request, settings)
        feedback_entry = _get_expected_message_feedback_entries(
            request.sessionId,
            [request.messageId],
        )[0]
    except (
        AiGenerationFailedError,
        AiResponseInvalidError,
        ValidationError,
    ) as exc:
        return _feedback_evaluation_error_result(case, run, exc)
    finally:
        clear_message_feedback_cache()

    feedback = feedback_entry.feedback
    score_evidence = feedback_entry.score_evidence
    message_score = _message_score_from_evidence(score_evidence)
    feedback_type = feedback.feedbackType.value
    expected_feedback_type = case.get("expectedFeedbackType")
    expected_context_fit = case.get("expectedContextFit")
    expected_score_range = case.get("expectedMessageScoreRange")
    required_placeholders = case.get("requiredCorrectionPlaceholders", [])
    required_placeholder_prefixes = case.get(
        "requiredCorrectionPlaceholderPrefixes",
        [],
    )
    correction_expression = feedback.correctionExpression or ""
    missing_placeholders = [
        placeholder
        for placeholder in required_placeholders
        if placeholder not in correction_expression
    ]
    missing_placeholder_prefixes = [
        prefix
        for prefix in required_placeholder_prefixes
        if prefix not in correction_expression
    ]
    feedback_text = "\n".join(
        value
        for value in (
            feedback.baseLocaleAnalogy,
            feedback.positiveFeedback,
            feedback.feedbackDetail,
            feedback.correctionExpression,
            feedback.correctionReason,
        )
        if value is not None
    )
    forbidden_terms = case.get("forbiddenFeedbackTerms", [])
    found_forbidden_terms = [
        term
        for term in forbidden_terms
        if term.casefold() in feedback_text.casefold()
    ]
    return {
        "caseId": case["caseId"],
        "kind": "message-feedback",
        "run": run,
        "expectedFeedbackType": expected_feedback_type,
        "feedbackType": feedback_type,
        "candidateWasRepaired": feedback_entry.candidate_was_repaired,
        "copyWasRepaired": feedback_entry.copy_was_repaired,
        "copyWasFallback": feedback_entry.copy_was_fallback,
        "feedbackTypeMatchesExpectation": (
            feedback_type == expected_feedback_type
            if expected_feedback_type is not None
            else None
        ),
        "scoreEvidence": score_evidence.model_dump(),
        "expectedContextFit": expected_context_fit,
        "contextFitMatchesExpectation": (
            score_evidence.contextFit == expected_context_fit
            if expected_context_fit is not None
            else None
        ),
        "messageScore": message_score,
        "expectedMessageScoreRange": expected_score_range,
        "messageScoreWithinExpectation": (
            expected_score_range[0] <= message_score <= expected_score_range[1]
            if expected_score_range is not None
            else None
        ),
        "baseLocaleAnalogy": feedback.baseLocaleAnalogy,
        "positiveFeedback": feedback.positiveFeedback,
        "feedbackDetail": feedback.feedbackDetail,
        "correctionExpression": feedback.correctionExpression,
        "correctionReason": feedback.correctionReason,
        "finalFeedback": feedback.model_dump(mode="json"),
        "expectedFeedbackTypeMatched": (
            feedback_type == expected_feedback_type
            if expected_feedback_type is not None
            else None
        ),
        "expectedScoreRangeMatched": (
            expected_score_range[0] <= message_score <= expected_score_range[1]
            if expected_score_range is not None
            else None
        ),
        "missingRequiredCorrectionPlaceholders": missing_placeholders,
        "missingRequiredCorrectionPlaceholderPrefixes": missing_placeholder_prefixes,
        "foundForbiddenFeedbackTerms": found_forbidden_terms,
        "feedbackTextMatchesExpectation": (
            not missing_placeholders
            and not missing_placeholder_prefixes
            and not found_forbidden_terms
        ),
        "validationError": None,
        "validationReason": None,
    }


def _feedback_evaluation_error_result(
    case: dict[str, Any],
    run: int,
    error: Exception,
) -> dict[str, Any]:
    return {
        "caseId": case["caseId"],
        "kind": "message-feedback",
        "run": run,
        "expectedFeedbackType": case.get("expectedFeedbackType"),
        "feedbackType": None,
        "candidateWasRepaired": None,
        "copyWasRepaired": None,
        "copyWasFallback": None,
        "feedbackTypeMatchesExpectation": False,
        "scoreEvidence": None,
        "expectedContextFit": case.get("expectedContextFit"),
        "contextFitMatchesExpectation": False,
        "messageScore": None,
        "expectedMessageScoreRange": case.get("expectedMessageScoreRange"),
        "messageScoreWithinExpectation": False,
        "baseLocaleAnalogy": None,
        "positiveFeedback": None,
        "feedbackDetail": None,
        "correctionExpression": None,
        "correctionReason": None,
        "finalFeedback": None,
        "expectedFeedbackTypeMatched": False,
        "expectedScoreRangeMatched": False,
        "missingRequiredCorrectionPlaceholders": [],
        "missingRequiredCorrectionPlaceholderPrefixes": [],
        "foundForbiddenFeedbackTerms": [],
        "feedbackTextMatchesExpectation": False,
        "validationError": type(error).__name__,
        "validationReason": getattr(error, "reason", type(error).__name__),
    }


def _evaluate_feedback_session_case(
    case: dict[str, Any],
    *,
    run: int,
    settings: Settings,
) -> dict[str, Any]:
    started_at = perf_counter()
    message_latencies_ms: list[float] = []
    clear_message_feedback_cache()
    try:
        message_requests = [
            MessageFeedbackRequest.model_validate(payload)
            for payload in case["messageFeedbackPayloads"]
        ]
        for request in message_requests:
            message_started_at = perf_counter()
            response = generate_message_feedback(request, settings)
            message_latencies_ms.append(
                round((perf_counter() - message_started_at) * 1000, 1),
            )
            if response.feedbackStatus.value == "FAILED":
                raise AiGenerationFailedError("message_feedback_failed")

        message_ids = [request.messageId for request in message_requests]
        entries = _get_expected_message_feedback_entries(
            message_requests[0].sessionId,
            message_ids,
        )
        expected_messages = {
            boundary["messageId"]: boundary
            for boundary in case["expectedMessages"]
        }
        message_results = [
            _feedback_session_message_result(
                entry,
                expected_messages[entry.feedback.messageId],
            )
            for entry in entries
        ]

        session_started_at = perf_counter()
        session_feedback = generate_session_feedback(
            SessionFeedbackRequest.model_validate(case["sessionFeedbackPayload"]),
            settings,
        )
        session_latency_ms = round(
            (perf_counter() - session_started_at) * 1000,
            1,
        )
        session_text = (
            f"{session_feedback.highlightMessage}\n"
            f"{session_feedback.summaryMessage}"
        )
        found_forbidden_session_terms = [
            term
            for term in case.get("forbiddenSessionTerms", [])
            if term.casefold() in session_text.casefold()
        ]
        expected_native_score_range = case["expectedNativeScoreRange"]
        return {
            "caseId": case["caseId"],
            "kind": "feedback-session",
            "run": run,
            "messageResults": message_results,
            "messageExpectationsMatched": all(
                result["expectationMatched"]
                for result in message_results
            ),
            "nativeScore": session_feedback.nativeScore,
            "expectedNativeScoreRange": expected_native_score_range,
            "nativeScoreWithinExpectation": (
                expected_native_score_range[0]
                <= session_feedback.nativeScore
                <= expected_native_score_range[1]
            ),
            "starRating": session_feedback.starRating,
            "expectedStarRating": case["expectedStarRating"],
            "starRatingMatchesExpectation": (
                session_feedback.starRating == case["expectedStarRating"]
            ),
            "highlightMessage": session_feedback.highlightMessage,
            "summaryMessage": session_feedback.summaryMessage,
            "messageFeedbacks": [
                feedback.model_dump(mode="json")
                for feedback in session_feedback.messageFeedbacks
            ],
            "foundForbiddenSessionTerms": found_forbidden_session_terms,
            "messageLatenciesMs": message_latencies_ms,
            "sessionFeedbackLatencyMs": session_latency_ms,
            "totalLatencyMs": round(
                (perf_counter() - started_at) * 1000,
                1,
            ),
            "validationError": None,
            "validationReason": None,
        }
    except (
        AiGenerationFailedError,
        AiResponseInvalidError,
        MessageFeedbackNotReadyError,
        ValidationError,
    ) as exc:
        reason = getattr(exc, "reason", None) or str(exc) or type(exc).__name__
        return {
            "caseId": case["caseId"],
            "kind": "feedback-session",
            "run": run,
            "messageResults": [],
            "messageExpectationsMatched": False,
            "nativeScore": None,
            "nativeScoreWithinExpectation": False,
            "starRating": None,
            "starRatingMatchesExpectation": False,
            "foundForbiddenSessionTerms": [],
            "messageLatenciesMs": message_latencies_ms,
            "sessionFeedbackLatencyMs": None,
            "totalLatencyMs": round(
                (perf_counter() - started_at) * 1000,
                1,
            ),
            "validationError": type(exc).__name__,
            "validationReason": reason,
        }
    finally:
        clear_message_feedback_cache()


def _feedback_session_message_result(
    entry: Any,
    expected: dict[str, Any],
) -> dict[str, Any]:
    feedback = entry.feedback
    feedback_text = "\n".join(
        value
        for value in (
            feedback.baseLocaleAnalogy,
            feedback.positiveFeedback,
            feedback.feedbackDetail,
            feedback.correctionExpression,
            feedback.correctionReason,
        )
        if value is not None
    )
    forbidden_terms = expected.get("forbiddenFeedbackTerms", [])
    found_forbidden_terms = [
        term
        for term in forbidden_terms
        if term.casefold() in feedback_text.casefold()
    ]
    required_any_terms = expected.get("requiredAnyFeedbackTerms", [])
    required_any_term_matched = not required_any_terms or any(
        term.casefold() in feedback_text.casefold()
        for term in required_any_terms
    )
    required_any_correction_reason_terms = expected.get(
        "requiredAnyCorrectionReasonTerms",
        [],
    )
    correction_reason = feedback.correctionReason or ""
    required_any_correction_reason_term_matched = (
        not required_any_correction_reason_terms
        or any(
            term.casefold() in correction_reason.casefold()
            for term in required_any_correction_reason_terms
        )
    )
    message_score = _message_score_from_evidence(entry.score_evidence)
    expected_score_range = expected["expectedMessageScoreRange"]
    feedback_type_matches = (
        feedback.feedbackType.value == expected["expectedFeedbackType"]
    )
    score_matches = (
        expected_score_range[0]
        <= message_score
        <= expected_score_range[1]
    )
    return {
        "messageId": feedback.messageId,
        "feedbackType": feedback.feedbackType.value,
        "expectedFeedbackType": expected["expectedFeedbackType"],
        "feedbackTypeMatchesExpectation": feedback_type_matches,
        "scoreEvidence": entry.score_evidence.model_dump(),
        "messageScore": message_score,
        "expectedMessageScoreRange": expected_score_range,
        "messageScoreWithinExpectation": score_matches,
        "candidateWasRepaired": entry.candidate_was_repaired,
        "copyWasRepaired": entry.copy_was_repaired,
        "copyWasFallback": entry.copy_was_fallback,
        "finalFeedback": feedback.model_dump(mode="json"),
        "foundForbiddenFeedbackTerms": found_forbidden_terms,
        "requiredAnyFeedbackTerms": required_any_terms,
        "requiredAnyFeedbackTermMatched": required_any_term_matched,
        "requiredAnyCorrectionReasonTerms": required_any_correction_reason_terms,
        "requiredAnyCorrectionReasonTermMatched": (
            required_any_correction_reason_term_matched
        ),
        "expectationMatched": (
            feedback_type_matches
            and score_matches
            and not found_forbidden_terms
            and required_any_term_matched
            and required_any_correction_reason_term_matched
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--kind",
        choices=(
            "all",
            "closing",
            "inner-thought",
            "message-feedback",
            "feedback-session",
        ),
        default="all",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/landit-ai-lan-138-results.json"),
    )
    args = parser.parse_args()

    settings = Settings()
    results = evaluate_cases(
        load_cases(args.cases),
        runs=args.runs,
        kind=args.kind,
        settings=settings,
    )
    report = {
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
        "model": settings.openrouter_model,
        "casesFile": str(args.cases),
        "casesSha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "runs": args.runs,
        "kind": args.kind,
        "results": results,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(results)} evaluation results to {args.output}")


if __name__ == "__main__":
    main()
