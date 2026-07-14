# LAN-138 대화 품질 사례를 실제 모델로 반복 평가하는 스크립트
import argparse
import json
from pathlib import Path
from typing import Any

from app.conversation.application.next_message_service import (
    clear_message_feedback_cache,
    generate_closing_message,
    generate_message_feedback,
    get_cached_message_feedback,
)
from app.core.config import Settings
from app.models.conversation import ClosingMessageRequest, MessageFeedbackRequest


_META_CLOSING_PHRASES = (
    "let's wrap up",
    "let's pause here",
    "대화를 마무리하자",
    "여기서 마무리하자",
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
    if kind not in {"all", "closing", "message-feedback"}:
        raise ValueError("kind must be all, closing, or message-feedback")

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
    if case["kind"] == "message-feedback":
        return _evaluate_feedback_case(case, run=run, settings=settings)
    raise ValueError(f"unsupported quality case kind: {case['kind']}")


def _evaluate_closing_case(
    case: dict[str, Any],
    *,
    run: int,
    settings: Settings,
) -> dict[str, Any]:
    response = generate_closing_message(
        ClosingMessageRequest.model_validate(case["payload"]),
        settings,
    )
    text = f"{response.aiMessage}\n{response.translatedMessage}".lower()
    return {
        "caseId": case["caseId"],
        "kind": "closing",
        "run": run,
        "aiMessage": response.aiMessage,
        "translatedMessage": response.translatedMessage,
        "innerThoughtType": response.innerThoughtType,
        "hasQuestion": "?" in text or "？" in text,
        "hasMetaClosing": any(phrase in text for phrase in _META_CLOSING_PHRASES),
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
        feedback = get_cached_message_feedback(request.sessionId, request.messageId)
    finally:
        clear_message_feedback_cache()

    if feedback is None:
        raise RuntimeError("message feedback was not cached")

    feedback_type = feedback.feedbackType.value
    expected_feedback_type = case["expectedFeedbackType"]
    return {
        "caseId": case["caseId"],
        "kind": "message-feedback",
        "run": run,
        "feedbackType": feedback_type,
        "feedbackTypeMatchesExpectation": feedback_type == expected_feedback_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--kind",
        choices=("all", "closing", "message-feedback"),
        default="all",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/landit-ai-lan-138-results.json"),
    )
    args = parser.parse_args()

    results = evaluate_cases(
        load_cases(args.cases),
        runs=args.runs,
        kind=args.kind,
        settings=Settings(),
    )
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(results)} evaluation results to {args.output}")


if __name__ == "__main__":
    main()
