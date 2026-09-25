# 요청 범위의 전체 시간 예산으로 동기 SDK의 실제 HTTP 송수신을 제한한다.
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic

import httpx

_current: ContextVar["RequestBudget | None"] = ContextVar("request_budget", default=None)


@dataclass
class RequestBudget:
    deadline: float
    per_call_seconds: float
    max_calls: int
    calls: int = 0

    def remaining(self):
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("memory_deadline_exceeded")
        return remaining


@contextmanager
def request_budget(seconds, *, per_call_seconds=20, max_calls=9):
    token = _current.set(RequestBudget(monotonic() + seconds, per_call_seconds, max_calls))
    try:
        yield
    finally:
        _current.reset(token)


def budget_client_options(timeout):
    budget = _current.get()
    if budget is None:
        return {"timeout": timeout, "max_retries": 0} if timeout is not None else {}
    limit = min(budget.remaining(), budget.per_call_seconds,
                timeout if timeout is not None else budget.per_call_seconds)
    return {"timeout": limit, "max_retries": 0,
            "http_client": httpx.Client(transport=_DeadlineTransport(budget, limit))}


def has_request_budget():
    return _current.get() is not None


class _DeadlineTransport(httpx.BaseTransport):
    def __init__(self, budget, call_limit):
        self.budget = budget
        self.call_limit = call_limit

    def handle_request(self, request):
        limit = min(self.budget.remaining(), self.call_limit)
        if self.budget.calls >= self.budget.max_calls:
            raise TimeoutError("memory_call_limit")
        self.budget.calls += 1
        try:
            return asyncio.run(self._send(request, limit))
        except TimeoutError as exc:
            raise httpx.ReadTimeout("memory_deadline_exceeded", request=request) from exc

    async def _send(self, request, limit):
        # read timeout은 청크마다 초기화되므로 전체 송수신에는 취소 가능한 별도 deadline을 둔다.
        async with asyncio.timeout(limit), httpx.AsyncClient(timeout=limit) as client:
            response = await client.request(
                request.method, request.url, headers=request.headers, content=request.read(),
            )
            headers = dict(response.headers)
            # AsyncClient가 이미 압축을 해제했으므로 바깥 Client의 중복 해제를 막는다.
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            return httpx.Response(response.status_code, headers=headers,
                                  content=response.content, request=request)
