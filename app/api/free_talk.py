# 프리톡 대화 생성 HTTP API 라우터를 정의하는 모듈
from fastapi import APIRouter, Request

from app.common.errors import ApiException, ErrorCode
from app.common.response import ApiResponse, success_response
from app.free_talk.application.conversation_service import (
    AiGenerationFailedError,
    AiResponseInvalidError,
    generate_closing,
    generate_opening,
    generate_turn,
)
from app.models.free_talk import (
    FreeTalkClosingRequest,
    FreeTalkClosingResponse,
    FreeTalkOpeningRequest,
    FreeTalkOpeningResponse,
    FreeTalkTurnRequest,
    FreeTalkTurnResponse,
)


router = APIRouter(prefix="/api/v1/free-talk", tags=["free-talk"])


@router.post("/opening", response_model=ApiResponse[FreeTalkOpeningResponse])
def create_opening(
    payload: FreeTalkOpeningRequest,
    request: Request,
) -> ApiResponse[FreeTalkOpeningResponse]:
    return success_response(_generate(payload, request, generate_opening))


@router.post("/turn", response_model=ApiResponse[FreeTalkTurnResponse])
def create_turn(
    payload: FreeTalkTurnRequest,
    request: Request,
) -> ApiResponse[FreeTalkTurnResponse]:
    return success_response(_generate(payload, request, generate_turn))


@router.post("/closing", response_model=ApiResponse[FreeTalkClosingResponse])
def create_closing(
    payload: FreeTalkClosingRequest,
    request: Request,
) -> ApiResponse[FreeTalkClosingResponse]:
    return success_response(_generate(payload, request, generate_closing))


def _generate(payload, request: Request, generator):
    try:
        return generator(payload, request.app.state.settings)
    except AiResponseInvalidError as exc:
        raise ApiException(502, ErrorCode.AI_RESPONSE_INVALID) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(503, ErrorCode.AI_GENERATION_FAILED) from exc
