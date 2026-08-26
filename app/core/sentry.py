# Sentry 에러 추적 초기화를 담당하는 모듈
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from app.core.config import Settings

# 유저 음성 등 이벤트에 실려서는 안 되는 요청 필드
_SENSITIVE_REQUEST_FIELDS = ("userAudio",)


def scrub_sensitive_request_data(event: dict, hint: dict) -> dict:
    request_data = event.get("request", {}).get("data")
    if isinstance(request_data, dict):
        for field in _SENSITIVE_REQUEST_FIELDS:
            if field in request_data:
                request_data[field] = "[Filtered]"
    return event


def init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[LoggingIntegration(event_level=None)],
        before_send=scrub_sensitive_request_data,
    )
