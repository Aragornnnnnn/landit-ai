# 대화 생성 API 라우터를 정의하는 모듈
from fastapi import APIRouter, Request

from app.common.errors import ApiException, ErrorCode
from app.common.response import ApiResponse, success_response
from app.models.conversation import (
    ClosingMessageRequest,
    ClosingMessageResponse,
    InnerThoughtRequest,
    InnerThoughtResponse,
    MessageFeedbackRequest,
    MessageFeedbackResponse,
    NextMessageRequest,
    NextMessageResponse,
    SessionFeedbackRequest,
    SessionFeedbackResponse,
)
from app.conversation.application.next_message_service import (
    AiGenerationFailedError,
    AiResponseInvalidError,
    MessageFeedbackNotReadyError,
    generate_closing_message,
    generate_inner_thought,
    generate_message_feedback,
    generate_next_message,
    generate_session_feedback,
)

router = APIRouter(prefix="/api/v1/conversation", tags=["conversation"])


@router.post(
    "/next-message",
    response_model=ApiResponse[NextMessageResponse],
)
def create_next_message(
    payload: NextMessageRequest,
    request: Request,
) -> ApiResponse[NextMessageResponse]:
    try:
        response = generate_next_message(payload, request.app.state.settings)
    except AiResponseInvalidError as exc:
        raise ApiException(
            status_code=502,
            error_code=ErrorCode.AI_RESPONSE_INVALID,
        ) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(
            status_code=503,
            error_code=ErrorCode.AI_GENERATION_FAILED,
        ) from exc

    return success_response(response)


@router.post(
    "/inner-thought",
    response_model=ApiResponse[InnerThoughtResponse],
)
def create_inner_thought(
    payload: InnerThoughtRequest,
    request: Request,
) -> ApiResponse[InnerThoughtResponse]:
    try:
        response = generate_inner_thought(payload, request.app.state.settings)
    except AiResponseInvalidError as exc:
        raise ApiException(
            status_code=502,
            error_code=ErrorCode.AI_RESPONSE_INVALID,
        ) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(
            status_code=503,
            error_code=ErrorCode.AI_GENERATION_FAILED,
        ) from exc

    return success_response(response)


@router.post(
    "/closing-message",
    response_model=ApiResponse[ClosingMessageResponse],
)
def create_closing_message(
    payload: ClosingMessageRequest,
    request: Request,
) -> ApiResponse[ClosingMessageResponse]:
    try:
        response = generate_closing_message(payload, request.app.state.settings)
    except AiResponseInvalidError as exc:
        raise ApiException(
            status_code=502,
            error_code=ErrorCode.AI_RESPONSE_INVALID,
        ) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(
            status_code=503,
            error_code=ErrorCode.AI_GENERATION_FAILED,
            message="대화 종료 메시지 생성에 실패했습니다.",
        ) from exc

    return success_response(response)


@router.post(
    "/message-feedback",
    response_model=ApiResponse[MessageFeedbackResponse],
    status_code=202,
)
def create_message_feedback(
    payload: MessageFeedbackRequest,
    request: Request,
) -> ApiResponse[MessageFeedbackResponse]:
    try:
        response = generate_message_feedback(payload, request.app.state.settings)
    except AiResponseInvalidError as exc:
        raise ApiException(
            status_code=502,
            error_code=ErrorCode.AI_RESPONSE_INVALID,
        ) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(
            status_code=503,
            error_code=ErrorCode.AI_GENERATION_FAILED,
        ) from exc

    return success_response(response)


@router.post(
    "/session-feedback",
    response_model=ApiResponse[SessionFeedbackResponse],
)
def create_session_feedback(
    payload: SessionFeedbackRequest,
    request: Request,
) -> ApiResponse[SessionFeedbackResponse]:
    try:
        response = generate_session_feedback(payload, request.app.state.settings)
    except MessageFeedbackNotReadyError as exc:
        raise ApiException(
            status_code=409,
            error_code=ErrorCode.MESSAGE_FEEDBACK_NOT_READY,
        ) from exc
    except AiResponseInvalidError as exc:
        raise ApiException(
            status_code=502,
            error_code=ErrorCode.AI_RESPONSE_INVALID,
        ) from exc
    except AiGenerationFailedError as exc:
        raise ApiException(
            status_code=503,
            error_code=ErrorCode.AI_GENERATION_FAILED,
            message="세션 최종 피드백 생성에 실패했습니다.",
        ) from exc

    return success_response(response)
