# FastAPI 예외를 공통 API 응답으로 변환하는 핸들러 등록 모듈
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.errors import ApiException, ErrorCode
from app.common.response import error_response


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
    return _error_json_response(
        status_code=400,
        error_code=ErrorCode.INVALID_REQUEST,
    )


async def api_exception_handler(
    request: Request,
    exc: ApiException,
) -> JSONResponse:
    return _error_json_response(
        status_code=exc.status_code,
        error_code=exc.error_code,
        message=exc.message,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else None
    return _error_json_response(
        status_code=exc.status_code,
        error_code=ErrorCode.INVALID_REQUEST,
        message=message,
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _error_json_response(
        status_code=500,
        error_code=ErrorCode.INTERNAL_SERVER_ERROR,
    )


def _error_json_response(
    status_code: int,
    error_code: ErrorCode,
    message: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_response(error_code, message).model_dump(mode="json"),
    )
