# 프리톡 LLM의 JSON 응답 호출과 기본 계약 검증을 담당하는 모듈
import json
import logging
from json import JSONDecodeError
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.openai_client import create_openai_client
from app.core.structured_output import (
    json_schema_response_format,
    structured_outputs_unsupported,
)


logger = logging.getLogger(__name__)


class AiResponseInvalidError(Exception):
    """AI 응답이 JSON 계약을 만족하지 않을 때 발생한다."""

    def __init__(
        self,
        message: str | None = None,
        *,
        raw_content: str | None = None,
    ) -> None:
        self.reason = message or "schema_validation"
        if message is None:
            super().__init__()
        else:
            super().__init__(message)
        self.raw_content = raw_content


class AiGenerationFailedError(Exception):
    """AI 호출 자체가 실패했을 때 발생한다."""


def request_json_completion(
    *,
    settings: Settings,
    system_prompt: str,
    user_prompt: str,
    reasoning_effort: Literal["medium"] | None = None,
    response_model: type[BaseModel] | None = None,
    schema_name: str = "free_talk_json_response",
    workflow: str = "free_talk_json_completion",
    max_attempts: int = 2,
    retry_schema_violations: bool = True,
) -> dict[str, object]:
    model = _required_model(settings)
    try:
        client = create_openai_client(settings)
        request = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        if reasoning_effort is not None:
            request["extra_body"] = {"reasoning": {"effort": reasoning_effort, "exclude": True}}
            request["max_completion_tokens"] = 4096
        if response_model is None:
            request["response_format"] = {"type": "json_object"}
            completion = client.chat.completions.create(**request)
            return _parse_json_object(_extract_content(completion))

        request["response_format"] = json_schema_response_format(
            response_model,
            name=schema_name,
        )
        for attempt in range(1, max_attempts + 1):
            try:
                completion = client.chat.completions.create(**request)
            except Exception as exc:
                if not structured_outputs_unsupported(exc):
                    raise
                logger.warning(
                    "Structured Outputs를 지원하지 않아 json_object로 전환합니다. "
                    "event=structured_output_fallback workflow=%s provider=%s model=%s "
                    "fromFormat=json_schema toFormat=json_object "
                    "attempt=%s maxAttempts=%s",
                    workflow,
                    settings.llm_provider,
                    model,
                    attempt,
                    max_attempts,
                )
                request["response_format"] = {"type": "json_object"}
                try:
                    completion = client.chat.completions.create(**request)
                except Exception as fallback_exc:
                    if not structured_outputs_unsupported(fallback_exc):
                        raise
                    logger.warning(
                        "json_object를 지원하지 않아 기존 프롬프트 방식으로 전환합니다. "
                        "event=structured_output_fallback workflow=%s provider=%s "
                        "model=%s fromFormat=json_object toFormat=prompt "
                        "attempt=%s maxAttempts=%s",
                        workflow,
                        settings.llm_provider,
                        model,
                        attempt,
                        max_attempts,
                    )
                    request.pop("response_format", None)
                    completion = client.chat.completions.create(**request)
                return _parse_json_object(_extract_content(completion))
            try:
                data = _parse_json_object(_extract_content(completion))
            except AiResponseInvalidError as exc:
                logger.warning(
                    "Structured Outputs JSON 형식 검증에 실패했습니다. "
                    "event=json_format_failure workflow=%s provider=%s model=%s "
                    "reason=%s attempt=%s maxAttempts=%s",
                    workflow,
                    settings.llm_provider,
                    model,
                    str(exc),
                    attempt,
                    max_attempts,
                )
                if attempt == max_attempts:
                    raise
                logger.warning(
                    "Structured Outputs JSON 형식 오류를 재시도합니다. "
                    "event=structured_output_retry workflow=%s provider=%s model=%s "
                    "nextAttempt=%s maxAttempts=%s",
                    workflow,
                    settings.llm_provider,
                    model,
                    attempt + 1,
                    max_attempts,
                )
                continue
            try:
                response_model.model_validate(data)
            except ValidationError as exc:
                reason = exc.errors()[0]["type"] if exc.errors() else "validation_error"
                logger.warning(
                    "Structured Outputs schema 검증에 실패했습니다. "
                    "event=schema_validation_failure workflow=%s provider=%s model=%s "
                    "reason=%s attempt=%s maxAttempts=%s",
                    workflow,
                    settings.llm_provider,
                    model,
                    reason,
                    attempt,
                    max_attempts,
                )
                if retry_schema_violations and attempt < max_attempts:
                    logger.warning(
                        "Structured Outputs schema 위반을 재시도합니다. "
                        "event=structured_output_retry workflow=%s provider=%s model=%s "
                        "nextAttempt=%s maxAttempts=%s",
                        workflow,
                        settings.llm_provider,
                        model,
                        attempt + 1,
                        max_attempts,
                    )
                    continue
            return data
    except AiResponseInvalidError:
        raise
    except Exception as exc:
        logger.warning(
            "프리톡 AI 응답 생성에 실패했습니다. provider=%s model=%s",
            settings.llm_provider,
            model,
        )
        raise AiGenerationFailedError from exc

    raise AiGenerationFailedError


def _required_model(settings: Settings) -> str:
    if settings.openrouter_model is None or not settings.openrouter_model.strip():
        raise AiGenerationFailedError("OPENROUTER_MODEL is required.")
    return settings.openrouter_model


def _extract_content(completion: Any) -> str:
    try:
        content = completion.choices[0].message.content
    except (AttributeError, IndexError) as exc:
        raise AiResponseInvalidError("completion content is missing") from exc
    if not isinstance(content, str) or not content.strip():
        raise AiResponseInvalidError("completion content is blank")
    return content.strip()


def _parse_json_object(content: str) -> dict[str, object]:
    try:
        data = json.loads(content)
    except JSONDecodeError as exc:
        raise AiResponseInvalidError(
            "completion is not valid JSON",
            raw_content=content,
        ) from exc
    if not isinstance(data, dict):
        raise AiResponseInvalidError(
            "completion must be a JSON object",
            raw_content=content,
        )
    return data
