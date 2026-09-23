# BE가 전달하는 내부 토큰을 요청 본문 처리 전에 검증한다.
import secrets
import uuid


from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from app.common.observation_context import remember, scope
from app.common.failure_observation import observe, request_id, user_id, validated_user_id
from app.core.config import Settings


def register_internal_auth(app: FastAPI, settings: Settings) -> None:
    token = settings.landit_ai_internal_token
    expected = token.get_secret_value().strip().encode() if token else b""

    @app.middleware("http")
    async def require_internal_token(request: Request, call_next):
        request.state.internal_authenticated = False
        correlation = str(uuid.uuid4())
        context_token = request_id.set(correlation)
        user_context_token = user_id.set("")
        with scope(http_method=request.method, http_route="UNKNOWN",
                   learning_session_id=None, free_talk_session_id=None,
                   message_id=None, provider=None, model=None):
            try:
                # 비어 있는 설정은 구버전 BE를 먼저 교체하기 위한 전환 단계다.
                if expected and request.url.path.startswith("/api/"):
                    supplied = request.headers.get("X-Landit-Internal-Token", "").encode()
                    if not secrets.compare_digest(supplied, expected):
                        observe(workflow="internal_auth", failure_stage="authentication",
                                reason="invalid_credentials", outcome="expected_rejection")
                        return JSONResponse(status_code=401, content={
                            "success": False, "data": None,
                            "error": {"code": "UNAUTHORIZED", "message": "인증이 필요합니다."},
                        })
                    request.state.internal_authenticated = True
                    user_id.set(validated_user_id(request.headers.get("X-Landit-User-Id", "")))
                if request.url.path.startswith("/api/"):
                    try:
                        correlation = str(uuid.UUID(request.headers.get("X-Request-Id", "")))
                        request_id.set(correlation)
                    except ValueError:
                        pass
                return await call_next(request)
            except Exception as exc:
                remember(exc)
                exc._landit_request_id = correlation
                exc._landit_user_id = user_id.get()
                raise
            finally:
                request_id.reset(context_token)
                user_id.reset(user_context_token)
