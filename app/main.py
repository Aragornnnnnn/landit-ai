# FastAPI 애플리케이션 팩토리와 ASGI 앱을 제공하는 모듈
import logging

from fastapi import FastAPI

from app.api.conversation import router as conversation_router
from app.api.free_talk import router as free_talk_router
from app.api.health import router as health_router
from app.common.exception_handlers import register_exception_handlers
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.observability import init_metrics
from app.core.sentry import init_sentry


logger = logging.getLogger("uvicorn.error")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging()
    init_sentry(resolved_settings)

    fastapi_app = FastAPI(
        title=resolved_settings.app_name,
        docs_url=None if resolved_settings.app_env == "prod" else "/docs",
        redoc_url=None if resolved_settings.app_env == "prod" else "/redoc",
        openapi_url=None if resolved_settings.app_env == "prod" else "/openapi.json",
    )
    fastapi_app.state.settings = resolved_settings
    fastapi_app.include_router(health_router)
    fastapi_app.include_router(conversation_router)
    fastapi_app.include_router(free_talk_router)
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
