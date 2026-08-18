# 프리톡 미사용 응답 필드 정규화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프리톡 후속 턴과 종료 감지 응답에서 서버가 사용하지 않는 모델 필드를 폐기해 불필요한 502를 방지한다.

**Architecture:** 기존 `generate_turn()`의 JSON 및 필수 콘텐츠 검증은 유지한다. 요청 컨텍스트상 사용하지 않는 `inferredTitle`과 종료 감지 후의 생성 메시지만 응답 조립 단계에서 `None`으로 정규화한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, `unittest`.

**Spec:** `docs/tasks/LAN-309/issue.md`

## Global Constraints

- 변경 범위는 `app/free_talk/application/conversation_service.py`와 `tests/test_free_talk_api.py`로 제한한다.
- 첫 사용자 턴의 `inferredTitle`은 짧은 한국어 제목이어야 한다는 기존 검증을 유지한다.
- `NORMAL` 응답의 `userExitIntentDetected`와 계속 대화할 때의 `aiMessage`, `translatedMessage` 필수 검증을 유지한다.
- `CONTINUE_AFTER_EXIT_DECLINED`가 종료 의사를 다시 판단하지 않는 기존 동작을 유지한다.
- 표현 추천, 임베딩, BE API 계약은 변경하지 않는다.
- 새 의존성을 추가하지 않는다.
- 테스트를 먼저 변경하고 예상한 실패를 확인한 뒤 최소 구현을 작성한다.

---

### Task 1: 프리톡 미사용 턴 필드 정규화

**Files:**
- Modify: `tests/test_free_talk_api.py:495-550`
- Modify: `app/free_talk/application/conversation_service.py:101-138`
- Modify: `app/free_talk/application/conversation_service.py:190-205`

**Interfaces:**
- Consumes: `generate_turn(payload: FreeTalkTurnRequest, settings: Settings) -> FreeTalkTurnResponse`.
- Produces: 후속 턴의 `inferredTitle`과 종료 감지 응답의 `aiMessage`, `translatedMessage`, `emotion`을 `None`으로 정규화한 기존 `FreeTalkTurnResponse` 계약.

- [x] **Step 1: 후속 턴 제목 정규화 실패 테스트 작성**

  `test_turn_rejects_inferred_title_after_first_user_turn`을 다음 동작 검증으로 변경한다.

  ```python
  def test_turn_ignores_inferred_title_after_first_user_turn(self):
      response = self._post(
          "/api/v1/free-talk/turn",
          valid_turn_payload(isFirstUserTurn=False),
          FakeOpenAI(contents=[json.dumps(normal_turn_completion())]),
      )

      self.assertEqual(response.status_code, 200)
      self.assertIsNone(response.json()["data"]["inferredTitle"])
  ```

- [x] **Step 2: 후속 턴 제목 테스트가 기존 코드에서 실패하는지 확인**

  Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest tests.test_free_talk_api.FreeTalkApiTests.test_turn_ignores_inferred_title_after_first_user_turn`

  Expected: 응답 상태가 `502`여서 `200` assertion이 실패한다.

- [x] **Step 3: 종료 감지 후 생성 필드 정규화 실패 테스트 작성**

  `test_turn_rejects_generated_fields_when_exit_intent_is_detected`를 다음 동작 검증으로 변경한다.

  ```python
  def test_turn_ignores_generated_fields_when_exit_intent_is_detected(self):
      response = self._post(
          "/api/v1/free-talk/turn",
          valid_turn_payload(),
          FakeOpenAI(
              contents=[
                  json.dumps(
                      normal_turn_completion(userExitIntentDetected=True),
                  ),
              ],
          ),
      )

      self.assertEqual(response.status_code, 200)
      self.assertEqual(
          response.json()["data"],
          {
              "userExitIntentDetected": True,
              "inferredTitle": "주말 등산 이야기",
              "aiMessage": None,
              "translatedMessage": None,
              "emotion": None,
          },
      )
  ```

- [x] **Step 4: 종료 감지 테스트가 기존 코드에서 실패하는지 확인**

  Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest tests.test_free_talk_api.FreeTalkApiTests.test_turn_ignores_generated_fields_when_exit_intent_is_detected`

  Expected: 응답 상태가 `502`여서 `200` assertion이 실패한다.

- [x] **Step 5: 후속 턴 제목 검증을 첫 사용자 턴에만 적용**

  `_validate_inferred_title()`에서 `is_first_user_turn`이 `False`이면 모델이 반환한 제목과 관계없이 즉시 반환한다. 첫 사용자 턴의 기존 한국어·길이·공백 검증은 그대로 둔다.

  ```python
  def _validate_inferred_title(
      title: str | None,
      is_first_user_turn: bool,
  ) -> None:
      if not is_first_user_turn:
          return
      if (
          title is None
          or not title.strip()
          or len(title.strip()) > 30
          or _KOREAN_TITLE_PATTERN.fullmatch(title.strip()) is None
          or _KOREAN_CHARACTER_PATTERN.search(title) is None
      ):
          raise ValueError("first user turn requires a short Korean inferred title")
  ```

- [x] **Step 6: 종료 감지 응답의 생성 필드를 폐기**

  `exit_detected` 분기에서 모델의 `aiMessage`, `translatedMessage`, `emotion`을 전달하지 않고 모두 `None`으로 조립한다. 첫 사용자 턴의 유효한 `inferredTitle`은 기존처럼 유지한다.

  ```python
  if exit_detected:
      return FreeTalkTurnResponse(
          userExitIntentDetected=True,
          inferredTitle=(
              candidate.inferredTitle if payload.isFirstUserTurn else None
          ),
          aiMessage=None,
          translatedMessage=None,
          emotion=None,
      )
  ```

- [x] **Step 7: 프리톡 API 회귀 테스트 실행**

  Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest tests.test_free_talk_api`

  Expected: 모든 프리톡 API 테스트가 통과한다. 특히 첫 사용자 턴의 잘못된 제목과 일반 응답의 누락 메시지는 계속 `502`로 검증된다.

- [x] **Step 8: 전체 테스트 실행**

  Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`

  Expected: `243`개 이상의 테스트가 실패 없이 통과한다.

- [x] **Step 9: 구현 결과 기록 및 커밋**

  `docs/tasks/LAN-309/plan.md`의 완료 항목과 검증 결과를 갱신한 뒤 다음 파일만 커밋한다.

  ```bash
  git add app/free_talk/application/conversation_service.py tests/test_free_talk_api.py docs/tasks/LAN-309/plan.md
  git commit -m "fix: 프리톡 미사용 응답 필드를 안전하게 무시"
  ```

### 검증 결과

- TDD RED: 두 신규 회귀 테스트가 기존 코드에서 각각 502 응답으로 실패했다.
- TDD GREEN: 두 focused 테스트가 각각 `OK`로 통과했다.
- 프리톡 API 회귀: 41개 테스트 `OK`.
- 전체 테스트: 243개 테스트 `OK`.
