# 발음 멀티모달 호출의 구조화 출력과 형식 fallback을 담당하는 모듈
import logging
import time
from dataclasses import dataclass
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from app.core.config import Settings
from app.core.structured_output import (
    json_schema_response_format,
    structured_outputs_unsupported,
)


logger = logging.getLogger(__name__)

OutputFormat = Literal["json_schema", "json_object", "prompt"]
_FORMAT_ORDER: tuple[OutputFormat, ...] = (
    "json_schema",
    "json_object",
    "prompt",
)


@dataclass(frozen=True)
class StructuredCompletionResult:
    content: str
    output_format: OutputFormat
    response: object


def request_structured_pronunciation_completion(
    client: OpenAI,
    settings: Settings,
    *,
    request: dict,
    response_model: type[BaseModel],
    schema_name: str,
    workflow: str,
    deadline: float | None = None,
    start_format: OutputFormat = "json_schema",
) -> StructuredCompletionResult:
    """남은 시간 안에서 json_schema부터 기존 프롬프트 방식까지 시도한다."""
    format_deadline = deadline or (
        time.monotonic() + settings.pronunciation_llm_timeout_seconds
    )
    start_index = _FORMAT_ORDER.index(start_format)
    last_error: Exception | None = None
    for output_format in _FORMAT_ORDER[start_index:]:
        remaining = format_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("pronunciation structured output budget exhausted")
        current_request = dict(request)
        current_request["timeout"] = min(
            settings.pronunciation_llm_timeout_seconds,
            remaining,
        )
        if output_format == "json_schema":
            current_request["response_format"] = json_schema_response_format(
                response_model,
                name=schema_name,
            )
        elif output_format == "json_object":
            current_request["response_format"] = {"type": "json_object"}
        try:
            response = client.chat.completions.create(**current_request)
        except Exception as exc:
            last_error = exc
            if output_format == "prompt" or not structured_outputs_unsupported(exc):
                raise
            next_format = _FORMAT_ORDER[_FORMAT_ORDER.index(output_format) + 1]
            logger.warning(
                "발음 Structured Outputs 형식을 지원하지 않아 fallback합니다. "
                "event=structured_output_fallback workflow=%s provider=%s model=%s "
                "fromFormat=%s toFormat=%s",
                workflow,
                settings.llm_provider,
                settings.pronunciation_model,
                output_format,
                next_format,
            )
            continue
        content = _extract_content(response)
        return StructuredCompletionResult(content, output_format, response)
    if last_error is not None:
        raise last_error
    raise TimeoutError("pronunciation structured output budget exhausted")


def _extract_content(response) -> str:
    content = response.choices[0].message.content
    return (content or "").strip()
