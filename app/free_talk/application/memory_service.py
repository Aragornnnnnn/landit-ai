# 프리톡 장기기억 후보 추출과 상태 판정을 담당하는 유스케이스 모듈
import json

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.core.config import Settings
from app.free_talk.llm.embeddings import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    request_embeddings,
)
from app.free_talk.llm.json_completion import (
    AiResponseInvalidError,
    request_json_completion,
)
from app.models.free_talk import (
    MemoryCandidate,
    MemoryCandidatesRequest,
    MemoryCandidatesResponse,
    MemoryResolution,
    MemoryResolutionRequest,
    MemoryResolutionResponse,
)


_MAX_CANDIDATES = 5
EXTRACTOR_VERSION = "memory-candidate-v1"


def generate_memory_candidates(
    payload: MemoryCandidatesRequest,
    settings: Settings,
) -> MemoryCandidatesResponse:
    drafts = _validated_candidate_drafts(
        request_json_completion(
            settings=settings,
            system_prompt=_candidate_system_prompt(),
            user_prompt=_json_prompt(payload),
        ),
        payload,
    )
    if not drafts:
        return MemoryCandidatesResponse(
            extractorVersion=EXTRACTOR_VERSION,
            candidates=[],
        )

    contents = [draft.content.strip() for draft in drafts]
    embeddings = request_embeddings(settings=settings, texts=contents)
    candidates = [
        draft.model_copy(update={"embedding": embedding})
        for draft, embedding in zip(drafts, embeddings, strict=True)
    ]
    return MemoryCandidatesResponse(
        extractorVersion=EXTRACTOR_VERSION,
        candidates=candidates,
    )


def generate_memory_resolution(
    payload: MemoryResolutionRequest,
    settings: Settings,
) -> MemoryResolutionResponse:
    return _validated_resolution(
        request_json_completion(
            settings=settings,
            system_prompt=_resolution_system_prompt(),
            user_prompt=_json_prompt(payload),
        ),
        payload,
    )


def _validated_resolution(
    data: dict[str, object],
    payload: MemoryResolutionRequest,
) -> MemoryResolutionResponse:
    try:
        response = MemoryResolutionResponse.model_validate(data)
        _validate_resolutions(response.resolutions, payload)
        return response
    except ValidationError as exc:
        raise AiResponseInvalidError from exc


def _validated_candidate_drafts(
    data: dict[str, object],
    payload: MemoryCandidatesRequest,
) -> list[MemoryCandidate]:
    try:
        envelope = _MemoryCandidateDraftResponse.model_validate(data)
        drafts = []
        for raw_candidate in envelope.candidates:
            if "embeddingModel" in raw_candidate or "embedding" in raw_candidate:
                raise AiResponseInvalidError("candidate must not contain embedding")
            drafts.append(
                MemoryCandidate.model_validate(
                    {
                        **raw_candidate,
                        "embeddingModel": EMBEDDING_MODEL,
                        "embedding": [0.0] * EMBEDDING_DIMENSIONS,
                    },
                ),
            )
    except ValidationError as exc:
        raise AiResponseInvalidError from exc

    if [draft.candidateIndex for draft in drafts] != list(range(len(drafts))):
        raise AiResponseInvalidError("candidate indexes must be contiguous")

    messages_by_id = {message.messageId: message for message in payload.conversationHistory}
    for draft in drafts:
        if draft.contentLocale != payload.baseLocale:
            raise AiResponseInvalidError("candidate locale must match base locale")
        for source_message_id in draft.sourceMessageIds:
            source = messages_by_id.get(source_message_id)
            if source is None or source.role != "USER":
                raise AiResponseInvalidError("candidate source must be a user message")

    return drafts


class _MemoryCandidateDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[dict[str, object]] = Field(max_length=_MAX_CANDIDATES)


def _validate_resolutions(
    resolutions: list[MemoryResolution],
    payload: MemoryResolutionRequest,
) -> None:
    requested_indexes = [candidate.candidateIndex for candidate in payload.candidates]
    resolved_indexes = [resolution.candidateIndex for resolution in resolutions]
    if sorted(requested_indexes) != sorted(resolved_indexes):
        raise AiResponseInvalidError("every candidate must have one resolution")
    if len(resolved_indexes) != len(set(resolved_indexes)):
        raise AiResponseInvalidError("candidate resolutions must be unique")

    comparable_ids_by_candidate = {
        candidate.candidateIndex: {
            memory.memoryId for memory in candidate.comparableMemories
        }
        for candidate in payload.candidates
    }
    superseded_ids = []
    for resolution in resolutions:
        comparable_ids = comparable_ids_by_candidate[resolution.candidateIndex]
        if any(
            memory_id not in comparable_ids
            for memory_id in resolution.supersededMemoryIds
        ):
            raise AiResponseInvalidError("resolution references an unknown memory")
        superseded_ids.extend(resolution.supersededMemoryIds)
    if len(superseded_ids) != len(set(superseded_ids)):
        raise AiResponseInvalidError("a memory cannot be superseded twice")


def _json_prompt(payload: BaseModel) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _candidate_system_prompt() -> str:
    return (
        "Extract zero to five durable memories from the USER messages in the completed "
        "FreeTalk conversation. Return only a JSON object with a candidates array. "
        "Each candidate must contain candidateIndex, memoryType (PROFILE, EVENT, or "
        "EPISODE), a concise content sentence in baseLocale, contentLocale, sourceMessageIds, "
        "confidence, validFrom, and validTo. candidateIndex must start at zero and be "
        "contiguous. Use only USER message IDs "
        "as sources. Do not infer diagnoses, personality, relationships, or intent. "
        "Exclude secrets, credentials, financial identifiers, greetings, acknowledgements, "
        "one-off requests, and language-learning examples. For a future plan, keep the "
        "scheduled date in content and use the utterance time as validFrom."
    )


def _resolution_system_prompt() -> str:
    return (
        "Resolve each memory candidate against the comparable ACTIVE memories. Return "
        "only a JSON object with exactly one resolution for every candidateIndex. "
        "Use ADD for an independent fact, SUPERSEDE only when an existing memory is "
        "replaced, and IGNORE for duplicates, transient statements, or weak evidence. "
        "Only SUPERSEDE may contain supersededMemoryIds, and use only IDs present in "
        "the candidate's comparableMemories. Never supersede another candidate."
    )
