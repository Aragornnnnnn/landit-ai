# 프리톡 대화에서 학습 가치 있는 사용자 발화를 추출해 임베딩하는 유스케이스 모듈
import json
import logging

from pydantic import ValidationError

from app.core.config import Settings
from app.free_talk.llm.embeddings import EMBEDDING_MODEL, request_embeddings
from app.free_talk.llm.json_completion import (
    AiResponseInvalidError,
    request_json_completion,
)
from app.models.free_talk import (
    ConversationEmbeddingsRequest,
    ConversationEmbeddingsResponse,
    MemoryQueryEmbeddingRequest,
    MemoryQueryEmbeddingResponse,
)


_MAX_EXCERPTS = 4

logger = logging.getLogger(__name__)


class _RepairableExcerptError(AiResponseInvalidError):
    """교정 프롬프트로 복구할 수 있는 발화 추출 오류."""


def generate_conversation_embeddings(
    payload: ConversationEmbeddingsRequest,
    settings: Settings,
) -> ConversationEmbeddingsResponse:
    excerpt_texts = _extract_excerpt_texts(payload, settings)
    vectors = request_embeddings(settings=settings, texts=excerpt_texts)
    try:
        return ConversationEmbeddingsResponse.model_validate(
            {
                "excerpts": [
                    {"excerptText": text, "embedding": vector}
                    for text, vector in zip(excerpt_texts, vectors, strict=True)
                ],
            },
        )
    except (ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc


def generate_memory_query_embedding(
    payload: MemoryQueryEmbeddingRequest,
    settings: Settings,
) -> MemoryQueryEmbeddingResponse:
    vector = request_embeddings(settings=settings, texts=[payload.query])[0]
    try:
        return MemoryQueryEmbeddingResponse(
            embeddingModel=EMBEDDING_MODEL,
            embedding=vector,
        )
    except (ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc


def _extract_excerpt_texts(
    payload: ConversationEmbeddingsRequest,
    settings: Settings,
) -> list[str]:
    user_prompt = _extraction_user_prompt(payload)
    data = request_json_completion(
        settings=settings,
        system_prompt=_extraction_system_prompt(),
        user_prompt=user_prompt,
    )
    try:
        return _validated_excerpt_texts(data)
    except _RepairableExcerptError as exc:
        _log_invalid_excerpts("initial", exc, data)
        repair_reason = str(exc)

    repaired_data = request_json_completion(
        settings=settings,
        system_prompt=_extraction_repair_system_prompt(repair_reason),
        user_prompt=user_prompt,
    )
    try:
        return _validated_excerpt_texts(repaired_data)
    except _RepairableExcerptError as repair_exc:
        _log_invalid_excerpts("repair", repair_exc, repaired_data)
        raise


def _log_invalid_excerpts(
    attempt: str,
    error: AiResponseInvalidError,
    data: dict[str, object],
) -> None:
    excerpts = data.get("excerpts")
    excerpt_count = len(excerpts) if isinstance(excerpts, list) else None
    logger.warning(
        "Conversation excerpts are invalid. workflow=conversation_excerpts_repair "
        "attempt=%s reason=%s excerptCount=%s",
        attempt,
        str(error),
        excerpt_count,
    )


def _validated_excerpt_texts(data: dict[str, object]) -> list[str]:
    if "excerpts" not in data:
        raise _RepairableExcerptError("missing_excerpts")
    excerpts = data["excerpts"]
    if not isinstance(excerpts, list):
        raise AiResponseInvalidError("invalid_excerpts_type")
    if not excerpts:
        raise _RepairableExcerptError("empty_excerpts")
    if len(excerpts) > _MAX_EXCERPTS:
        raise _RepairableExcerptError("too_many_excerpts")
    if any(not isinstance(text, str) for text in excerpts):
        raise AiResponseInvalidError("invalid_excerpt_type")
    if any(not text.strip() for text in excerpts):
        raise _RepairableExcerptError("blank_excerpt")
    return [text.strip() for text in excerpts]


def _extraction_repair_system_prompt(reason: str) -> str:
    return (
        _extraction_system_prompt()
        + " The previous response violated the output contract: "
        + reason
        + ". Return a complete replacement JSON object with exactly one key, excerpts. "
        "excerpts must contain one to four non-blank strings based only on USER messages. "
        "If no sentence is especially valuable, select or rewrite the most meaningful "
        "non-blank USER utterance. Never return an empty array, explanations, or extra keys."
    )


def _extraction_system_prompt() -> str:
    return (
        "Extract one to four key sentences worth learning from the user's utterances "
        "in the complete free-talk conversation. Return only JSON in the form "
        '{"excerpts": ["..."]}. Extract from USER messages only; use AI messages '
        "solely as context to interpret short replies. A short acknowledgement may be "
        "rewritten into a sentence that reveals its meaning using the preceding AI "
        'message (e.g. "Yeah, totally" becomes "I totally agree that the exam was '
        'hard"). Write every excerpt in the conversation\'s learning language '
        "(targetLocale), never in the base language."
    )


def _extraction_user_prompt(payload: ConversationEmbeddingsRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
