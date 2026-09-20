# 프리톡 세션 요약을 생성하고 원문 참조 계약을 검증하는 모듈
import asyncio
import json
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.core.openai_client import create_async_openai_client
from app.core.structured_output import json_schema_response_format
from app.free_talk.llm.json_completion import (
    AiGenerationFailedError,
    AiResponseInvalidError,
    _parse_json_object,
    _extract_content,
)
from app.models.free_talk import (
    ContextSummaryRequest,
    ContextSummaryResponse,
    SessionSummaryContent,
)


class SummaryInputTooLargeError(AiResponseInvalidError):
    """요약 입력이 모델 예산을 초과해 외부 호출을 만들 수 없을 때 발생한다."""


_SUMMARY_SYSTEM_PROMPT = (
    "Summarize the supplied free-talk source messages into JSON with exactly these keys: "
    "topic, userStatements, openThreads, interactionContext. "
    "Keep direct user facts, corrections, negations, dates, names, and numbers. "
    "Treat current source messages as higher priority than previousSummary. "
    "Do not turn plans into completed events or historical facts into current facts. "
    "Use sourceMessageIds from the supplied messages or inherited previousSummary only. "
    "userStatements must be grounded in USER messages. Do not infer personality or intent."
)


async def generate_context_summary(
    payload: ContextSummaryRequest,
    settings: Settings,
) -> ContextSummaryResponse:
    """요약 전용 deadline으로 세션 컨텍스트 요약을 생성한다.

    Args:
        payload: BE가 선택한 원문 구간과 이전 요약.
        settings: OpenRouter 및 요약 예산 설정.
    Returns:
        참조 ID가 검증된 세션 요약 응답.
    Raises:
        SummaryInputTooLargeError: 요약 입력이 설정된 예산을 넘을 때.
        AiResponseInvalidError: 모델 출력이 요약 계약을 위반할 때.
        AiGenerationFailedError: provider 호출 또는 deadline이 실패할 때.
    """
    user_prompt = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
    if _estimate_tokens(_SUMMARY_SYSTEM_PROMPT + user_prompt) > settings.free_talk_context_input_budget_tokens:
        raise SummaryInputTooLargeError("summary input exceeds token budget")

    try:
        async with asyncio.timeout(settings.free_talk_summary_timeout_seconds):
            client = create_async_openai_client(
                settings,
                timeout=settings.free_talk_summary_timeout_seconds,
            )
            completion = await client.chat.completions.create(
                model=_required_model(settings),
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_completion_tokens=settings.free_talk_summary_max_tokens,
                response_format=json_schema_response_format(
                    SessionSummaryContent,
                    name="free_talk_session_summary",
                ),
            )
    except SummaryInputTooLargeError:
        raise
    except Exception as exc:
        raise AiGenerationFailedError from exc

    try:
        summary = SessionSummaryContent.model_validate(
            _parse_json_object(_extract_content(completion)),
        )
        _validate_summary_references(summary, payload)
        return ContextSummaryResponse(
            policyVersion=payload.policyVersion,
            baseRevision=payload.baseRevision,
            coveredThroughSequence=payload.targetThroughSequence,
            summary=summary,
        )
    except (ValidationError, ValueError, AiResponseInvalidError) as exc:
        raise AiResponseInvalidError from exc


def _required_model(settings: Settings) -> str:
    if settings.openrouter_model is None or not settings.openrouter_model.strip():
        raise AiGenerationFailedError("OPENROUTER_MODEL is required.")
    return settings.openrouter_model


def _estimate_tokens(value: str) -> int:
    """모델별 tokenizer가 없어도 보수적으로 입력 크기를 제한한다."""
    return max(1, (len(value.encode("utf-8")) + 3) // 4)


def _validate_summary_references(
    summary: SessionSummaryContent,
    payload: ContextSummaryRequest,
) -> None:
    source_by_id = {message.messageId: message for message in payload.sourceMessages}
    inherited_user_ids = _inherited_user_statement_ids(payload.previousSummary)
    allowed_user_ids = {
        message_id
        for message_id, message in source_by_id.items()
        if message.role == "USER"
    } | inherited_user_ids
    allowed_ids = set(source_by_id) | _all_inherited_ids(payload.previousSummary)
    for entry in summary.userStatements:
        if not set(entry.sourceMessageIds) <= allowed_user_ids:
            raise ValueError("user statement references a non-user source")
    for entries in (summary.openThreads, summary.interactionContext):
        for entry in entries:
            if not set(entry.sourceMessageIds) <= allowed_ids:
                raise ValueError("summary entry references an unknown source")


def _all_inherited_ids(summary: SessionSummaryContent | None) -> set[int]:
    if summary is None:
        return set()
    entries = summary.userStatements + summary.openThreads + summary.interactionContext
    return {message_id for entry in entries for message_id in entry.sourceMessageIds}


def _inherited_user_statement_ids(summary: SessionSummaryContent | None) -> set[int]:
    if summary is None:
        return set()
    return {
        message_id
        for entry in summary.userStatements
        for message_id in entry.sourceMessageIds
    }
