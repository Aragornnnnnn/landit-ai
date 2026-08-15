# 프리톡 대화 발췌 문장의 임베딩 호출과 기본 계약 검증을 담당하는 모듈
import logging
import math

from app.core.config import Settings
from app.core.openai_client import create_openai_client
from app.free_talk.llm.json_completion import (
    AiGenerationFailedError,
    AiResponseInvalidError,
)


logger = logging.getLogger(__name__)

# 표현 측 임베딩(LAN-291)과 코사인 유사도가 성립하려면 같은 모델로 고정해야 한다.
EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


def request_embeddings(
    *,
    settings: Settings,
    texts: list[str],
) -> list[list[float]]:
    try:
        client = create_openai_client(settings)
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    except Exception as exc:
        logger.warning(
            "프리톡 대화 임베딩 생성에 실패했습니다. provider=%s model=%s",
            settings.llm_provider,
            EMBEDDING_MODEL,
        )
        raise AiGenerationFailedError from exc

    return _validated_vectors(response, expected_count=len(texts))


def _validated_vectors(response, *, expected_count: int) -> list[list[float]]:
    try:
        # 응답 순서는 보장되지 않으므로 index 기준으로 재정렬해 입력 문장과 짝을 맞춘다.
        items = sorted(response.data, key=lambda item: item.index)
        indices = [item.index for item in items]
        vectors = [list(item.embedding) for item in items]
    except (AttributeError, TypeError) as exc:
        raise AiResponseInvalidError("embedding response is malformed") from exc

    if any(type(index) is not int for index in indices) or indices != list(
        range(expected_count),
    ):
        raise AiResponseInvalidError("embedding indices must match input order")
    if len(vectors) != expected_count:
        raise AiResponseInvalidError("embedding count must match input count")
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise AiResponseInvalidError("embedding dimensions must be 1536")
        if any(
            not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in vector
        ):
            raise AiResponseInvalidError("embedding values must be finite numbers")
    return vectors
