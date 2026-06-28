# FastAPI 애플리케이션 팩토리와 ASGI 앱을 제공하는 모듈
from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import Settings
from app.core.sentry import init_sentry


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    init_sentry(resolved_settings)

    fastapi_app = FastAPI(title=resolved_settings.app_name)
    fastapi_app.include_router(health_router)
    return fastapi_app


app = create_app()
