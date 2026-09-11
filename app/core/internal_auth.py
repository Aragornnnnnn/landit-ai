# BE가 전달하는 내부 토큰을 요청 본문 처리 전에 검증한다.
import secrets

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from app.core.config import Settings


def register_internal_auth(app: FastAPI, settings: Settings) -> None:
    token = settings.landit_ai_internal_token
    expected = token.get_secret_value().strip().encode() if token else b""

    @app.middleware("http")
    async def require_internal_token(request: Request, call_next):
        # 비어 있는 설정은 구버전 BE를 먼저 교체하기 위한 전환 단계다.
        if expected and request.url.path.startswith("/api/"):
            supplied = request.headers.get("X-Landit-Internal-Token", "").encode()
            if not secrets.compare_digest(supplied, expected):
                return JSONResponse(status_code=401, content={
                    "success": False, "data": None,
                    "error": {"code": "UNAUTHORIZED", "message": "인증이 필요합니다."},
                })
        return await call_next(request)
