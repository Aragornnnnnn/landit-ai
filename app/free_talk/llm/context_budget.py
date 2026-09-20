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


def fit_context(
    payload: ContextRequest,
    budget: int,
    request_size: Callable[[ContextRequest], int],
) -> ContextRequest:
    """기존 정책은 그대로 두고 초과 요청만 원문 경계를 따라 복사·축소한다."""
    if payload.contextPolicyVersion is None or request_size(payload) <= budget:
        return payload
    history = payload.conversationHistory
    protected = next((i for i in range(len(history) - 2, -1, -1)
                      if history[i].role == "AI"), len(history) - 1)
    boundaries = sorted({0, protected} | {
        i + 1 for i in range(protected) if history[i].role == "AI"
    })

    def candidate(index: int) -> ContextRequest:
        return payload.model_copy(update={
            "conversationHistory": history[boundaries[index]:],
            "sessionSummary": None,
            "historyIncomplete": True,
        })

    if request_size(candidate(len(boundaries) - 1)) > budget:
        raise AiContextTooLargeError("free-talk context exceeds token budget")
    low, high = 0, len(boundaries) - 1
    while low < high:
        middle = (low + high) // 2
        if request_size(candidate(middle)) <= budget:
            high = middle
        else:
            low = middle + 1
    return candidate(low)
