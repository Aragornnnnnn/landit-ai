# 프리톡 대화에서 학습 가치 있는 사용자 발화를 추출해 임베딩하는 유스케이스 모듈
import json

from pydantic import ValidationError

from app.core.config import Settings
from app.free_talk.llm.embeddings import request_embeddings
from app.free_talk.llm.json_completion import (
    AiResponseInvalidError,
    request_json_completion,
)
from app.models.free_talk import (
    ConversationEmbeddingsRequest,
    ConversationEmbeddingsResponse,
)


_MAX_EXCERPTS = 4


def generate_conversation_embeddings(
    payload: ConversationEmbeddingsRequest,
    settings: Settings,
) -> ConversationEmbeddingsResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_extraction_system_prompt(),
        user_prompt=_extraction_user_prompt(payload),
    )
    excerpt_texts = _validated_excerpt_texts(data)
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


def _validated_excerpt_texts(data: dict[str, object]) -> list[str]:
    excerpts = data.get("excerpts")
    if (
        not isinstance(excerpts, list)
        or not 1 <= len(excerpts) <= _MAX_EXCERPTS
        or any(not isinstance(text, str) or not text.strip() for text in excerpts)
    ):
        raise AiResponseInvalidError("excerpts must be one to four non-blank sentences")
    return [text.strip() for text in excerpts]


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
