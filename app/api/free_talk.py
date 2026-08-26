# 프리톡 대화 생성 HTTP API 라우터를 정의하는 모듈
from fastapi import APIRouter, Request

from app.common.errors import ApiException, ErrorCode
from app.common.exception_handlers import report_ai_fallback
from app.common.response import ApiResponse, success_response
from app.free_talk.application.conversation_service import (
    AiGenerationFailedError,
    AiResponseInvalidError,
    generate_closing,
    generate_inner_thought,
    generate_opening,
    generate_turn,
    safe_closing_response,
)
from app.free_talk.application.embedding_service import (
    generate_conversation_embeddings,
)
from app.free_talk.application.expression_service import (
    recommend_expressions,
)
from app.models.free_talk import (
    ConversationEmbeddingsRequest,
    ConversationEmbeddingsResponse,
    ExpressionRecommendationsRequest,
    ExpressionRecommendationsResponse,
    FreeTalkClosingRequest,
    FreeTalkClosingResponse,
    FreeTalkInnerThoughtRequest,
    FreeTalkInnerThoughtResponse,
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


@router.post("/inner-thought", response_model=ApiResponse[FreeTalkInnerThoughtResponse])
def create_inner_thought(
    payload: FreeTalkInnerThoughtRequest,
    request: Request,
) -> ApiResponse[FreeTalkInnerThoughtResponse]:
    return success_response(_generate(payload, request, generate_inner_thought))


@router.post("/closing", response_model=ApiResponse[FreeTalkClosingResponse])
def create_closing(
    payload: FreeTalkClosingRequest,
    request: Request,
) -> ApiResponse[FreeTalkClosingResponse]:
    try:
        response = generate_closing(payload, request.app.state.settings)
    except (AiResponseInvalidError, AiGenerationFailedError) as exc:
        report_ai_fallback(request, exc, workflow="free_talk_closing_fallback")
        response = safe_closing_response()
    return success_response(response)


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
    "/conversation-embeddings",
    response_model=ApiResponse[ConversationEmbeddingsResponse],
)
def create_conversation_embeddings(
    payload: ConversationEmbeddingsRequest,
    request: Request,
) -> ApiResponse[ConversationEmbeddingsResponse]:
    return success_response(_generate(payload, request, generate_conversation_embeddings))


def _generate(payload, request: Request, generator):
    try:
        return generator(payload, request.app.state.settings)
    except AiResponseInvalidError as exc:
        raise ApiException(502, ErrorCode.AI_RESPONSE_INVALID) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(503, ErrorCode.AI_GENERATION_FAILED) from exc
