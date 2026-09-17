# FastAPI 예외를 공통 API 응답으로 변환하는 핸들러 등록 모듈
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.failure_observation import observe
from app.common.errors import ApiException, ErrorCode
from app.common.response import error_response


_AI_FAILURE_CODES = {
    ErrorCode.AI_RESPONSE_INVALID,
    ErrorCode.AI_GENERATION_FAILED,
}


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        RequestValidationError,
        request_validation_error_handler,
    )
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    _observe_request_error(request, exc, "request_contract")
    return _error_json_response(
        status_code=400,
        error_code=ErrorCode.INVALID_REQUEST,
    )


async def api_exception_handler(
    request: Request,
    exc: ApiException,
) -> JSONResponse:
    if exc.error_code in _AI_FAILURE_CODES:
        _report_ai_failure(request, exc)
    elif exc.error_code == ErrorCode.MESSAGE_FEEDBACK_NOT_READY:
        observe(workflow="session_feedback", failure_stage="readiness",
                reason="not_ready", outcome="expected_rejection", exc=exc)
    elif exc.status_code >= 500:
        observe(workflow="api", failure_stage="execution",
                reason="server_failure", outcome="failed", exc=exc)
    else:
        _observe_request_error(request, exc, "request_contract")
    return _error_json_response(
        status_code=exc.status_code,
        error_code=exc.error_code,
        message=exc.message,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if exc.status_code >= 500:
        observe(workflow="http", failure_stage="execution",
                reason="server_failure", outcome="failed", exc=exc)
    else:
        _observe_request_error(request, exc, "http_contract")
    message = exc.detail if isinstance(exc.detail, str) else None
    return _error_json_response(
        status_code=exc.status_code,
        error_code=ErrorCode.INVALID_REQUEST,
        message=message,
        headers=exc.headers,
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    observe(workflow="api", failure_stage="execution",
            reason="unexpected_exception", outcome="failed", exc=exc)
    return _error_json_response(
        status_code=500,
        error_code=ErrorCode.INTERNAL_SERVER_ERROR,
    )


def _observe_request_error(request: Request, exc: Exception, reason: str) -> None:
    trusted = getattr(request.state, "internal_authenticated", False)
    observe(workflow="api", failure_stage="request_validation", reason=reason,
            outcome="failed" if trusted else "expected_rejection", exc=exc)


def _report_ai_failure(request: Request, exc: ApiException) -> None:
    observe(workflow="ai_request_failed", failure_stage="generation",
            reason=exc.error_code.value.lower(), outcome="failed", exc=exc)


def report_ai_fallback(request: Request, exc: Exception, *, workflow: str) -> None:
    observe(workflow=workflow, failure_stage="generation", reason="safe_fallback",
            outcome="recovered", exc=exc)


def _error_json_response(
    status_code: int,
    error_code: ErrorCode,
    message: str | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content=error_response(error_code, message).model_dump(mode="json"),
    )
