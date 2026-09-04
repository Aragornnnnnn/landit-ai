# 프리톡 장기기억 후보 추출과 상태 판정을 담당하는 유스케이스 모듈
import json
import re

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
    MemoryConversationHistoryMessage,
    MemoryOperation,
    MemoryType,
    MemoryResolution,
    MemoryResolutionRequest,
    MemoryResolutionResponse,
)


_MAX_CANDIDATES = 5
EXTRACTOR_VERSION = "memory-candidate-v6"
_AMBIGUOUS_RELATIVE_WEEKDAY_PATTERN = re.compile(
    r"\b(?:next|this|coming)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|(?:다음|이번)(?:\s*주)?\s*(?:월|화|수|목|금|토|일)요일",
    re.IGNORECASE,
)
_RELATIVE_TIME_PATTERN = re.compile(
    r"\b(?:today|yesterday|tomorrow|tonight|last\s+weekend|next\s+week)\b"
    r"|(?:오늘|어제|내일|오늘\s*밤|지난\s*주말|다음\s*주|다음\s*(?:월|화|수|목|금|토|일)요일)",
    re.IGNORECASE,
)
_ONE_OFF_REQUEST_PATTERN = re.compile(
    r"^\s*(?:(?:could|can|would|will)\s+you\s+(?:say|repeat|speak)\b"
    r"|please\s+(?:say|repeat|speak)\b)"
    r"|^\s*(?:다시|천천히).*(?:말해|말씀해|반복해)",
    re.IGNORECASE,
)
_CONVERSATION_CONTROL_PATTERN = re.compile(
    r"\b(?:end|stop|finish|leave)\s+(?:(?:this|the|our)\s+)?"
    r"(?:conversation|session)\b"
    r"|\b(?:let'?s|let\s+us)\s+(?:wrap\s+(?:(?:it|this)\s+)?up"
    r"(?:\s+(?:here|now))?|stop\s+here)\s*[.!?]*\s*$"
    r"|\b(?:that'?s|that\s+is)\s+all\s+for\s+(?:today|now)\s*[.!?]*\s*$"
    r"|\b(?:i\s+)?(?:need|have|got)\s+to\s+(?:go|leave)(?:\s+now)?\s*[.!?]*\s*$"
    r"|\bi\s+should\s+get\s+going(?:\s+now)?\s*[.!?]*\s*$"
    r"|(?:^|,\s*)(?:talk\s+to\s+you\s+later|bye\s+for\s+now)\s*[.!?]*\s*$"
    r"|(?:대화|세션).*(?:끝내|종료|마무리|그만)"
    r"|(?:이제\s*)?그만\s*(?:할게|하자|할래|해요|하겠습니다)\s*[.!?]*\s*$"
    r"|(?:오늘은?\s*)?여기까지\s*(?:하자|할게|할래|해요|하겠습니다)\s*[.!?]*\s*$"
    r"|(?:(?:나|저)는?\s*)?(?:이제\s+)?가봐야\s*해\s*[.!?]*\s*$"
    r"|이만\s+갈게\s*[.!?]*\s*$"
    r"|(?:^|,\s*)(?:다음에\s+이야기하자|잘\s+가)\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_GREETING_ONLY_PATTERN = re.compile(
    r"^\s*(?:hi|hello|hey)(?:[!,.?\s]+(?:nice\s+to\s+meet\s+you)[!,.?\s]*)?$"
    r"|^\s*(?:안녕|안녕하세요)(?:[!,.?\s]+(?:만나서\s+반가워요?)[!,.?\s]*)?$",
    re.IGNORECASE,
)
_EPHEMERAL_STATE_PATTERN = re.compile(
    r"^\s*(?:i(?:'m|\s+am)|i\s+feel)\s+(?:really\s+)?"
    r"(?:sleepy|tired|hungry|bored|cold|hot|sad|happy|angry|anxious)\s+"
    r"(?:right\s+now|at\s+the\s+moment)[.!?]*\s*$"
    r"|^\s*(?:나|저)는?\s*지금\s*(?:졸려|피곤해|배고파|지루해|추워|더워)[.!?]*\s*$",
    re.IGNORECASE,
)
_LANGUAGE_EXAMPLE_PATTERN = re.compile(
    r"\b(?:for\s+(?:english\s+)?practice|example\s+sentence|role[ -]?play)\b"
    r"|(?:영어\s*연습|예문|역할극)",
    re.IGNORECASE,
)
_EXPLICIT_DENIAL_PATTERN = re.compile(
    r"\b(?:isn't|is\s+not|not)\s+(?:actually\s+)?true\b"
    r"|\bjust\s+an?\s+example\b|(?:사실이\s*아니|예시일\s*뿐)",
    re.IGNORECASE,
)
_QUESTION_ONLY_PATTERN = re.compile(r"[?？]\s*$")
_EXPLICIT_MEMORY_REQUEST_PATTERN = re.compile(
    r"^\s*(?:please\s+|(?:can|could|would|will|do)\s+you\s+(?:please\s+)?)"
    r"(?:remember|keep\s+in\s+mind)\b"
    r"|기억해\s*(?:줘|주세요|줄래|줄\s*수\s*있어|주실래)",
    re.IGNORECASE,
)
_CONTENT_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
_KOREAN_PARTICLE_SUFFIXES = (
    "에게서",
    "와의",
    "과의",
    "으로",
    "에서",
    "에게",
    "이랑",
    "부터",
    "까지",
    "처럼",
    "보다",
    "랑",
    "와",
    "과",
    "을",
    "를",
    "은",
    "는",
    "이",
    "가",
    "에",
    "도",
    "만",
    "로",
)
_KOREAN_VERB_SUFFIXES = ("합니다", "한다", "했다", "하고", "해요", "하다")
_CANDIDATE_PROMPT_PARTS = (
    (
        "Extract zero to five durable memories from the USER messages in the completed "
        "FreeTalk conversation. Return only a JSON object with a candidates array. "
        "Each candidate must contain candidateIndex, memoryType (PROFILE, EVENT, or "
        "EPISODE), a concise content sentence in baseLocale, contentLocale, "
        "sourceMessageIds, confidence, validFrom, and validTo. candidateIndex must start "
        "at zero and be contiguous. For contentLocale, copy the request baseLocale exactly "
        "without converting the code. Write ordinary words entirely in baseLocale and keep "
        "only proper nouns unchanged. Use only USER message IDs as sources. Each candidate "
        "must contain one independently updatable fact. Split facts that could later change "
        "or be invalidated separately, even when they appear in one USER message. Do not "
        "split a cause and its behavioral restatement when both express the same durable "
        "preference; keep the more general useful fact."
    ),
    (
        "Classify by durable meaning rather than the surface wording. PROFILE is a stable "
        "user fact, preference, relationship, possession, recurring habit, or stable fact "
        "about a named entity in the user's life; it is shared across characters. EVENT is "
        "a concrete past or future occurrence with time relevance; it is scoped to the "
        "current character. EPISODE is a shared experience or interaction between the user "
        "and the current character; it is scoped to that character. Do not classify a fact "
        "as EPISODE merely because the user mentioned it in this conversation. Every EPISODE "
        "content must explicitly name the request characterId as a participant, including "
        "when the source refers to that character only as 'we' or 'our'. When an event "
        "establishes a more useful current stable fact, prefer the PROFILE meaning, such as "
        "'I adopted a dog named Bori' becoming '사용자는 보리라는 개를 키운다.' Preserve "
        "relevant named entities and participants. Never drop an explicitly stated companion "
        "or participant from a recurring habit, and do not generalize the habit by removing "
        "who it involves."
    ),
    (
        "Never keep relative time expressions such as 'today', 'yesterday', 'tomorrow', "
        "'last weekend', or 'next Friday' in durable content. Resolve a relative expression "
        "using occurredAt and timezone only when it maps to exactly one calendar date without "
        "an assumption. Relative weekday phrases such as 'next Friday' are ambiguous; if the "
        "date is essential, omit that EVENT candidate instead of guessing or retaining the "
        "relative phrase. Before returning, scan every content sentence and remove any "
        "remaining relative time expression. For PROFILE, use the source utterance time as "
        "validFrom. For a future EVENT, keep the scheduled calendar date in content and use "
        "the utterance time as validFrom. For a past EVENT, include the resolved calendar date "
        "in content and use the event time as validFrom. If only the event date is known, use "
        "00:00:00 in the request timezone. Every validFrom and validTo must be a full RFC 3339 "
        "timestamp with a timezone offset; never return a date-only value. When an end date is "
        "supported but its time is unknown, use 23:59:59 in the request timezone as validTo. "
        "Otherwise set validTo to null."
    ),
    (
        "Quoted, hypothetical, role-play, translation, or language-practice statements are "
        "not user facts unless the user separately confirms them as true. An explicit denial "
        "overrides a quoted or example claim; never extract the denied claim. Do not infer "
        "diagnoses, personality, relationships, or intent. Exclude secrets, credentials, "
        "financial identifiers, greetings, acknowledgements, one-off requests, conversation "
        "control messages, and language-learning examples. Do not extract facts that appear "
        "only as assumptions or presuppositions inside a question. A direct request to "
        "remember an explicitly stated fact is allowed."
    ),
    (
        "Follow these boundary examples: (1) occurredAt=2026-09-02T17:00:00+09:00 and "
        "'Yesterday I won a local marathon' produces an EVENT whose content includes "
        "2026-09-01 and validFrom=2026-09-01T00:00:00+09:00. (2) 'I have a dentist "
        "appointment next Friday' is ambiguous, so return zero candidates. (3) 'For English "
        "practice, I say I have a dog, but it is not true' is neither a fact nor a durable "
        "event, so return zero candidates. (4) 'I will visit Osaka from October 3 to October "
        "7, 2026' uses the utterance time as validFrom and "
        "validTo=2026-10-07T23:59:59+09:00. (5) When baseLocale is KR, 'I work at Landit as "
        "a backend engineer, and I play tennis every Wednesday' produces separate PROFILE "
        "contents '사용자는 Landit에서 백엔드 엔지니어로 일한다' and '사용자는 매주 "
        "수요일에 테니스를 친다'. (6) When baseLocale is KR, the ordinary term 'job "
        "interview' is written as '면접', not left in English. (7) When baseLocale is "
        "KR, 'I have a golden retriever named Bori, and we go hiking together every Sunday' "
        "produces separate PROFILE contents '사용자는 보리라는 골든 리트리버를 키운다' "
        "and '사용자는 보리와 매주 일요일에 등산한다'. (8) When baseLocale is KR, 'I "
        "hate cilantro, so I always ask restaurants to leave it out' produces only the "
        "PROFILE content '사용자는 고수를 싫어한다'. (9) occurredAt=2026-09-02T17:00:00+09:00 "
        "and 'Today I started a new job as an engineer at Acme' produces the PROFILE content "
        "'사용자는 Acme에서 엔지니어로 일한다' with the utterance time as validFrom."
    ),
)


def generate_memory_candidates(
    payload: MemoryCandidatesRequest,
    settings: Settings,
) -> MemoryCandidatesResponse:
    """프리톡에서 저장할 기억 후보를 추출한다.

    후보별 임베딩을 생성한다.

    Args:
        payload: 후보 추출에 필요한 세션, 언어, 시간대 및 대화 이력.
        settings: OpenRouter와 임베딩 호출에 사용하는 서버 설정.
    Returns:
        검증된 후보와 서버가 생성한 임베딩을 포함한 응답.
    Raises:
        AiResponseInvalidError: AI 또는 임베딩 응답이 계약을 위반할 때.
        AiGenerationFailedError: AI/임베딩 호출 또는 모델 설정이 실패할 때.
    """
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
    """장기기억 후보별로 추가, 대체 또는 무시 상태를 판정한다.

    Args:
        payload: 후보와 후보별 비교 대상 장기기억 목록.
        settings: OpenRouter 호출에 사용하는 서버 설정.
    Returns:
        후보마다 하나의 검증된 상태 판정을 포함한 응답.
    Raises:
        AiResponseInvalidError: AI 응답이 후보별 참조 계약을 위반할 때.
        AiGenerationFailedError: AI 호출이나 모델 설정이 실패할 때.
    """
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
        return _ignore_information_losing_supersedes(response, payload)
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
    return _filtered_candidate_drafts(drafts, payload)


def _filtered_candidate_drafts(
    drafts: list[MemoryCandidate],
    payload: MemoryCandidatesRequest,
) -> list[MemoryCandidate]:
    """명백한 오기억 후보를 제거하고 남은 후보 인덱스를 다시 정렬한다."""
    messages_by_id = {
        message.messageId: message for message in payload.conversationHistory
    }
    filtered = [
        draft
        for draft in drafts
        if not _must_drop_candidate(draft, messages_by_id)
    ]
    return [
        draft.model_copy(update={"candidateIndex": candidate_index})
        for candidate_index, draft in enumerate(filtered)
    ]


def _must_drop_candidate(
    draft: MemoryCandidate,
    messages_by_id: dict[int, MemoryConversationHistoryMessage],
) -> bool:
    """후보 내용과 USER 원문에서 안전하게 판정 가능한 제외 조건만 적용한다."""
    source_messages = [messages_by_id[source_id] for source_id in draft.sourceMessageIds]
    source_text = " ".join(message.content for message in source_messages)
    if (
        _RELATIVE_TIME_PATTERN.search(draft.content)
        or _AMBIGUOUS_RELATIVE_WEEKDAY_PATTERN.search(draft.content)
    ):
        return True
    if (
        draft.memoryType == MemoryType.EVENT
        and _AMBIGUOUS_RELATIVE_WEEKDAY_PATTERN.search(source_text)
    ):
        return True
    if _ONE_OFF_REQUEST_PATTERN.search(source_text):
        return True
    if _CONVERSATION_CONTROL_PATTERN.search(source_text):
        return True
    if all(_is_question_without_explicit_fact(message.content) for message in source_messages):
        return True
    if (
        draft.memoryType == MemoryType.EPISODE
        and _GREETING_ONLY_PATTERN.search(source_text)
    ):
        return True
    if _EPHEMERAL_STATE_PATTERN.search(source_text):
        return True
    return bool(
        _LANGUAGE_EXAMPLE_PATTERN.search(source_text)
        and _EXPLICIT_DENIAL_PATTERN.search(source_text)
    )


def _is_question_without_explicit_fact(source_text: str) -> bool:
    """명시적 기억 요청이 아닌 순수 질문형 발화인지 판정한다."""
    return bool(
        _QUESTION_ONLY_PATTERN.search(source_text)
        and not _EXPLICIT_MEMORY_REQUEST_PATTERN.search(source_text)
    )


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


def _ignore_information_losing_supersedes(
    response: MemoryResolutionResponse,
    payload: MemoryResolutionRequest,
) -> MemoryResolutionResponse:
    """기존 기억의 세부 정보를 제거하는 역방향 대체를 무시한다."""
    candidates_by_index = {
        candidate.candidateIndex: candidate for candidate in payload.candidates
    }
    guarded = []
    for resolution in response.resolutions:
        candidate = candidates_by_index[resolution.candidateIndex]
        memories_by_id = {
            memory.memoryId: memory for memory in candidate.comparableMemories
        }
        loses_information = any(
            _is_strict_content_subset(
                candidate.content,
                memories_by_id[memory_id].content,
            )
            for memory_id in resolution.supersededMemoryIds
        )
        if resolution.operation == MemoryOperation.SUPERSEDE and loses_information:
            guarded.append(
                resolution.model_copy(
                    update={
                        "operation": MemoryOperation.IGNORE,
                        "supersededMemoryIds": [],
                    },
                ),
            )
            continue
        guarded.append(resolution)
    return MemoryResolutionResponse(resolutions=guarded)


def _is_strict_content_subset(candidate: str, existing: str) -> bool:
    """후보가 기존 기억의 단어를 제거한 일반화인지 보수적으로 판정한다."""
    candidate_tokens = _content_tokens(candidate)
    existing_tokens = _content_tokens(existing)
    return candidate_tokens < existing_tokens


def _content_tokens(content: str) -> set[str]:
    return {
        _strip_korean_particle(token.lower())
        for token in _CONTENT_TOKEN_PATTERN.findall(content)
    }


def _strip_korean_particle(token: str) -> str:
    """한국어 조사 차이로 같은 핵심 단어가 달라지는 것을 방지한다."""
    for suffix in _KOREAN_PARTICLE_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            token = token[: -len(suffix)]
            break
    for suffix in _KOREAN_VERB_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix):
            return token[: -len(suffix)]
    return token


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
    return " ".join(_CANDIDATE_PROMPT_PARTS)


def _resolution_system_prompt() -> str:
    return (
        "Resolve each memory candidate against the comparable ACTIVE memories. Return "
        "only a JSON object with a resolutions array containing exactly one object for "
        "every candidateIndex. Each resolution object must contain exactly candidateIndex, "
        "operation, and supersededMemoryIds. "
        "Use ADD for an independent fact and IGNORE for an equivalent duplicate, transient "
        "statement, or weak evidence. Use SUPERSEDE when the candidate is a more specific "
        "version of the same real-world fact and keeping the broader memory would be "
        "redundant; supersede the broader memory. Compare the core predicate and recurrence "
        "first. When both describe the same recurring action, added participants, places, "
        "or qualifiers make the candidate a refinement, not an independent fact. Do not use "
        "ADD merely because the candidate adds those details. For example, 'the user hikes "
        "every Sunday' is superseded by 'the user hikes with Bori every Sunday'. Facts that "
        "remove an existing participant, place, recurrence, or qualifier are broader and must "
        "never supersede the more specific memory; use IGNORE for that broader duplicate. "
        "For example, 'the user walks with Nori every Saturday' must not supersede 'the user "
        "walks with Nori in Seoul Forest every Saturday'. "
        "Facts that can change independently remain ADD even when they mention the same "
        "entity; owning Bori and hiking with Bori are separate facts. "
        "Only SUPERSEDE may contain supersededMemoryIds, and use only IDs present in "
        "the candidate's comparableMemories. Never supersede another candidate."
    )
