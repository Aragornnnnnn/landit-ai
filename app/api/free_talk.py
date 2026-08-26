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
    generate_memory_query_embedding,
)
from app.free_talk.application.expression_service import (
    recommend_expressions,
)
from app.free_talk.application.memory_service import (
    generate_memory_candidates,
    generate_memory_resolution,
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
    MemoryCandidatesRequest,
    MemoryCandidatesResponse,
    MemoryQueryEmbeddingRequest,
    MemoryQueryEmbeddingResponse,
    MemoryResolutionRequest,
    MemoryResolutionResponse,
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


@router.post(
    "/memory-candidates",
    response_model=ApiResponse[MemoryCandidatesResponse],
)
def create_memory_candidates(
    payload: MemoryCandidatesRequest,
    request: Request,
) -> ApiResponse[MemoryCandidatesResponse]:
    """완료된 프리톡의 장기기억 저장 후보를 추출한다.

    Args:
        payload: 장기기억 후보 추출 요청.
        request: 애플리케이션 설정을 보유한 FastAPI 요청.
    Returns:
        검증된 장기기억 후보와 임베딩을 담은 성공 응답.
    Raises:
        ApiException: AI 응답이 잘못되었으면 502, AI 호출이 실패했으면
            503을 발생시킨다.
    """
    return success_response(_generate(payload, request, generate_memory_candidates))


@router.post(
    "/memory-resolution",
    response_model=ApiResponse[MemoryResolutionResponse],
)
def create_memory_resolution(
    payload: MemoryResolutionRequest,
    request: Request,
) -> ApiResponse[MemoryResolutionResponse]:
    """장기기억 후보별 저장 상태를 판정한다.

    Args:
        payload: 후보와 후보별 비교 대상 장기기억을 담은 상태 판정
            요청.
        request: 애플리케이션 설정을 보유한 FastAPI 요청.
    Returns:
        후보별 상태 판정을 담은 성공 응답.
    Raises:
        ApiException: AI 응답이 잘못되었으면 502, AI 호출이 실패했으면
            503을 발생시킨다.
    """
    return success_response(_generate(payload, request, generate_memory_resolution))


@router.post(
    "/memory-query-embedding",
    response_model=ApiResponse[MemoryQueryEmbeddingResponse],
)
def create_memory_query_embedding(
    payload: MemoryQueryEmbeddingRequest,
    request: Request,
) -> ApiResponse[MemoryQueryEmbeddingResponse]:
    return success_response(_generate(payload, request, generate_memory_query_embedding))


def _generate(payload, request: Request, generator):
    try:
        return generator(payload, request.app.state.settings)
    except AiResponseInvalidError as exc:
        raise ApiException(502, ErrorCode.AI_RESPONSE_INVALID) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(503, ErrorCode.AI_GENERATION_FAILED) from exc
