# LAN-144 다음 메시지·속마음 생성 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `next-message`에서 속마음 생성을 제거하고, 속마음만 생성하는 stateless 동기 API를 추가한다.

**Architecture:** 일반 턴에서 `landit-be`가 `next-message`와 `inner-thought`를 병렬 호출한다. `landit-ai`는 두 OpenRouter 호출만 독립적으로 처리하며 상태, 캐시, 재시도, 폴링을 소유하지 않는다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK, unittest.

## Global Constraints

- 기존 파일 구조를 유지하고 새 모듈이나 의존성을 추가하지 않는다.
- `next-message` 요청, 고정 질문 검증, `goalCompletionStatus` 생성은 유지한다.
- `inner-thought`는 `nextQuestion`을 받지 않는다.
- `inner-thought`의 `sessionId`, `messageId`는 각각 요청의 `sessionId`, `submittedMessageId`에서 복사한다.
- `conversationHistory`는 최소 1개이며 마지막 메시지는 요청 식별자와 일치하는 `USER` 메시지여야 한다.
- 전체 히스토리는 맥락으로만 참고하고 마지막 사용자 발화만 속마음 생성 대상으로 삼는다.
- 모델 응답 오류는 502, OpenRouter 호출 실패는 503을 유지한다.
- `closing-message`와 BE의 상태 전환, timeout, 재시도, 폴링은 변경하지 않는다.

---

### Task 1: `next-message` 응답 축소

**Files:**
- Modify: `tests/test_conversation_api.py`
- Modify: `app/models/conversation.py`
- Modify: `app/conversation/application/next_message_service.py`

**Interfaces:**
- Produces: `NextMessageResponse(aiMessage, translatedMessage, goalCompletionStatus)`.
- Preserves: `generate_next_message()`와 `_validate_fixed_question_in_response()`.

- [ ] 성공 테스트의 예상 응답에서 `innerThought`, `innerThoughtType`을 제거한다.
- [ ] system prompt에 `innerThought` 출력 지시가 없고, 이전 5개 필드 모델 응답은 `AI_RESPONSE_INVALID` 502가 되는 테스트를 추가한다.
- [ ] `.venv/bin/python -m unittest tests.test_conversation_api.NextMessageApiTests`를 실행해 RED를 확인한다.
- [ ] `NextMessageResponse`에서 속마음 필드를 제거하고 validator 대상을 `aiMessage`, `translatedMessage`로 줄인다.
- [ ] `_next_message_system_prompt()`에서 속마음 정책과 속마음 출력 필드를 제거한다. 고정 질문, 맞장구, 목표 달성 상태 정책은 그대로 둔다.
- [ ] 같은 focused test를 다시 실행해 성공, 고정 질문 누락 502, 생성 실패 503, 요청 불일치 400이 모두 통과하는지 확인한다.
- [ ] 아래 논리 단위로 커밋한다.

```bash
git add app/models/conversation.py app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "feat: 다음 메시지 응답에서 속마음 필드 분리"
```

### Task 2: `inner-thought` API 추가

**Files:**
- Modify: `tests/test_conversation_api.py`
- Modify: `app/models/conversation.py`
- Modify: `app/conversation/application/next_message_service.py`
- Modify: `app/api/conversation.py`

**Interfaces:**
- Produces: `InnerThoughtRequest`, `InnerThoughtData`, `InnerThoughtResponse`.
- Produces: `generate_inner_thought(request, settings) -> InnerThoughtResponse`.
- Produces: `POST /api/v1/conversation/inner-thought`.

```python
class InnerThoughtRequest(BaseModel):
    sessionId: int = Field(gt=0)
    submittedMessageId: int = Field(gt=0)
    submittedTurnNumber: int = Field(gt=0)
    scenario: ScenarioContext
    conversationHistory: list[ConversationHistoryMessage] = Field(min_length=1)


class InnerThoughtData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    innerThought: str
    innerThoughtType: InnerThoughtType


class InnerThoughtResponse(InnerThoughtData):
    sessionId: int = Field(gt=0)
    messageId: int = Field(gt=0)
```

- [ ] `valid_next_message_payload()`에서 `nextQuestion`만 제거한 `valid_inner_thought_payload()`를 추가한다.
- [ ] `InnerThoughtApiTests`에 다음 테스트를 먼저 작성한다.
  - 성공 응답은 요청의 `sessionId`, `submittedMessageId`를 반환한다.
  - user prompt에는 전체 히스토리와 명시적인 마지막 USER 메시지가 있고 `Next fixed question`은 없다.
  - 필드 누락 또는 모델이 식별자까지 생성한 응답은 `AI_RESPONSE_INVALID` 502다.
  - OpenRouter 호출 실패는 `AI_GENERATION_FAILED` 503이다.
  - 빈 히스토리와 마지막 메시지 식별자 불일치는 `INVALID_REQUEST` 400이며 OpenRouter를 호출하지 않는다.
- [ ] `.venv/bin/python -m unittest tests.test_conversation_api.InnerThoughtApiTests`를 실행해 RED를 확인한다.
- [ ] `InnerThoughtRequest`에 양수 ID, 최소 1개 히스토리, 마지막 USER 메시지 일치 검증을 추가한다.
- [ ] `InnerThoughtData`는 `extra="forbid"`로 OpenRouter 출력이 `innerThought`, `innerThoughtType`만 포함하도록 검증한다.
- [ ] `generate_inner_thought()`에서 별도 OpenRouter 호출 후 `InnerThoughtData`를 검증하고 요청 식별자로 `InnerThoughtResponse`를 조립한다.
- [ ] 기존 `next-message`의 `Inner Thought Policy`와 속마음 예시를 전용 system prompt로 옮긴다. 다음 질문·행동 계획·문법 평가 금지 정책을 유지한다.
- [ ] user prompt에 시나리오, 전체 히스토리, 마지막 USER 메시지를 넣고 `nextQuestion`은 넣지 않는다.
- [ ] `app/api/conversation.py`에 route를 추가하고 기존 502·503 오류 매핑을 그대로 적용한다.
- [ ] focused test를 다시 실행해 성공, 400, 502, 503 경로를 확인한다.
- [ ] 아래 논리 단위로 커밋한다.

```bash
git add app/models/conversation.py app/conversation/application/next_message_service.py app/api/conversation.py tests/test_conversation_api.py
git commit -m "feat: 사용자 마지막 발화 속마음 생성 API 추가"
```

### Task 3: 문서와 전체 검증

**Files:**
- Modify: `docs/api/conversation.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

- [ ] `next-message` 응답 필드 목록에서 속마음 필드를 제거한다.
- [ ] `inner-thought` 요청 검증, 응답 식별자 복사, 재호출 의미, BE 상태 관리 책임, 종료 턴 제외를 문서화한다.
- [ ] `checklist.md`와 `context-notes.md`에는 LAN-144 구현 결과와 검증 결과만 이어서 기록한다.
- [ ] 아래 검증을 순서대로 실행한다.

```bash
.venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/landit-ai-lan-144-pycache .venv/bin/python -m compileall -q app tests
git diff --check
git status --short
```

Expected: 전체 unittest와 compileall이 통과하고, LAN-144 관련 파일 외 변경이 없어야 한다.

- [ ] 아래 논리 단위로 커밋한다.

```bash
git add docs/api/conversation.md checklist.md context-notes.md
git commit -m "docs: 다음 메시지와 속마음 생성 책임 분리 계약 기록"
```
