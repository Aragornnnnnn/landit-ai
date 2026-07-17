# LAN-169 속마음 톤 판정 개선 Implementation Plan

> **For agentic workers:** 구현 시 `superpowers:test-driven-development`를 사용하고, 아래 작업을 순서대로 진행한다.

**Goal:** 속마음이 답변 내용뿐 아니라 단답, 반복 거절, 공격적 말투, 상대를 향한 욕설·위협을 관계 맥락에 맞게 직접 반영하도록 개선한다.

**Architecture:** `inner-thought` API 계약과 정상 경로 1회 호출은 유지한다. LLM이 반환한 `answerCoverage`, `relationshipTone`, `directedAttack`으로 서버가 유형을 결정하고, 근거 형식이 잘못되면 기존 `innerThought`, `innerThoughtType`을 fallback으로 사용한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK, unittest.

## 제약 사항

- `POST /api/v1/conversation/inner-thought` 요청·응답과 OpenAPI 계약을 변경하지 않는다.
- 모든 단답을 부정 평가하지 않고 질문 충족도와 관계상 말투를 분리해서 본다.
- 상대를 향한 명시적인 욕설·모욕·위협은 질문에 답했더라도 `BAD`로 판정한다.
- 상황을 강조하는 비속어까지 무조건 `BAD`로 처리하지 않는다.
- 근거 없는 선의 해석, 사용자 성격 추론, 상대방의 다음 행동 계획을 속마음에 넣지 않는다.
- 반복 여부는 별도 판정 필드나 서버 규칙으로 만들지 않고 전체 대화 맥락으로만 사용한다.
- 정상 경로에 두 번째 LLM 호출, 입력 문장별 템플릿, 새 의존성을 추가하지 않는다.
- 상세 결정은 `docs/tasks/LAN-169/design.md`를 따른다.

---

### Task 1: 말투 판정 경계를 프롬프트 계약으로 고정

**Files:**

- Modify: `tests/test_conversation_api.py:530`
- Modify: `app/conversation/application/next_message_service.py:1130`

**Preserved interfaces:**

- `generate_inner_thought(request: InnerThoughtRequest, settings: Settings | None) -> InnerThoughtResponse`
- `InnerThoughtResponse(sessionId, messageId, innerThought, innerThoughtType)`

- [x] `InnerThoughtApiTests`에 아래 프롬프트 계약을 확인하는 실패 테스트를 추가한다.

```python
system_prompt = messages[0]["content"]
self.assertIn("Judge answer relevance and relationship tone separately", system_prompt)
self.assertIn("A first short answer can be NORMAL", system_prompt)
self.assertIn("Repeated refusal can be BAD", system_prompt)
self.assertIn("Directed profanity, insults, or threats must be BAD", system_prompt)
self.assertIn("Do not infer positive personality or intent without evidence", system_prompt)
```

- [x] 기존 프롬프트에서 새 assertion이 실패하는지 확인한다.

```bash
.venv/bin/python -m unittest tests.test_conversation_api.InnerThoughtApiTests
```

Expected: 새 정책 문구 assertion이 실패한다.

- [x] `_inner_thought_system_prompt()`에 아래 경계를 추가한다.
  - 질문에 답했는지와 관계상 말투가 적절한지를 별도로 판단한다.
  - `No.`, `Saturday.`처럼 질문에는 답했지만 짧고 무뚝뚝한 첫 답변은 `NORMAL`이 될 수 있다.
  - 전체 대화에서 같은 거절이 반복되거나 상대를 밀어내는 명령이면 `BAD`가 될 수 있다.
  - 상대를 향한 욕설·모욕·위협은 내용 충족 여부와 관계없이 `BAD`다.
  - `I hate it`처럼 상황에 대한 불만과 `I hate you`처럼 상대를 향한 공격을 구분한다.
  - 짧은 답변만으로 `친절하다`, `믿음이 간다`, `잘 아는 사람 같다` 같은 긍정적 특성을 추론하지 않는다.
  - `더 캐묻지 말아야겠다`, `선을 지켜야겠다` 같은 다음 행동 대신 현재 느끼는 감정을 쓴다.

```python
"Judge answer relevance and relationship tone separately. "
"A first short answer can be NORMAL when it answers the question but feels blunt or distant. "
"Repeated refusal can be BAD when the full conversation shows the user repeatedly avoiding engagement. "
"Directed profanity, insults, or threats must be BAD even when the utterance also answers the question. "
"Distinguish profanity used to emphasize a situation from an attack directed at the counterpart. "
"Do not infer positive personality or intent without evidence from the last utterance. "
"Describe the counterpart's present feeling, not what the counterpart plans to do next. "
```

- [x] 아래 대표 예시를 prompt examples에 추가한다.

```text
Question: Does Saturday or Sunday work better for you?
User: Saturday.
Expected: {"innerThought":"토요일이 좋다는 건 알겠는데, 대답이 꽤 짧네.","innerThoughtType":"NORMAL"}

Question: What's your whole daily rhythm like?
User after repeated refusals: nonono
Expected: {"innerThought":"계속 아니라고만 하니까 대화를 피하는 것 같아 좀 답답하다.","innerThoughtType":"BAD"}

User: My name is. Fuck you, man.
Expected: {"innerThought":"첫 만남부터 나한테 욕을 하다니, 당황스럽고 기분이 상한다.","innerThoughtType":"BAD"}
```

- [x] focused test를 다시 실행해 통과시킨다.

```bash
.venv/bin/python -m unittest tests.test_conversation_api.InnerThoughtApiTests
```

- [x] 논리 단위로 커밋한다.

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 사용자 말투를 속마음 판정에 반영"
```

### Task 2: 사용자 작성 테스트 데이터 기반 속마음 품질 평가 추가

**Files:**

- Create: `tests/fixtures/lan_169_inner_thought_quality_cases.json`
- Modify: `scripts/evaluate_conversation_quality.py:14-65,251-281`
- Modify: `tests/test_quality_evaluation.py`

**Interface extension:**

- `evaluate_cases(..., kind="inner-thought")`를 지원한다.
- 결과에 `innerThought`, `innerThoughtType`, `expectedTypeMatched`, `requiredTermMatched`, `foundForbiddenTerms`를 기록한다.

- [x] `tests/test_quality_evaluation.py`에 `generate_inner_thought()`를 mock한 실패 테스트를 추가한다.
  - 실제 유형이 `expectedInnerThoughtTypes` 중 하나인지 확인한다.
  - `requiredAnyTerms` 중 하나가 속마음에 포함됐는지 확인한다.
  - `forbiddenTerms`가 속마음에 포함되지 않았는지 확인한다.
  - fixture에 아래 8개 `caseId`가 모두 있는지 확인한다.

- [x] `scripts/evaluate_conversation_quality.py`에 아래 최소 분기를 추가한다.
  - `generate_inner_thought`, `InnerThoughtRequest`를 import한다.
  - `kind` 허용값과 CLI choices에 `inner-thought`를 추가한다.
  - `_evaluate_case()`에서 `_evaluate_inner_thought_case()`를 호출한다.
  - `_evaluate_inner_thought_case()`는 `InnerThoughtRequest.model_validate(case["payload"])`로 요청을 만들고 모델을 한 번 호출한다.
  - 문자열 비교는 기존 평가 코드처럼 `casefold()`를 사용한다.

- [x] 사용자가 직접 작성한 속마음 테스트 CSV의 아래 사례를 fixture로 고정한다.

| 메시지 | 질문과 사용자 답변 | 현재 결과와 문제 | 기대 경계 |
|---|---|---|---|
| 395 | 룸메 불편 경험 질문 → `No.` | `GOOD`, “다행이다”, “부딪힐 일은 적겠다”로 선의 추론 | `NORMAL`, 짧고 무뚝뚝한 반응 |
| 249 | 토요일·일요일 선택 질문 → `Saturday.` | `GOOD`, 내용 충족만 보고 말투를 반영하지 않음 | `NORMAL`, “대답이 짧네” 수준 |
| 335 | 여행지와 이유 질문 → `I don't know` | `NORMAL`이지만 “친절하게 이야기해줘서 다행”이라는 근거 없는 칭찬 | `NORMAL`, 막연함이나 답답함만 반영 |
| 357 | 여행지와 이유 질문 → `I recommend suwon` | `GOOD`, “한국을 잘 알고 믿음이 간다”로 과대 추론 | `NORMAL`, 장소만 답하고 이유가 빠졌음을 반영 |
| 380 | 이전에도 거절한 뒤 룸메 불편 경험 질문 → `nonono` | `NORMAL`, 반복 거절인데도 현재 감정보다 “캐묻지 말아야겠다”는 행동 계획 생성 | `BAD`, 반복 거절에 대한 답답함 |
| 233 | 물건 공유 기준 질문 → `I don't share with you my my stuff. I hate it. Don't do that. Just just yourself.` | `GOOD`, 질문에 답했다는 이유로 강한 말투를 누락 | `NORMAL` 또는 `BAD`, 불편함·당황·거리감 반영 |
| 168 | 첫 자기소개 질문 → `My name is. Fuck you, man.` | `BAD`, 욕설을 올바르게 감지한 control | 반드시 `BAD` 유지 |
| 400 | 생활 리듬 질문 → `I'm up at 9 am.` | `GOOD`, 구체적이고 관계상 자연스러운 control | `GOOD` 유지 |

- [x] 각 fixture의 문구 기대값을 아래처럼 고정한다.

| 메시지 | 허용 유형 | `requiredAnyTerms` | `forbiddenTerms` |
|---|---|---|---|
| 395 | `NORMAL` | `짧`, `무뚝뚝`, `거리`, `답답`, 거절·대화 의지 부족 표현 | `다행`, `친절`, `해야겠`, `말아야겠` |
| 249 | `NORMAL` | `짧`, `딱`, `까칠`, `차갑` | `어렵지 않`, `해야겠` |
| 335 | `NORMAL` | `모르`, `막연`, `답답` | `친절`, `다행`, `해야겠`, `말아야겠` |
| 357 | `NORMAL` | `수원`, `이유`, `짧` | `믿음`, `잘 아는` |
| 380 | `BAD` | `답답`, `무시`, `거절`, `불편` | `해야겠`, `말아야겠` |
| 233 | `NORMAL`, `BAD` | `강`, `불편`, `당황`, `거리`, `상처`, `불쾌` 등 | `맞겠다`, `지켜야겠` |
| 168 | `BAD` | `욕`, `기분`, `불쾌`, `당황`, `상처` | `해야겠`, `말아야겠` |
| 400 | `GOOD` | `규칙`, `다행`, `안심`, `좋` | `까칠`, `무례`, `불쾌` |

- [x] 평가 도구 단위 테스트를 통과시킨다.

```bash
.venv/bin/python -m unittest tests.test_quality_evaluation.QualityEvaluationTests
```

- [x] 논리 단위로 커밋한다.

```bash
git add scripts/evaluate_conversation_quality.py tests/fixtures/lan_169_inner_thought_quality_cases.json tests/test_quality_evaluation.py
git commit -m "test: 테스트 데이터 기반 속마음 품질 평가 추가"
```

### Task 3: 구조화 판정과 fallback 추가

**Files:**

- Modify: `app/models/conversation.py`
- Modify: `app/conversation/application/next_message_service.py`
- Modify: `tests/test_conversation_api.py`

**Preserved interface:**

- `generate_inner_thought(request, settings) -> InnerThoughtResponse`
- `POST /api/v1/conversation/inner-thought` 요청·응답 필드

- [ ] 변경 전 고정 사례 8건을 1회 실행해 품질과 총 소요 시간을 기준값으로 기록한다.

```bash
/usr/bin/time -p /Users/sangmin8817/Soma/landit-ai/.venv/bin/python \
  scripts/evaluate_conversation_quality.py \
  --cases tests/fixtures/lan_169_inner_thought_quality_cases.json \
  --runs 1 \
  --kind inner-thought \
  --output /tmp/landit-ai-lan-169-before.json
```

- [x] `InnerThoughtApiTests`에 먼저 아래 실패 테스트를 추가한다.
  - 전체 근거가 유효하면 LLM 유형 대신 서버 결정표를 사용한다.
  - `directedAttack=true`, `HOSTILE`, `UNRELATED`는 `BAD`가 된다.
  - `BLUNT`, `PARTIAL`, `DECLINED`는 `NORMAL`, `COMPLETE`와 `WARM` 또는 `NEUTRAL` 조합은 `GOOD`이 된다.
  - 근거 필드가 없고 기존 두 필드가 유효하면 추가 호출 없이 fallback한다.
  - 기존 두 필드까지 잘못되면 한 번 복구하고, 복구도 실패하면 502를 반환한다.
  - 정상 결과는 OpenAI 호출이 1회인지 확인한다.

```bash
/Users/sangmin8817/Soma/landit-ai/.venv/bin/python \
  -m unittest tests.test_conversation_api.InnerThoughtApiTests
```

Expected: 새 판정·fallback 테스트가 실패한다.

- [x] `AnswerCoverage`, `RelationshipTone`, `InnerThoughtCandidate(extra="forbid")`를 추가하고 prompt 출력 스키마를 확장한다.
- [x] `next_message_service.py`에 작은 순수 결정 함수와 파싱 흐름을 추가한다.
  - 전체 근거가 유효하면 `design.md` 우선순위로 유형을 정한다.
  - 근거만 잘못되면 기존 두 필드를 사용하고 fallback 사실만 기록한다.
  - 기존 두 필드까지 잘못되면 형식 복구를 한 번만 호출한다.
  - 사용자 원문과 모델 원문은 로그에 남기지 않는다.
- [x] focused test를 다시 실행해 통과시킨다.
- [x] 아래 논리 단위로 커밋한다.

```bash
git add app/models/conversation.py \
  app/conversation/application/next_message_service.py \
  tests/test_conversation_api.py
git commit -m "fix: 판정 근거로 속마음 유형을 확정"
```

### Task 4: 실제 모델과 전체 회귀 검증

**Files:**

- Modify: `docs/tasks/LAN-169/plan.md`

- [x] 변경 후 고정 사례 8개를 실제 설정 모델로 각 3회 실행한다.

```bash
/Users/sangmin8817/Soma/landit-ai/.venv/bin/python \
  scripts/evaluate_conversation_quality.py \
  --cases tests/fixtures/lan_169_inner_thought_quality_cases.json \
  --runs 3 \
  --kind inner-thought \
  --output /tmp/landit-ai-lan-169-inner-thought-results.json
```

Expected: 24개 결과가 모두 허용 유형을 만족하고, 필수 감정어가 하나 이상 있으며, 금지 표현이 없다.

- [x] 변경 전과 같은 조건을 `/usr/bin/time -p`로 실행해 정상 경로 호출 수와 총 소요 시간을 비교한다. 유의미하게 느려지면 완료하지 않고 원인을 기록한다.

- [ ] prod·develop 데이터를 동일한 컬럼으로 각각 추출해 아래 회귀를 확인한다.
  - 상대를 향한 욕설·모욕·위협이 `GOOD` 또는 `NORMAL`로 저장된 사례가 남아 있지 않은지 확인한다.
  - 단답이 무조건 `GOOD`이거나 근거 없는 긍정 추론으로 생성되지 않는지 확인한다.
  - 정상적인 구체 답변의 `GOOD` 판정이 불필요하게 하락하지 않는지 확인한다.
  - 한 환경의 데이터에 접근할 수 없으면 완료 처리하지 않고 환경명과 blocker를 기록한다.

- [x] 전체 회귀 검증을 실행한다.

```bash
/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/landit-ai-lan-169-pycache \
  /Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m compileall -q app tests scripts
/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m pip check
git diff --check
```

Expected: 모든 명령이 통과하고 `inner-thought` API 필드에 변경이 없다.

- [x] 모델명, 실행 시각, 24개 성공 수, 실패 사례, prod·develop 확인 결과, 실행 명령을 이 문서 하단 `구현 및 검증 결과`에 기록한다. 별도 `checklist.md`, `context-notes.md`, 평가 문서는 만들지 않는다.

## 완료 기준

- [x] 단답과 반복 거절이 같은 기준으로 평가되지 않는다.
- [x] 상대를 향한 욕설·모욕·위협은 `BAD`로 평가된다.
- [x] 공격적인 답변이 내용 충족만으로 `GOOD`이 되지 않는다.
- [x] 근거 없는 선의 해석과 다음 행동 계획이 속마음에서 제거된다.
- [x] 정상 `GOOD` control을 포함한 테스트 데이터 8개 사례가 실제 모델 3회 검증을 통과한다.
- [x] 전체 unittest, compileall, pip check, diff check가 통과한다.

## 구현 및 검증 결과 기록 위치

구현 중 발견 사항, 계획 변경, 실제 검증 결과는 이 섹션에만 이어서 기록한다.

### 2026-07-17 구현 결과

- `63b0b64`에서 답변 내용과 관계상 말투를 분리해 판정하고, 첫 단답, 반복 거절, 상대를 향한 욕설·모욕·위협의 경계를 prompt와 API 회귀 테스트에 추가했다.
- `b6f5394`에서 `inner-thought` 평가 분기와 사용자 작성 테스트 CSV 기반 8개 fixture를 추가했다.
- `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`가 121개 테스트를 통과했다. worktree에 `.venv`가 없어 기존 저장소의 가상환경을 사용했다.
- `PYTHONPYCACHEPREFIX=/tmp/landit-ai-lan-169-pycache /Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m compileall -q app tests scripts`, `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m pip check`, `git diff --check`를 통과했다.
- OpenRouter 전송 승인 후 `openai/gpt-5.4-mini`로 8개 사례를 3회씩 실행했다. 구조화 판정 도입 전 프롬프트 보강 결과는 14/24, 16/24, 20/24까지 개선됐다.
- 20/24 결과의 미통과 4건은 메시지 395 `No.` 1회가 `BAD`로, 메시지 249 `Saturday.` 3회가 `GOOD`으로 분류된 사례다. 둘 다 기대 유형은 `NORMAL`이다.
- `_request_json_completion()`은 이미 `temperature=0`으로 호출한다. 그 뒤 유형 정의와 self-check를 더 강하게 바꾼 실험은 16/24, 17/24로 하락해 현재 코드에는 반영하지 않았다.
- 당시 프롬프트만으로 24/24를 보장하려면 추가 반복이 아니라 deterministic한 서버 후처리 또는 모델 변경이 필요하다고 판단했고, 이후 승인된 설계에 따라 서버 판정을 적용했다.
- prod·develop 직접 데이터 추출 권한과 develop export가 현재 제공되지 않아, 환경별 재검증은 아직 실행하지 못했다.
- 구조화 근거가 유효하면 `directedAttack`, `relationshipTone`, `answerCoverage` 우선순위로 서버가 최종 유형을 결정하도록 구현했다. 정상 경로는 LLM 1회 호출을 유지한다.
- 근거 필드만 잘못되면 유효한 `innerThought`, `innerThoughtType`을 추가 호출 없이 사용하고, 두 핵심 필드까지 잘못된 경우에만 형식 복구를 1회 호출한다.
- 구조화 판정 구현 전후 focused test에서 실패를 확인한 뒤 `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest tests.test_conversation_api.InnerThoughtApiTests` 9개와 `tests.test_quality_evaluation.QualityEvaluationTests` 12개가 통과했다.
- 전체 회귀 검증에서 unittest 125개, compileall, pip check, `git diff --check`가 통과했다. OpenAPI 스키마에서 `InnerThoughtRequest`, `InnerThoughtResponse` 필드가 유지되고 내부 `InnerThoughtCandidate`가 노출되지 않는 것도 확인했다.
- 사용자가 제공한 CSV는 실제 사용자 대화가 아니라 직접 작성한 테스트 데이터임을 확인했다. 해당 분류와 OpenRouter 전송 승인을 근거로 구조화 판정 적용 후 검증을 실행했다.
- 최종 검증은 `2026-07-17T10:58:38Z`, `openai/gpt-5.4-mini`에서 8개 사례를 3회씩 실행했다. 유형, 필수 감정 표현, 금지 표현이 모두 24/24를 통과했고 실패 사례는 없다.
- 구현 전 `a67bef9`와 최종 코드를 동일한 24회 조건으로 비교한 총 소요 시간은 각각 29.73초와 30.68초였다. 정상 경로 호출은 모두 1회이며 약 3.2% 차이는 네트워크 변동 범위로 판단했다.
- 시스템 프롬프트는 중복 설명을 줄여 구현 전 5,968자에서 최종 5,962자로 감소했다.
