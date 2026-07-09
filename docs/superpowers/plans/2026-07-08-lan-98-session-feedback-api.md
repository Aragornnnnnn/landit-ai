# LAN-98 Session Feedback API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/v1/conversation/session-feedback`가 캐시된 메시지별 피드백을 세션 단위로 묶고 최종 요약, 점수, 별점을 반환하게 만든다.

**Architecture:** 기존 `conversation` 라우터, DTO, `next_message_service.py` 흐름을 유지한다. SayNow의 session-feedback 구조를 참고하되 Landit 계약에 필요한 최소 기능만 가져오고, 점수와 별점은 서버 deterministic 계산으로 처리한다.

**Tech Stack:** FastAPI, Pydantic v2, OpenAI Python SDK, unittest, in-memory TTL cache.

## Global Constraints

- 브랜치는 `feat/LAN-98`이다.
- 성공 응답은 `ApiResponse[SessionFeedbackResponse]` 형태다.
- `expectedMessageIds`는 non-empty, positive, no duplicate로 검증한다.
- `MESSAGE_FEEDBACK_NOT_READY`는 409로 반환하고 외부 응답에 누락 ID를 포함하지 않는다.
- `nativeScore`는 서버가 0~100 정수로 계산한다.
- `starRating`은 `nativeScore` 기준으로 `1.0`, `1.5`, `2.0`, `2.5`, `3.0` 중 하나를 반환한다.
- `highlightMessage`, `summaryMessage`는 LLM이 생성한다.
- 성공 후 해당 세션의 메시지별 피드백 캐시는 삭제한다.
- 실패 또는 피드백 미준비 시 캐시는 보존한다.
- 새 의존성은 추가하지 않는다.

---

### Task 1: Contract Models And Not-Ready Error

**Files:**
- Modify: `app/models/conversation.py`
- Modify: `app/common/errors.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Produces: `SessionFeedbackRequest`, `SessionFeedbackSummary`, `SessionFeedbackResponse`, `ErrorCode.MESSAGE_FEEDBACK_NOT_READY`.
- Consumes: `ScenarioContext`, `MessageFeedbackData`, `FeedbackType`.

- [ ] **Step 1: Write failing DTO and error-code tests**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.SessionFeedbackApiTests`

Expected: fail because session-feedback models and error code do not exist.

- [ ] **Step 2: Implement minimal models and error code**

Add request validation for non-empty, positive, unique `expectedMessageIds`. Add response fields `sessionId`, `nativeScore`, `starRating`, `highlightMessage`, `summaryMessage`, `messageFeedbacks`.

- [ ] **Step 3: Verify focused tests pass**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.SessionFeedbackApiTests`

Expected: DTO tests pass or move to the next missing behavior.

### Task 2: Service Behavior And Score Policy

**Files:**
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `get_expected_message_feedbacks`, `_request_json_completion`, `MessageFeedbackData`.
- Produces: `generate_session_feedback`, `delete_message_feedback_cache`.

- [ ] **Step 1: Write failing service tests**

Cover successful generation, message feedback not ready, invalid LLM response, generation failure, cache delete on success, cache preserve on failure, score/star mapping.

- [ ] **Step 2: Implement minimal service**

Read cached entries in `expectedMessageIds` order. Generate only `highlightMessage` and `summaryMessage` through LLM. Compute `nativeScore` and `starRating` in server code.

- [ ] **Step 3: Verify focused tests pass**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.SessionFeedbackApiTests`

Expected: session-feedback service tests pass.

### Task 3: API Route And OpenAPI

**Files:**
- Modify: `app/api/conversation.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `generate_session_feedback`, `MessageFeedbackNotReadyError`, `AiResponseInvalidError`, `AiGenerationFailedError`.
- Produces: `POST /api/v1/conversation/session-feedback`.

- [ ] **Step 1: Write failing route tests**

Cover 200 common wrapper response, 409 common wrapper response, 502 invalid LLM response, 503 generation failure.

- [ ] **Step 2: Implement route**

Return `success_response(response)`. Map `MessageFeedbackNotReadyError` to 409 `MESSAGE_FEEDBACK_NOT_READY`.

- [ ] **Step 3: Verify focused tests pass**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.SessionFeedbackApiTests`

Expected: route tests pass.

### Task 4: Documentation And Full Verification

**Files:**
- Modify: `docs/api/conversation.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Consumes: final route and DTO names.
- Produces: updated docs and task records.

- [ ] **Step 1: Update docs**

Document session-feedback request, response, field policy, score policy, and error policy.

- [ ] **Step 2: Run full verification**

Run: `.venv/bin/python -m unittest discover -s tests`

Run: `.venv/bin/python -m compileall app tests`

Run: `git diff --check`

Run OpenAPI path check for `/api/v1/conversation/session-feedback`.

- [ ] **Step 3: Commit logical units**

Use reviewable commits for models, service/API/tests, and docs if the diff size warrants it.
