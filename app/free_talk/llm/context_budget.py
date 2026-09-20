# 프리톡의 전체 요청 크기를 추정하고 원문을 보존하는 축소 경계를 선택한다.
import json
from collections.abc import Callable
from typing import TypeVar

from app.models.free_talk import (
    FreeTalkClosingRequest,
    FreeTalkInnerThoughtRequest,
    FreeTalkTurnRequest,
)

ContextRequest = TypeVar(
    "ContextRequest", FreeTalkTurnRequest, FreeTalkInnerThoughtRequest, FreeTalkClosingRequest,
)


class AiContextTooLargeError(Exception):
    """직전 AI와 현재 USER 원문도 입력 예산에 들어가지 않을 때 발생한다."""


def estimate_request_tokens(system: str, user: str, response_format: dict) -> int:
    """직렬화된 system·user·schema와 512토큰 여유분의 바이트 기반 추정치다."""
    serialized = json.dumps({"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], "response_format": response_format}, ensure_ascii=False)
    return (len(serialized.encode("utf-8")) + 3) // 4 + 512
