# 수준 평가의 호출별 메타데이터와 최초 검증 실패를 원문 없이 기록한다.
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

from openai import APITimeoutError

from app.common.failure_diagnostics import exception_diagnostics
from app.common.failure_observation import request_id
from app.common.observation_context import for_failure

logger = logging.getLogger(__name__)
_current: ContextVar[dict | None] = ContextVar("assessment_observation", default=None)
_FINISH_REASONS = {"stop", "length", "content_filter", "tool_calls", "function_call", "error"}
_NATIVE_REASONS = {"completed", "max_output_tokens", "stop", "length", "content_filter"}


def observe_assessment(function):
    """요청 단위로 격리하고, 실패한 최초 평가와 재시도를 한 로그에 함께 남긴다."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        state = {"stage": 1, "calls": [], "validations": []}
        token = _current.set(state)
        started = perf_counter()
        try:
            result = function(*args, **kwargs)
            state["outcome"] = "model" if result.levelAssessment is not None else "fallback"
            return result
        except Exception as exc:
            state["outcome"] = "failed"
            state["terminal_failure"] = exception_diagnostics(exc)
            raise
        finally:
            _current.reset(token)
            state["elapsed_ms"] = round((perf_counter() - started) * 1000)
            state["request_id"] = request_id.get()
            state["context"] = for_failure()
            log = logger.warning if state["validations"] or "terminal_failure" in state else logger.info
            log("assessment_diagnostics %s", json.dumps(state, ensure_ascii=True))
    return wrapped


def begin_core_retry() -> None:
    state = _current.get()
    if state is not None:
        state["stage"] = 2


def record_validation_failure(exc: Exception) -> None:
    state = _current.get()
    if state is not None:
        state["validations"].append({"stage": state["stage"], **exception_diagnostics(exc)})


def _number(value) -> int | None:
    return value if type(value) is int and 0 <= value <= 10**12 else None


def _identifier(value) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(
        r"(?:gen-|req[-_]|resp_)[A-Za-z0-9_-]{1,128}", value,
    ) else None


def completion_metadata(completion) -> dict:
    """응답 본문과 임의 문자열을 제외하고 알려진 식별자와 숫자만 추출한다."""
    choices = getattr(completion, "choices", None)
    choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
    usage = getattr(completion, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    finish = getattr(choice, "finish_reason", None)
    native_finish = getattr(choice, "native_finish_reason", None)
    return {
        "generation_id": _identifier(getattr(completion, "id", None)),
        "provider_request_id": _identifier(getattr(completion, "_request_id", None)),
        "finish_reason": finish if isinstance(finish, str) and finish in _FINISH_REASONS else None,
        "native_finish_reason": (
            native_finish
            if isinstance(native_finish, str) and native_finish in _NATIVE_REASONS else None
        ),
        "prompt_tokens": _number(getattr(usage, "prompt_tokens", None)),
        "completion_tokens": _number(getattr(usage, "completion_tokens", None)),
        "reasoning_tokens": _number(getattr(details, "reasoning_tokens", None)),
    }


@contextmanager
def observe_completion(max_tokens: int, response_format: dict | None):
    """실제 provider 호출마다 순번·형식·소요 시간과 파싱 실패를 보존한다."""
    state = _current.get()
    if state is None:
        yield None
        return
    kind = response_format.get("type") if isinstance(response_format, dict) else None
    call = {
        "attempt": len(state["calls"]) + 1, "stage": state["stage"],
        "max_tokens": max_tokens,
        "format": kind if kind in ("json_schema", "json_object") else "prompt",
    }
    state["calls"].append(call)
    started = perf_counter()
    try:
        yield call
    except Exception as exc:
        call["failure"] = exception_diagnostics(exc) or {
            "provider_error": "timeout" if isinstance(exc, APITimeoutError) else "request_failed",
        }
        raise
    finally:
        call["elapsed_ms"] = round((perf_counter() - started) * 1000)
