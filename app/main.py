# FastAPI 애플리케이션 팩토리와 ASGI 앱을 제공하는 모듈
import logging

from fastapi import FastAPI

from app.api.conversation import router as conversation_router
from app.api.health import router as health_router
from app.common.exception_handlers import register_exception_handlers
from app.core.config import Settings
from app.core.observability import init_metrics
from app.core.sentry import init_sentry


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    init_sentry(resolved_settings)

    fastapi_app = FastAPI(title=resolved_settings.app_name)
    fastapi_app.state.settings = resolved_settings
    fastapi_app.include_router(health_router)
    fastapi_app.include_router(conversation_router)
    register_exception_handlers(fastapi_app)
    init_metrics(fastapi_app, resolved_settings)

    def log_deployment_started() -> None:
        logger.info(
            "Landit AI 배포가 준비되었습니다. "
            "workflow=deployment_started serviceVersion=%s",
            resolved_settings.app_version,
        )

    fastapi_app.router.add_event_handler("startup", log_deployment_started)
    return fastapi_app


app = create_app()
