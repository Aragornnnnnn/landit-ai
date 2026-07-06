# 공통 API 에러 코드를 정의하는 모듈
from enum import Enum


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    AI_GENERATION_FAILED = "AI_GENERATION_FAILED"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"

    @property
    def default_message(self) -> str:
        messages = {
            ErrorCode.INVALID_REQUEST: "요청이 올바르지 않습니다.",
            ErrorCode.AI_GENERATION_FAILED: "AI 생성에 실패했습니다.",
            ErrorCode.INTERNAL_SERVER_ERROR: "서버 내부 오류가 발생했습니다.",
        }
        return messages[self]
