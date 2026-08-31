# FastAPI 애플리케이션 팩토리와 ASGI 앱을 제공하는 모듈
import logging
import threading

from fastapi import FastAPI

from app.api.conversation import router as conversation_router
from app.api.free_talk import router as free_talk_router
from app.api.health import router as health_router
from app.api.pronunciation import router as pronunciation_router
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
    fastapi_app.include_router(pronunciation_router)
    register_exception_handlers(fastapi_app)
    init_metrics(fastapi_app, resolved_settings)

    def log_deployment_started() -> None:
        logger.info(
            "Landit AI 배포가 준비되었습니다. "
            "workflow=deployment_started serviceVersion=%s",
            resolved_settings.app_version,
        )

    fastapi_app.router.add_event_handler("startup", log_deployment_started)

    def warm_pronunciation_alignment() -> None:
        from app.pronunciation.alignment.forced_align import warm_up

        # 서버 기동은 막지 않고 백그라운드에서 정렬 모델을 미리 올린다.
        # daemon=True: 워밍업이 끝나기 전에 프로세스가 종료돼도 붙잡지 않는다
        threading.Thread(
            target=warm_up,
            args=(resolved_settings.pronunciation_alignment_model_path,),
            name="alignment-warmup",
            daemon=True,
        ).start()

    # 로컬·테스트(app_env=local)는 정렬 모델 워밍업이 필요 없고, 테스트에서
    # 모델(int8 ~95MB) 로드를 유발하면 안 되므로 배포 환경에서만 등록한다
    if resolved_settings.app_env != "local":
        fastapi_app.router.add_event_handler(
            "startup", warm_pronunciation_alignment
        )
    return fastapi_app


app = create_app()
