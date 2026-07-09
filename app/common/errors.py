# 공통 API 에러 코드와 예외 타입을 정의하는 모듈
from enum import Enum


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    AI_RESPONSE_INVALID = "AI_RESPONSE_INVALID"
    AI_GENERATION_FAILED = "AI_GENERATION_FAILED"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"

    @property
    def default_message(self) -> str:
        messages = {
            ErrorCode.INVALID_REQUEST: "요청이 올바르지 않습니다.",
            ErrorCode.AI_RESPONSE_INVALID: "AI 응답 형식이 올바르지 않습니다.",
            ErrorCode.AI_GENERATION_FAILED: "AI 응답 생성에 실패했습니다.",
            ErrorCode.INTERNAL_SERVER_ERROR: "서버 내부 오류가 발생했습니다.",
        }
        return messages[self]


class ApiException(Exception):
    def __init__(
        self,
        status_code: int,
        error_code: ErrorCode,
        message: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.message = message or error_code.default_message
        super().__init__(self.message)
