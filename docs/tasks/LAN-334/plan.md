# LAN-334 FreeTalk Closing Title Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자 선시작 프리톡 제목을 closing에서 안전하게 생성하고 실패 시 BE fallback으로 세션 종료를 보장한다.

**Architecture:** AI는 closing의 핵심 메시지와 부가 제목을 분리해 검증하고 제목만 1회 repair한다. BE는 세션 상태로 제목 생성 필요 여부를 결정하고 완료 트랜잭션에서 생성 제목 또는 캐릭터 기반 fallback을 저장한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI SDK, Java, Spring Boot, Jackson, JPA, JUnit 5, unittest.

**Spec:** `docs/tasks/LAN-334/design.md`

## Global Constraints

- 추천 주제 세션의 기존 제목은 변경하지 않는다.
- 제목 실패는 closing 메시지 또는 세션 종료를 실패시키지 않는다.
- 제목 repair는 최대 한 번만 호출한다.
- AI 선배포 후 BE를 배포한다.
- 새 외부 의존성을 추가하지 않는다.

---

### Task 1: AI closing 제목 계약

**Files:**
- Modify: `app/models/free_talk.py`
- Modify: `app/free_talk/application/conversation_service.py`
- Test: `tests/test_free_talk_api.py`
- Test: `tests/test_free_talk_rules.py`

**Interfaces:**
- Consumes: `FreeTalkClosingRequest.titleGenerationRequired: bool = False`
- Produces: `FreeTalkClosingResponse.inferredTitle: str | None`

- [x] **Step 1: 실패 테스트 작성**

```python
def test_closing_repairs_invalid_title_once():
    fake_openai = FakeOpenAI(contents=[
        json.dumps(closing_completion(inferredTitle="123")),
        json.dumps({"inferredTitle": "Weekend Hiking"}),
    ])
    response = self._post(
        "/api/v1/free-talk/closing",
        valid_closing_payload(titleGenerationRequired=True),
        fake_openai,
    )
    self.assertEqual(response.json()["data"]["inferredTitle"], "Weekend Hiking")
    self.assertEqual(len(fake_openai.completions.calls), 2)
```

- [x] **Step 2: 실패 확인**

Run: `.venv/bin/python -m unittest tests.test_free_talk_api`
Expected: closing 제목 필드와 repair 동작이 없어 실패한다.

- [x] **Step 3: 최소 구현**

```python
class FreeTalkClosingRequest(FreeTalkContext):
    titleGenerationRequired: bool = False

class FreeTalkClosingResponse(BaseModel):
    inferredTitle: str | None
```

마무리 메시지를 먼저 검증한 뒤 제목이 필요한 경우에만 제목 계약을 검사하고, 실패하면 제목 전용 completion을 한 번 호출한다. repair 예외와 유효하지 않은 결과는 `None`으로 변환한다.

- [x] **Step 4: 관련 테스트 통과 확인**

Run: `.venv/bin/python -m unittest tests.test_free_talk_api tests.test_free_talk_rules`
Expected: PASS.

- [x] **Step 5: AI 변경 커밋**

```bash
git add app/models/free_talk.py app/free_talk/application/conversation_service.py tests/test_free_talk_api.py tests/test_free_talk_rules.py docs/tasks/LAN-334
git commit -m "fix: 프리톡 제목을 종료 시점에 안전하게 생성"
```

### Task 2: BE closing 제목 저장과 fallback

**Files:**
- Modify: `src/main/java/com/landit/landitbe/feature/session/client/ai/AiFreeTalkClosingRequest.java`
- Modify: `src/main/java/com/landit/landitbe/feature/session/client/ai/AiFreeTalkClosingResult.java`
- Modify: `src/main/java/com/landit/landitbe/feature/session/client/ai/RemoteAiFreeTalkClient.java`
- Modify: `src/main/java/com/landit/landitbe/feature/session/client/ai/LocalAiFreeTalkClient.java`
- Modify: `src/main/java/com/landit/landitbe/feature/session/domain/FreeTalkCharacter.java`
- Modify: `src/main/java/com/landit/landitbe/feature/session/service/FreeTalkMessageService.java`
- Modify: `src/main/java/com/landit/landitbe/feature/session/service/FreeTalkSubmittedMessageService.java`
- Test: `src/test/java/com/landit/landitbe/feature/session/client/ai/RemoteAiFreeTalkClientTest.java`
- Test: `src/test/java/com/landit/landitbe/feature/session/FreeTalkSessionApiIntegrationTests.java`

**Interfaces:**
- Consumes: AI closing 응답의 nullable `inferredTitle`
- Produces: 완료된 사용자 선시작 세션의 non-null 제목

- [x] **Step 1: 실패 테스트 작성**

```java
assertThat(closingRequest.titleGenerationRequired()).isTrue();
assertThat(completedSessionTitle).isEqualTo("Weekend Hiking");
assertThat(fallbackSessionTitle).isEqualTo("Chloe와의 대화");
```

- [x] **Step 2: 실패 확인**

Run: `./gradlew test --tests '*RemoteAiFreeTalkClientTest' --tests '*FreeTalkSessionApiIntegrationTests' --no-daemon --console=plain`
Expected: closing 플래그, 응답 제목, fallback 저장이 없어 실패한다.

- [x] **Step 3: 최소 구현**

```java
boolean titleGenerationRequired =
    session.getStartMode() == FreeTalkStartMode.USER_FIRST && session.getTitle() == null;
String title = result.inferredTitle() != null
    ? result.inferredTitle()
    : FreeTalkCharacter.fromId(session.getCharacterId()).displayName() + "와의 대화";
```

일반 턴의 `isFirstUserTurn`은 항상 `false`로 보내고 turn 결과의 `inferredTitle`은 저장하지 않는다. closing 완료 경로 두 곳에서만 제목 생성 대상 세션의 제목을 저장한다.

- [x] **Step 4: 관련 테스트 통과 확인**

Run: `./gradlew test --tests '*RemoteAiFreeTalkClientTest' --tests '*FreeTalkSessionApiIntegrationTests' --no-daemon --console=plain`
Expected: PASS.

- [x] **Step 5: BE 변경 커밋**

```bash
git add src/main src/test
git commit -m "fix: 사용자 선시작 프리톡 종료 제목 fallback 추가"
```

### Task 3: 전체 계약 검증

**Files:**
- Modify: `docs/tasks/LAN-334/plan.md`

**Interfaces:**
- Consumes: Task 1과 Task 2의 최종 계약
- Produces: 배포 가능한 AI·BE 검증 근거

- [x] **Step 1: AI 전체 테스트**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: 모든 테스트 PASS.

Result: 271 tests PASS.

- [x] **Step 2: AI OpenAPI 확인**

Run: `.venv/bin/python -m unittest tests.test_free_talk_api.FreeTalkApiTests.test_openapi_exposes_closing_title_contract`
Expected: PASS.

Result: 전체 unittest에 포함해 PASS.

- [x] **Step 3: BE 전체 테스트**

Run: `./gradlew test --no-daemon --console=plain`
Expected: BUILD SUCCESSFUL.

Result: `test`와 `spotlessCheck` 모두 BUILD SUCCESSFUL.

- [x] **Step 4: 변경 범위 검토**

Run: `git diff --check && git status --short`
Expected: 공백 오류가 없고 LAN-334 파일만 변경된다.

Result: AI와 BE 모두 `git diff --check` 통과, 격리된 `fix/LAN-334` 작업 트리에서만 변경.
