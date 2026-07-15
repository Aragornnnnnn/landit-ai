# LAN-96 Closing Message API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/v1/conversation/closing-message`를 추가해 대화 종료 메시지, 번역, 마지막 사용자 메시지에 대한 속마음을 반환한다.

**Architecture:** Landit 명세는 전체 `conversationHistory`를 받는다. 서비스는 히스토리 전체를 프롬프트에 넣고 마지막 AI/USER 턴을 따로 강조하며, SayNow `origin/develop`의 closing prompt 문구를 기능상 동일한 범위에서 가져온다. LLM 응답 보정 fallback은 두지 않고 필드 누락이나 꼬리 질문 정책 위반은 502로 처리한다.

**Tech Stack:** FastAPI, Pydantic v2, OpenAI SDK, unittest.

## Global Constraints

- 성공 응답은 `ApiResponse[ClosingMessageResponse]` 공통 래퍼를 사용한다.
- `aiMessage`, `translatedMessage`가 물음표로 끝나면 `AI_RESPONSE_INVALID` 502로 처리한다.
- LLM 호출 실패 또는 설정 누락은 `AI_GENERATION_FAILED` 503으로 처리한다.
- 요청은 stateless하게 처리하며 서버에 세션 상태를 저장하지 않는다.

---

### Task 1: Request And Response Contract

**Files:**
- Modify: `app/models/conversation.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Produces: `ClosingMessageRequest`, `ClosingMessageResponse`, `ClosingReason`.

- [x] 실패 테스트로 `closing-message` 요청과 성공 응답 계약을 고정한다.
- [x] Pydantic 모델과 마지막 턴 검증을 추가한다.
- [x] focused test를 통과시킨다.

### Task 2: LLM Service And HTTP Route

**Files:**
- Modify: `app/conversation/application/next_message_service.py`
- Modify: `app/api/conversation.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `ClosingMessageRequest`.
- Produces: `generate_closing_message(request, settings)`.

- [x] SayNow closing prompt를 Landit 필드명과 히스토리 기반 요청에 맞춰 추가한다.
- [x] `POST /api/v1/conversation/closing-message` 라우터를 연결한다.
- [x] 응답 필드 누락, 꼬리 질문, 생성 실패 테스트를 통과시킨다.

### Task 3: Documentation And Verification

**Files:**
- Modify: `README.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

- [x] README에 closing-message API 책임을 반영한다.
- [x] `.venv/bin/python -m unittest discover -s tests`를 실행한다.
- [x] `.venv/bin/python -m compileall app tests`를 실행한다.
- [x] `git diff --check`를 실행한다.
