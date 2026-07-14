# LAN-138 AI 응답 품질 검증 및 개선 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 마무리 멘트의 어색함과 메시지 피드백의 과도한 `NEEDS_IMPROVEMENT` 판정을 재현 가능한 사례로 확인하고, 확인된 원인만 수정한 뒤 같은 사례로 개선 여부를 검증한다.

**Architecture:** 외부 API 계약과 DTO는 유지한다. 비식별화한 고정 사례로 현재 OpenRouter 모델의 기준선을 수집하고, `closing-message`와 `message-feedback`을 독립적으로 분석한다. 프롬프트가 원인으로 확인된 항목만 `app/conversation/application/next_message_service.py`에서 수정하며, mock 기반 unittest와 실제 모델 재평가를 함께 사용한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK, OpenRouter, 표준 `unittest`.

## Global Constraints

- 실제 LLM 네트워크 호출은 unittest에 포함하지 않는다.
- 사용자 원문, raw prompt, API key 같은 민감정보는 문서와 테스트 출력에 남기지 않는다.
- `ClosingMessageResponse`, `MessageFeedbackData` 및 HTTP 응답 계약은 변경하지 않는다.
- 두 증상을 동시에 수정하지 않는다. 각 원인을 별도로 검증하고 커밋한다.
- 실제 모델 평가가 끝나기 전에는 품질 개선을 완료로 판단하지 않는다.

---

### Task 1: 수정 전 기준선과 판정 기준 확정

**Files:**

- Create: `scripts/evaluate_conversation_quality.py`
- Create: `tests/fixtures/lan_138_quality_cases.json`
- Create: `docs/quality/lan-138-evaluation.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**

- Consumes: `ClosingMessageRequest`, `MessageFeedbackRequest`, `generate_closing_message()`, `generate_message_feedback()`.
- Produces: 비식별화된 고정 입력 사례와 수정 전 품질 기준선.

- [ ] **Step 1: 실제 제보 사례를 비식별화한다**

  마무리 멘트와 `NEEDS_IMPROVEMENT` 오판 사례를 각각 확보한다. ID와 사용자 식별값은 재현용 값으로 교체하고 의미와 대화 흐름만 보존한다. 사례가 부족하면 다음 경계를 보강한다.

  - 마무리 멘트는 초대 수락, 초대 거절, 구체적 부탁 완료, 최대 턴 도달, 짧지만 관련 있는 답변을 포함한다.
  - 메시지 피드백은 자연스러운 짧은 답변, 자연스러운 구어체, 실제 문법 오류, 맥락과 무관한 답변, USER First 시작 안내 수행을 포함한다.

- [ ] **Step 2: 품질 판정 기준을 문서로 고정한다**

  - 마무리 멘트는 마지막 사용자 발화를 직접 받아주고, 상대 역할과 상황에 맞으며, 새 질문이나 `대화를 마무리하자` 같은 메타 표현을 포함하지 않는다.
  - `GOOD`은 의미가 명확하고 평가 컨텍스트의 의도를 충족하며 실제 수정이 필요하지 않은 발화다. 더 세련된 대안이 있다는 이유만으로 `NEEDS_IMPROVEMENT`로 판정하지 않는다.
  - `NEEDS_IMPROVEMENT`는 의미 전달, 문법, 맥락 적합성 또는 상대 역할에 실제 영향을 주는 문제와 구체적인 수정 표현이 함께 있을 때만 사용한다.
  - 뉘앙스와 공손함은 해당 역할과 맥락에서 오해나 불편을 만들 가능성이 분명할 때만 수정 사유로 사용한다.

- [ ] **Step 3: 수동 품질 평가 스크립트를 작성한다**

  `scripts/evaluate_conversation_quality.py` 첫 줄은 다음 주석으로 시작한다.

  ```python
  # LAN-138 대화 품질 사례를 실제 모델로 반복 평가하는 스크립트
  ```

  표준 라이브러리와 현재 앱 코드만 사용한다. fixture를 읽어 두 서비스 함수 중 하나를 호출하고 기본 결과를 `/tmp/landit-ai-lan-138-results.json`에 저장한다. `--kind`는 `all`, `closing`, `message-feedback`을 허용하고 기본값은 `all`로 둔다. 출력에는 `caseId`, 반복 번호, 응답 필드, 예상 label 일치 여부, 질문 부호 및 메타 마무리 표현 포함 여부만 기록한다. API key는 출력하지 않는다.

  ```bash
  .venv/bin/python scripts/evaluate_conversation_quality.py \
    --cases tests/fixtures/lan_138_quality_cases.json \
    --runs 3 \
    --output /tmp/landit-ai-lan-138-baseline.json
  ```

- [ ] **Step 4: 현재 모델 기준선을 수집한다**

  같은 입력을 3회씩 실행한다. `docs/quality/lan-138-evaluation.md`에는 원문 전체가 아니라 사례 ID별 실패 횟수와 비식별화한 대표 결과만 기록한다. 제보가 재현되지 않으면 프롬프트를 수정하지 않고 모델명, 실행 환경, 실제 요청 payload 차이를 먼저 확인한다.

- [ ] **Step 5: 기준선 unittest를 실행한다**

  ```bash
  .venv/bin/python -m unittest discover -s tests
  ```

  기대 결과는 기존 전체 테스트 통과다. `.venv`가 없다면 의존성 환경을 복구하고 테스트가 통과하기 전에는 다음 Task로 진행하지 않는다.

- [ ] **Step 6: 진단 자료를 커밋한다**

  ```bash
  git add scripts/evaluate_conversation_quality.py tests/fixtures/lan_138_quality_cases.json docs/quality/lan-138-evaluation.md checklist.md context-notes.md
  git commit -m "test: AI 응답 품질 재현 기준 추가"
  ```

### Task 2: 마무리 멘트 원인 확인 및 수정

**Files:**

- Modify: `tests/test_conversation_api.py`
- Modify: `app/conversation/application/next_message_service.py`
- Modify: `docs/quality/lan-138-evaluation.md`
- Modify: `context-notes.md`

**Interfaces:**

- Consumes: Task 1의 마무리 실패 사례와 `_closing_message_system_prompt()`.
- Produces: 상황 안에서 끝나는 마무리 멘트 정책과 회귀 테스트.

- [ ] **Step 1: 실패 결과를 현재 프롬프트와 대조한다**

  현재 예시의 `Let's wrap up here`, `Let's pause here`, `close`, `wrap up`이 실제 어색한 출력에 반복되는지 확인한다. 반복되면 예시 모방을 원인 가설로 확정한다. 아니라면 마지막 AI 메시지, 마지막 사용자 메시지, 종료 사유, 목표 달성 상태를 차례로 비교해 어색함이 시작되는 입력을 찾는다.

- [ ] **Step 2: 실패 테스트를 먼저 추가한다**

  `tests/test_conversation_api.py`에서 서비스 모듈을 다음처럼 import한다.

  ```python
  from app.conversation.application import next_message_service
  ```

  `ClosingMessageApiTests`에 다음 테스트를 추가한다.

  ```python
  def test_closing_prompt_ends_inside_scenario_without_meta_wrap_up(self):
      prompt = next_message_service._closing_message_system_prompt()

      self.assertIn(
          "Stay inside the counterpart role and the concrete situation",
          prompt,
      )
      self.assertNotIn("Let's wrap up here", prompt)
      self.assertNotIn("Let's pause here", prompt)

  def test_closing_message_meta_wrap_up_returns_502(self):
      fake_openai = FakeOpenAI(
          content=json.dumps({
              "aiMessage": "I understand. Let's wrap up here.",
              "translatedMessage": "알겠어. 여기서 대화를 마무리하자.",
              "innerThought": "부탁한 내용은 이해했다.",
              "innerThoughtType": "NORMAL",
          }),
      )
      app = create_app(make_settings(
          openrouter_api_key="test-openrouter-key",
          openrouter_model="openrouter-test-model",
      ))

      with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
          response = make_client(app).post(
              "/api/v1/conversation/closing-message",
              json=valid_closing_message_payload(),
          )

      self.assertEqual(response.status_code, 502)
      self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")
  ```

  ```bash
  .venv/bin/python -m unittest tests.test_conversation_api.ClosingMessageApiTests
  ```

  기대 결과는 새 정책 테스트가 현재 프롬프트 예시 또는 검증 누락 때문에 실패하는 것이다.

- [ ] **Step 3: 확인된 원인만 최소 수정한다**

  예시 모방이 원인이면 `_closing_message_system_prompt()`의 메타 종료 예시를 역할과 상황 안에서 자연스럽게 끝나는 예시로 교체한다. 메타 종료 문구가 실제로 반복되면 `_validate_closing_message_policy()`에도 좁은 검증을 추가한다. 일반적인 `Goodbye`, `See you`, `Maybe next time`은 허용한다.

  ```text
  Stay inside the counterpart role and the concrete situation until the final word.
  Do not announce that the conversation, scenario, practice, or session is ending.
  Avoid meta-closing phrases such as "let's wrap up here" or "let's pause here".
  ```

- [ ] **Step 4: 자동 테스트와 실제 모델을 재검증한다**

  ```bash
  .venv/bin/python -m unittest tests.test_conversation_api.ClosingMessageApiTests
  .venv/bin/python scripts/evaluate_conversation_quality.py \
    --cases tests/fixtures/lan_138_quality_cases.json \
    --kind closing --runs 3 \
    --output /tmp/landit-ai-lan-138-closing-after.json
  ```

  hard rule 위반은 0건이어야 하고, 제보된 어색한 마무리는 동일 입력 3회에서 재발하지 않아야 한다.

- [ ] **Step 5: 마무리 멘트 수정만 커밋한다**

  ```bash
  git add app/conversation/application/next_message_service.py tests/test_conversation_api.py docs/quality/lan-138-evaluation.md context-notes.md
  git commit -m "fix: 상황 안에서 대화가 자연스럽게 끝나도록 마무리 정책 수정"
  ```

### Task 3: `GOOD`·`NEEDS_IMPROVEMENT` 판단 기준 확인 및 수정

**Files:**

- Modify: `tests/test_conversation_api.py`
- Modify: `app/conversation/application/next_message_service.py`
- Modify: `docs/api/conversation.md`
- Modify: `docs/quality/lan-138-evaluation.md`
- Modify: `context-notes.md`

**Interfaces:**

- Consumes: Task 1의 피드백 오판 사례와 `_message_feedback_judgement_policy()`, `_message_feedback_examples()`.
- Produces: 실제 수정 필요성이 있는 경우에만 `NEEDS_IMPROVEMENT`를 선택하는 정책과 경계 사례 테스트.

- [ ] **Step 1: 오판 원인을 분류한다**

  오판을 문법, 어휘, 관련성, 뉘앙스, 공손함, 예시 편향으로 나눈다. 현재 `Why do you wanna know that?`처럼 문법적으로 맞는 발화를 뉘앙스만으로 `NEEDS_IMPROVEMENT`에 고정한 예시가 실제 오판과 같은 방향인지 확인한다. `AI_MESSAGE`와 `SCENARIO_OPENING_INSTRUCTION`은 별도로 집계한다.

- [ ] **Step 2: 판단 경계 실패 테스트를 먼저 추가한다**

  `tests/test_conversation_api.py`의 model import에 `EvaluationContextType`을 추가하고, `MessageFeedbackApiTests`에 다음 테스트를 추가한다.

  ```python
  def test_feedback_prompt_keeps_clear_context_appropriate_utterance_good(self):
      prompt = next_message_service._message_feedback_system_prompt(
          EvaluationContextType.AI_MESSAGE,
      )

      self.assertIn(
          "Prefer GOOD when the meaning is clear, the response fits the context",
          prompt,
      )
      self.assertIn("only a style preference", prompt)

  def test_feedback_prompt_requires_material_impact_for_needs_improvement(self):
      for context_type in EvaluationContextType:
          with self.subTest(context_type=context_type):
              prompt = next_message_service._message_feedback_system_prompt(
                  context_type,
              )
              self.assertIn(
                  "materially affects meaning, correctness, relevance, or role-appropriate interaction",
                  prompt,
              )

  def test_feedback_examples_include_good_boundary_cases_for_each_context(self):
      ai_message_examples = next_message_service._message_feedback_examples(
          EvaluationContextType.AI_MESSAGE,
      )
      opening_examples = next_message_service._message_feedback_examples(
          EvaluationContextType.SCENARIO_OPENING_INSTRUCTION,
      )

      self.assertIn("Yeah, sounds good to me.", ai_message_examples)
      self.assertIn("An iced americano, please.", opening_examples)
      self.assertIn('"feedbackType":"GOOD"', ai_message_examples)
      self.assertIn('"feedbackType":"GOOD"', opening_examples)
  ```

  ```bash
  .venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests
  ```

  기대 결과는 현재 정책에 스타일 선호와 실제 수정 필요성을 구분하는 문구 및 충분한 GOOD 경계 예시가 없어 실패하는 것이다.

- [ ] **Step 3: 확인된 판정 편향만 최소 수정한다**

  `_message_feedback_judgement_policy()`의 판정 순서를 다음처럼 명확히 한다.

  ```text
  First decide whether the utterance successfully communicates the user's intent in the evaluation context.
  Prefer GOOD when the meaning is clear, the response fits the context, and any alternative is only a style preference.
  Use NEEDS_IMPROVEMENT only when the issue materially affects meaning, correctness, relevance, or role-appropriate interaction.
  Do not correct a natural colloquial expression merely because a softer or more formal alternative exists.
  ```

  `_message_feedback_examples()`에는 각 평가 타입의 GOOD 경계 사례와 명백한 `NEEDS_IMPROVEMENT` 사례를 균형 있게 둔다. 기준선에서 예시 편향이 확인되지 않으면 예시는 늘리지 않고 판정 정책만 수정한다.

- [ ] **Step 4: 자동 테스트와 실제 모델을 재검증한다**

  ```bash
  .venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests
  .venv/bin/python scripts/evaluate_conversation_quality.py \
    --cases tests/fixtures/lan_138_quality_cases.json \
    --kind message-feedback --runs 3 \
    --output /tmp/landit-ai-lan-138-feedback-after.json
  ```

  합의한 GOOD 경계 사례는 다수 실행에서 기대 label과 일치해야 한다. 명백한 오류나 맥락 이탈이 `GOOD`으로 완화되면 해당 정책을 다시 조정한다.

- [ ] **Step 5: 피드백 판단 기준 수정만 커밋한다**

  ```bash
  git add app/conversation/application/next_message_service.py tests/test_conversation_api.py docs/api/conversation.md docs/quality/lan-138-evaluation.md context-notes.md
  git commit -m "fix: 실제 수정이 필요한 발화만 개선 대상으로 판정"
  ```

### Task 4: 전체 회귀 검증과 완료 판단

**Files:**

- Modify: `docs/quality/lan-138-evaluation.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**

- Consumes: Task 2와 Task 3의 자동 검증 결과 및 실제 모델 재평가 결과.
- Produces: LAN-138 완료 근거와 남은 품질 위험 기록.

- [ ] **Step 1: 전체 자동 검증을 실행한다**

  ```bash
  .venv/bin/python -m unittest discover -s tests
  .venv/bin/python -m compileall app tests scripts
  git diff --check
  ```

- [ ] **Step 2: 같은 모델과 입력으로 수정 전·후를 비교한다**

  모델명, fixture, 반복 횟수가 모두 같을 때만 비교한다. 사례별 실패 횟수와 남은 예외를 문서에 기록한다.

- [ ] **Step 3: 완료 기준을 확인한다**

  - 제보된 마무리 멘트 문제가 동일 사례 3회에서 재발하지 않는다.
  - 질문, 메타 종료 문구, 역할 이탈은 0건이다.
  - 합의된 GOOD 경계 사례는 다수 실행에서 `GOOD`이다.
  - 명백한 문법 오류, 의미 불명확, 맥락 이탈은 `NEEDS_IMPROVEMENT`를 유지한다.
  - API 스키마와 응답 필드는 변경되지 않는다.

- [ ] **Step 4: 최종 평가 결과를 기록한다**

  `docs/quality/lan-138-evaluation.md`에 모델명, 실행 시점, 사례 수, 반복 횟수, 수정 전·후 집계, 남은 위험을 기록한다. `checklist.md`와 `context-notes.md`에는 실제 수행 결과만 반영한다.

## 실행 기록

- `openai/gpt-5.4-mini`로 마무리 멘트 3개 사례와 메시지 피드백 6개 사례를 각각 3회 실행했다.
- 초기 마무리 멘트 평가는 새 질문과 메타 종료 문구가 없었지만, 당시에는 실제 제보 입력이 없어 어색함을 재현하지 못했다.
- 직설적인 구어체 경계 사례는 수정 전 3회 모두 `NEEDS_IMPROVEMENT`였고, 프롬프트 정책과 예시 수정 후 3회 모두 `GOOD`이었다.
- 문법 오류와 맥락 이탈 사례는 수정 후에도 각각 3회 모두 `NEEDS_IMPROVEMENT`를 유지했다.
- 사용자 제보로 확인한 메타 종료 문구는 기존 마무리 프롬프트 예시에 직접 포함되어 있었다. 해당 예시를 상황별 마지막 반응으로 교체하고, 메타 종료 응답은 `AI_RESPONSE_INVALID`로 거절하도록 테스트를 추가했다.
- 수정 뒤 마무리 사례 3개를 3회씩 다시 실행했다. 9회 모두 새 질문과 메타 종료 문구가 없었고, 각 사례의 마지막 상황에 맞는 응답이었다.
