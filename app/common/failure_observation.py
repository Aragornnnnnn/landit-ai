# 실패의 기능 영향과 복구 결과를 민감정보 없이 로그·메트릭·Sentry에 기록한다.
import logging
from contextvars import ContextVar

import sentry_sdk
from opentelemetry import metrics

from app.common.observation_context import for_failure
from app.common.failure_diagnostics import exception_diagnostics

logger = logging.getLogger(__name__)
request_id: ContextVar[str] = ContextVar("failure_request_id", default="")
user_id: ContextVar[str] = ContextVar("failure_user_id", default="")
_counter = metrics.get_meter(__name__).create_counter("landit.failure.outcomes")


def validated_user_id(value: str) -> str:
    """인증된 BE가 제공한 양의 Long 사용자 ID만 허용한다."""
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
            or not 1 <= len(value) <= 19 or value.startswith("0")):
        return ""
    return value if int(value) <= 9223372036854775807 else ""


def configure_failure_metrics(provider) -> None:
    global _counter
    _counter = provider.get_meter(__name__).create_counter("landit.failure.outcomes")


def _chain(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__


def has_defect(exc: Exception | None) -> bool:
    """알려진 출력 계약/외부 호출 오류 이외의 원인을 결함으로 보수적으로 남긴다."""
    provider_failure = False
    for cause in _chain(exc):
        name = type(cause).__name__
        if name in {"AiResponseInvalidError", "InnerThoughtContractError"}:
            if (
                getattr(cause, "reason", None) in {"completion_content_missing", "completion content is missing"}
                and isinstance(cause.__cause__, (AttributeError, IndexError))
            ):
                return False  # 알려진 provider 출력 필드 누락이며 코드 오류 일반 제외가 아니다.
            if cause.__cause__ is None:
                return False
            continue
        if name in {"ValidationError", "JSONDecodeError", "InnerThoughtContractError"}:
            return False
        if name == "AiGenerationFailedError":
            if cause.__cause__ is None:
                return bool(cause.args)  # 필수 모델 누락 등 명시적 설정 오류.
            continue
        if type(cause).__module__.startswith(("openai", "httpx", "httpcore")):
            provider_failure = True
            if name in {"UnsupportedProtocol", "InvalidURL", "LocalProtocolError"}:
                return True
            if getattr(cause, "status_code", None) in {401, 403, 404}:
                return True
            if cause.__cause__ is not None:
                continue
            return False
        if provider_failure and isinstance(cause, OSError) and not isinstance(cause, (FileNotFoundError, PermissionError)):
            return False  # SDK가 감싼 네트워크 연결 오류는 fallback 결과로 결정한다.
        return True
    return False


def observe(*, workflow: str, failure_stage: str, reason: str,
            outcome: str, exc: Exception | None = None, attempt: int = 1) -> None:
    """호출자가 확정한 기능 결과를 기록한다. 원문/예외 문자열은 기록하지 않는다."""
    if outcome == "recovered" and has_defect(exc):
        outcome = "failed"
        reason = "recovered_with_defect"
    tags = {
        "workflow": workflow, "failure_stage": failure_stage, "reason": reason,
        "outcome": outcome, "recovered": str(outcome == "recovered").lower(),
        "attempt": str(attempt),
    }
    _counter.add(1, {k: v for k, v in tags.items() if k != "attempt"})
    tags.update(for_failure(exc))
    correlation = getattr(exc, "_landit_request_id", request_id.get())
    actor = getattr(exc, "_landit_user_id", user_id.get())
    if correlation:
        tags["request_id"] = correlation
    log = logger.error if outcome == "failed" else logger.warning
    diagnostics = exception_diagnostics(exc)
    log("failure_observation %s diagnostics=%s",
        " ".join(f"{k}={v}" for k, v in tags.items()), diagnostics)
    if exc is not None:
        exc._landit_observation = tags
        exc._landit_user_id = actor
    if outcome == "failed":
        failure = exc
        if failure is None:
            try:
                raise RuntimeError("functional_failure")
            except RuntimeError as synthetic:
                failure = synthetic
                failure._landit_synthetic = True
        failure._landit_observation = tags
        failure._landit_user_id = actor
        sentry_sdk.capture_exception(failure, tags=tags)
