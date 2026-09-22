# 명시적·자동 Sentry 수집에 동일한 전송 정책과 민감정보 제거를 적용한다.
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.openai import OpenAIIntegration

from app.core.config import Settings
from app.common.failure_observation import request_id

_SAFE_TAGS = {"workflow", "failure_stage", "reason", "outcome", "recovered", "attempt", "request_id"}
_FRAME_FIELDS = {"filename", "function", "module", "lineno", "in_app"}


def scrub_sensitive_request_data(event: dict, hint: dict) -> dict | None:
    """예외 메시지/본문/로컬변수 대신 원인 타입과 코드 위치만 전송한다."""
    # 이미 패치된 SDK integration이 남아 있어도 provider 중간 이벤트는 최종 경계에 맡긴다.
    if any((value.get("mechanism") or {}).get("type") == "openai"
           for value in event.get("exception", {}).get("values", [])):
        return None
    info = hint.get("exc_info")
    exc = info[1] if info else None
    observation = getattr(exc, "_landit_observation", None)
    if observation and observation["outcome"] != "failed":
        return None
    if getattr(exc, "_landit_sent", False):
        return None
    if exc is not None:
        exc._landit_sent = True
    safe = {key: event[key] for key in (
        "event_id", "timestamp", "level", "platform", "release", "environment", "sdk",
    ) if key in event}
    tags = observation or {
        "workflow": "unhandled", "failure_stage": "execution", "reason": "unexpected_exception",
        "outcome": "failed", "recovered": "false", "attempt": "1",
    }
    tags = dict(tags)
    correlation = getattr(exc, "_landit_request_id", None) or request_id.get()
    if correlation and "request_id" not in tags:
        tags["request_id"] = correlation
    safe["tags"] = {key: value for key, value in tags.items() if key in _SAFE_TAGS}
    if getattr(exc, "_landit_synthetic", False):
        safe["fingerprint"] = ["functional_failure", tags["workflow"], tags["failure_stage"], tags["reason"]]
    values = []
    for value in event.get("exception", {}).get("values", []):
        clean = {k: value[k] for k in ("type", "module") if k in value}
        clean["value"] = "[Filtered]"
        clean["stacktrace"] = {"frames": [
            {k: v for k, v in frame.items() if k in _FRAME_FIELDS}
            for frame in value.get("stacktrace", {}).get("frames", [])
        ]}
        values.append(clean)
    if values:
        safe["exception"] = {"values": values}
    else:
        safe["message"] = "unclassified_server_failure"
    return safe


def init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[LoggingIntegration(event_level=None)],
        # 호출 중간 오류는 재시도/복구 결과를 모른다. 기능 종료 경계에서만 보고한다.
        disabled_integrations=[OpenAIIntegration],
        before_send=scrub_sensitive_request_data,
        include_local_variables=False,
        max_request_body_size="never",
        send_default_pii=False,
    )
