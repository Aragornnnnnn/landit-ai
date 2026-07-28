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
from app.free_talk.application.expression_service import (
    generate_expression_learning_content,
    recommend_expressions,
)
from app.models.free_talk import (
    ExpressionLearningContentRequest,
    ExpressionLearningContentResponse,
    ExpressionRecommendationsRequest,
    ExpressionRecommendationsResponse,
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


@router.post(
    "/expression-recommendations",
    response_model=ApiResponse[ExpressionRecommendationsResponse],
)
def create_expression_recommendations(
    payload: ExpressionRecommendationsRequest,
    request: Request,
) -> ApiResponse[ExpressionRecommendationsResponse]:
    return success_response(_generate(payload, request, recommend_expressions))


@router.post(
    "/expression-learning-content",
    response_model=ApiResponse[ExpressionLearningContentResponse],
)
def create_expression_learning_content(
    payload: ExpressionLearningContentRequest,
    request: Request,
) -> ApiResponse[ExpressionLearningContentResponse]:
    return success_response(
        _generate(payload, request, generate_expression_learning_content),
    )


def _generate(payload, request: Request, generator):
    try:
        return generator(payload, request.app.state.settings)
    except AiResponseInvalidError as exc:
        raise ApiException(502, ErrorCode.AI_RESPONSE_INVALID) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(503, ErrorCode.AI_GENERATION_FAILED) from exc
