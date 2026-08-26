# 발음 분석 HTTP API 라우터를 정의하는 모듈
from fastapi import APIRouter, Request

from app.common.errors import ApiException, ErrorCode
from app.common.response import ApiResponse, success_response
from app.models.pronunciation import (
    PronunciationAnalyzeRequest,
    PronunciationAnalyzeResponse,
)
from app.pronunciation.alignment.forced_align import AlignmentError
from app.pronunciation.application.analysis_service import (
    ReferenceAudioUnavailableError,
    analyze_pronunciation,
)
from app.pronunciation.audio import AudioDecodeError
from app.pronunciation.llm.compare import (
    PronunciationJudgmentError,
    PronunciationJudgmentInvalidError,
)


router = APIRouter(prefix="/api/v1/pronunciation", tags=["pronunciation"])


@router.post("/analyze", response_model=ApiResponse[PronunciationAnalyzeResponse])
def analyze(
    payload: PronunciationAnalyzeRequest,
    request: Request,
) -> ApiResponse[PronunciationAnalyzeResponse]:
    try:
        result = analyze_pronunciation(payload, request.app.state.settings)
    except AudioDecodeError as exc:
        raise ApiException(400, ErrorCode.INVALID_AUDIO) from exc
    except PronunciationJudgmentInvalidError as exc:
        raise ApiException(502, ErrorCode.AI_RESPONSE_INVALID) from exc
    except (
        ReferenceAudioUnavailableError,
        PronunciationJudgmentError,
        AlignmentError,
    ) as exc:
        raise ApiException(503, ErrorCode.AI_GENERATION_FAILED) from exc
    return success_response(result)
