# 외부 HTTP API 공통 응답 모델과 helper를 정의하는 모듈
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.common.errors import ErrorCode

T = TypeVar("T")


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: ErrorResponse | None = None


def success_response(data: T) -> ApiResponse[T]:
    return ApiResponse[T](
        success=True,
        data=data,
        error=None,
    )


def error_response(
    error_code: ErrorCode,
    message: str | None = None,
) -> ApiResponse[None]:
    return ApiResponse[None](
        success=False,
        data=None,
        error=ErrorResponse(
            code=error_code,
            message=message or error_code.default_message,
        ),
    )
