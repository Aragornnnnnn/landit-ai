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
    return _candidates_with_embeddings(drafts, settings)


def _candidates_with_embeddings(
    drafts: list[MemoryCandidate],
    settings: Settings,
) -> MemoryCandidatesResponse:
    """검증된 후보 내용에 서버가 생성한 임베딩을 결합해 응답 계약을 완성한다."""
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
    """AI resolution 응답을 형식과 후보별 참조 범위까지 검증한다."""
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
    """후보의 연속 인덱스와 USER 원문 계보 계약을 검증한다."""
    try:
        envelope = _MemoryCandidateDraftResponse.model_validate(data)
        drafts = _candidate_drafts(envelope)
    except ValidationError as exc:
        raise AiResponseInvalidError from exc

    _validate_contiguous_indexes(drafts)
    _validate_candidate_sources(drafts, payload)
    return drafts


class _MemoryCandidateDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[dict[str, object]] = Field(max_length=_MAX_CANDIDATES)


def _candidate_drafts(
    envelope: _MemoryCandidateDraftResponse,
) -> list[MemoryCandidate]:
    """임베딩은 AI 응답이 아닌 서버 생성값만 후보에 주입한다."""
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
    return drafts


def _validate_contiguous_indexes(drafts: list[MemoryCandidate]) -> None:
    """후보 인덱스는 0부터 빈틈없이 이어져야 resolution 순서를 보장한다."""
    if [draft.candidateIndex for draft in drafts] != list(range(len(drafts))):
        raise AiResponseInvalidError("candidate indexes must be contiguous")


def _validate_candidate_sources(
    drafts: list[MemoryCandidate],
    payload: MemoryCandidatesRequest,
) -> None:
    """후보 언어와 출처는 요청 기준 언어 및 USER 메시지에만 연결한다."""
    messages_by_id = {message.messageId: message for message in payload.conversationHistory}
    for draft in drafts:
        if draft.contentLocale != payload.baseLocale:
            raise AiResponseInvalidError("candidate locale must match base locale")
        if any(
            messages_by_id.get(source_message_id) is None
            or messages_by_id[source_message_id].role != "USER"
            for source_message_id in draft.sourceMessageIds
        ):
            raise AiResponseInvalidError("candidate source must be a user message")


def _validate_resolutions(
    resolutions: list[MemoryResolution],
    payload: MemoryResolutionRequest,
) -> None:
    """모든 후보의 resolution과 supersede 대상 격리를 한 번에 검증한다."""
    _validate_resolution_indexes(resolutions, payload)
    comparable_ids_by_candidate = _comparable_ids_by_candidate(payload)
    _validate_superseded_ids(resolutions, comparable_ids_by_candidate)


def _validate_resolution_indexes(
    resolutions: list[MemoryResolution],
    payload: MemoryResolutionRequest,
) -> None:
    """요청 후보마다 정확히 하나의 고유한 resolution이 있어야 한다."""
    requested_indexes = [candidate.candidateIndex for candidate in payload.candidates]
    resolved_indexes = [resolution.candidateIndex for resolution in resolutions]
    if sorted(requested_indexes) != sorted(resolved_indexes):
        raise AiResponseInvalidError("every candidate must have one resolution")
    if len(resolved_indexes) != len(set(resolved_indexes)):
        raise AiResponseInvalidError("candidate resolutions must be unique")


def _comparable_ids_by_candidate(
    payload: MemoryResolutionRequest,
) -> dict[int, set[int]]:
    return {
        candidate.candidateIndex: {
            memory.memoryId for memory in candidate.comparableMemories
        }
        for candidate in payload.candidates
    }


def _validate_superseded_ids(
    resolutions: list[MemoryResolution],
    comparable_ids_by_candidate: dict[int, set[int]],
) -> None:
    """supersede ID는 해당 후보의 비교 목록에만 있고 후보 간 중복될 수 없다."""
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
