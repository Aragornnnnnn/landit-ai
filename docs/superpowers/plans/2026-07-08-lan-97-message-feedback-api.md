# LAN-97 Message Feedback API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/v1/conversation/message-feedback`가 사용자 메시지 1개의 피드백을 생성하고 TTL 있는 AI 서버 캐시에 저장한 뒤 202 `PREPARING`을 반환하게 만든다.

**Architecture:** 기존 `next-message`, `closing-message`와 같은 FastAPI 라우터, Pydantic DTO, application service 구조를 따른다. SQS, worker, 외부 저장소는 이번 범위에서 제외하고, 추후 최종 피드백에서 재사용할 내부 cache helper만 둔다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Pydantic Settings, OpenAI Python SDK, unittest.

## Global Constraints

- 브랜치는 `feat/LAN-97`이다.
- API 경로는 `POST /api/v1/conversation/message-feedback`다.
- 성공 응답은 HTTP 202와 `ApiResponse[MessageFeedbackResponse]` 형태다.
- LLM 응답 필드 누락 또는 GOOD, NEEDS_IMPROVEMENT 조건부 필드 정책 위반은 `AI_RESPONSE_INVALID` 502다.
- LLM 호출 실패 또는 설정 누락은 `AI_GENERATION_FAILED` 503이다.
- 프롬프트는 기능상 동일한 SayNow turn-feedback 정책을 최대한 재사용한다.
- SQS, Redis, Celery, AI 서버 DB, 외부 조회 API는 추가하지 않는다.
- 테스트는 `.venv/bin/python -m unittest discover -s tests`를 사용한다.

---

### Task 1: Message Feedback Contract

**Files:**
- Modify: `app/models/conversation.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Produces: `MessageFeedbackRequest`, `MessageFeedbackResponse`, `MessageFeedbackData`, `FeedbackStatus`, `FeedbackType`, `MessageContext`.
- Consumes: existing `ScenarioContext`, `ApiResponse`, FastAPI validation handler.

- [ ] **Step 1: Write failing DTO and API validation tests.**

Add tests that post a valid LAN-97 payload and expect the route to exist, plus a conditional policy test where `NEEDS_IMPROVEMENT` without `correctionExpression` returns 502 after the route exists.

- [ ] **Step 2: Run tests to verify RED.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: fail because `message-feedback` route and DTOs are not implemented.

- [ ] **Step 3: Add minimal Pydantic DTOs.**

Implement request fields from the user-provided spec. Implement conditional validation on `MessageFeedbackData` so GOOD and NEEDS_IMPROVEMENT policies are enforced by model validation.

- [ ] **Step 4: Run focused tests.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: route tests still fail until service and router are connected, but DTO import and validation errors move forward.

### Task 2: Generation Service And Cache

**Files:**
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `_request_json_completion`, `MessageFeedbackRequest`, `MessageFeedbackData`.
- Produces: `generate_message_feedback`, `get_cached_message_feedback`, `get_expected_message_feedback_entries`, `clear_message_feedback_cache`.

- [ ] **Step 1: Write failing generation and cache tests.**

Test that a GOOD or NEEDS_IMPROVEMENT LLM JSON response is stored under `sessionId` and `messageId`, and that expired entries are not returned.

- [ ] **Step 2: Run tests to verify RED.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: fail because service and cache helpers are missing.

- [ ] **Step 3: Implement minimal service and TTL cache.**

Use `_request_json_completion` with SayNow-derived prompt functions. Ignore optional `detectedPatterns` from the model response for now, and store `MessageFeedbackData`, user message, and `expires_at` in a locked in-memory dict.

- [ ] **Step 4: Run focused tests.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: message-feedback tests pass.

### Task 3: Router And Documentation

**Files:**
- Modify: `app/api/conversation.py`
- Modify: `README.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`
- Test: `tests/test_conversation_api.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `generate_message_feedback`.
- Produces: `POST /api/v1/conversation/message-feedback` with HTTP 202.

- [ ] **Step 1: Connect FastAPI route and error mapping.**

Return `success_response(response)` with `status_code=202`. Map invalid AI responses to 502 and generation failures to 503.

- [ ] **Step 2: Update README and task notes.**

Document the new public API and in-memory cache boundary.

- [ ] **Step 3: Verify all checks.**

Run: `.venv/bin/python -m unittest discover -s tests`

Run: `.venv/bin/python -m compileall app tests`

Run: `git diff --check`

- [ ] **Step 4: Commit meaningful units.**

Keep commits grouped as contract, service/cache, API/docs/tests if the diff size allows.
