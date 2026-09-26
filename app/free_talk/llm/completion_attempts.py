# 기억 LLM 호출의 본문 없는 시도별 진단과 출력 한도 검사를 담당한다.
import json
import logging
import re
from time import monotonic

from openai import APITimeoutError

from app.common.failure_diagnostics import SAFE_REASONS
from app.common.failure_observation import request_id
from app.core.structured_output import structured_outputs_unsupported
from app.core.request_budget import has_request_budget

logger = logging.getLogger(__name__)


class CompletionAttempts:
    def __init__(self, workflow):
        self.workflow = workflow
        self.enabled = workflow.startswith("free_talk_memory_") or has_request_budget()
        self.attempts = []
        self.first_failure = None

    def create(self, client, request):
        if not self.enabled:
            return client.chat.completions.create(**request)
        started = monotonic()
        entry = {"attempt": len(self.attempts) + 1}
        self.attempts.append(entry)
        try:
            completion = client.chat.completions.create(**request)
            entry.update(_metadata(completion))
            return completion
        except Exception as exc:
            entry["request_id"] = _request_identifier(getattr(exc, "request_id", None))
            reason = ("format_unsupported" if structured_outputs_unsupported(exc)
                      else "provider_timeout" if isinstance(exc, APITimeoutError)
                      else "provider_error")
            self.failure(reason)
            raise
        finally:
            entry["elapsed_ms"] = round((monotonic() - started) * 1000)

    def failure(self, reason):
        if self.enabled and self.attempts:
            safe = reason if reason in SAFE_REASONS or reason in {
                "format_unsupported", "provider_timeout", "provider_error",
            } else "schema_validation"
            self.first_failure = self.first_failure or safe
            self.attempts[-1]["failure"] = safe

    def exhausted(self):
        return self.enabled and (
            self.attempts[-1].get("finish_reason") == "length"
            or self.attempts[-1].get("native_finish_reason") in {"max_output_tokens", "max_tokens"}
        )

    def log(self):
        if self.enabled:
            log = logger.warning if self.first_failure else logger.info
            log("event=memory_completion_attempts workflow=%s request_id=%s diagnostics=%s",
                self.workflow, request_id.get(),
                json.dumps({"first_failure": self.first_failure, "attempts": self.attempts}))


def _metadata(completion):
    choices = getattr(completion, "choices", None)
    choice = choices[0] if isinstance(choices, list) and choices else None
    usage = getattr(completion, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    return {
        "finish_reason": _reason(getattr(choice, "finish_reason", None)),
        "native_finish_reason": _reason(getattr(choice, "native_finish_reason", None)),
        "completion_tokens": _count(getattr(usage, "completion_tokens", None)),
        "reasoning_tokens": _count(getattr(details, "reasoning_tokens", None)),
        "generation_id": _identifier(getattr(completion, "id", None), r"gen-[\w-]{1,120}"),
        "request_id": _request_identifier(getattr(completion, "_request_id", None)),
    }


def _reason(value):
    return value if isinstance(value, str) and value in {
        "stop", "length", "max_output_tokens", "max_tokens", "end_turn",
        "stop_sequence", "tool_calls", "content_filter", "error",
    } else None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _identifier(value, pattern):
    return value if isinstance(value, str) and re.fullmatch(pattern, value, re.ASCII) else None


def _request_identifier(value):
    return _identifier(value, r"(?:req[_-][\w-]{1,120}|[0-9a-f-]{36})")
