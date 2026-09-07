# Pydantic 모델을 OpenRouter Structured Outputs 요청 형식으로 변환하는 모듈
from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def json_schema_response_format(
    response_model: type[BaseModel],
    *,
    name: str,
) -> dict[str, object]:
    """OpenAI 호환 strict JSON Schema response_format을 생성한다."""
    schema = deepcopy(response_model.model_json_schema(mode="validation"))
    _make_schema_strict(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


def structured_outputs_unsupported(error: Exception) -> bool:
    """Provider가 Structured Outputs 자체를 거부한 오류인지 판별한다."""
    status_code = getattr(error, "status_code", None)
    if status_code not in {400, 404, 422}:
        return False
    message = str(error).casefold()
    format_marker = any(
        marker in message
        for marker in ("response_format", "json_schema", "structured output")
    )
    unsupported_marker = any(
        marker in message
        for marker in ("unsupported", "not supported", "no endpoints", "invalid")
    )
    no_compatible_endpoint = (
        status_code == 404
        and "no endpoints found that can handle the requested parameters" in message
    )
    return (format_marker and unsupported_marker) or no_compatible_endpoint


def _make_schema_strict(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("default", None)
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(properties)
        for value in node.values():
            _make_schema_strict(value)
    elif isinstance(node, list):
        for value in node:
            _make_schema_strict(value)
