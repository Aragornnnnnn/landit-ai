# 프리톡 LLM의 JSON 응답 호출과 기본 계약 검증을 담당하는 모듈
import json
import logging
from json import JSONDecodeError
from typing import Any

from app.core.config import Settings
from app.core.openai_client import create_openai_client


logger = logging.getLogger(__name__)


class AiResponseInvalidError(Exception):
    """AI 응답이 JSON 계약을 만족하지 않을 때 발생한다."""

    def __init__(
        self,
        message: str | None = None,
        *,
        raw_content: str | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_content = raw_content


class AiGenerationFailedError(Exception):
    """AI 호출 자체가 실패했을 때 발생한다."""


def request_json_completion(
    *,
    settings: Settings,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, object]:
    model = _required_model(settings)
    try:
        client = create_openai_client(settings)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as exc:
        logger.warning(
            "프리톡 AI 응답 생성에 실패했습니다. provider=%s model=%s",
            settings.llm_provider,
            model,
        )
        raise AiGenerationFailedError from exc

    return _parse_json_object(_extract_content(completion))


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
