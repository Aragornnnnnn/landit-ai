# LAN-182 메시지 피드백 품질과 복구 안정화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 표시 가능한 메시지 피드백은 내부 판정 불일치 때문에 재생성하지 않고, 실제 구조·근거·표시 품질 실패만 복구하면서 운영 품질 사례를 방지한다.

**Architecture:** Pydantic 구조 검증과 원문·표시 품질 검증은 강하게 유지하고, 점수·근거 간 중복 계약만 복구 가능한 일관성 경고로 분리한다. LLM이 만들 필요가 없는 대표 차원과 benchmark 출력을 제거하고, 원문 근거는 제한된 토큰 정규화로만 비교한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK, `unittest`.

## Global Constraints

- 외부 API, OpenAPI, 점수 산식과 별점 기준을 변경하지 않는다.
- 정상 메시지 피드백 LLM 호출 횟수는 2회로 유지한다.
- 모델, provider, 최대 출력 토큰과 새 의존성을 변경하지 않는다.
- 사용자 원문과 raw 모델 응답을 로그에 남기지 않는다.
- 제품 코드는 회귀 테스트를 먼저 실패시킨 뒤 최소 범위로 수정한다.

---

### Task 1: 복구 가능한 판정 불일치 분리

**Files:**
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `AiResponseInvalidError.reason`, `_parse_message_feedback_candidate`.
- Produces: `_RECOVERABLE_MESSAGE_FEEDBACK_CONSISTENCY_REASONS`, `_parse_message_feedback_candidate(..., enforce_consistency: bool = True)`.

- [x] **Step 1: 추가 복구 없이 일관성 불일치 후보를 저장하는 실패 테스트를 작성한다.**

```python
def test_message_feedback_consistency_mismatch_skips_candidate_repair(self):
    inconsistent = message_feedback_candidate_with_evidence(
        needs_improvement_message_feedback(1001),
    )
    fake_openai = FakeOpenAI(content=json.dumps(inconsistent))
    app = create_app(make_settings(message_feedback_review_enabled=False))
    # 응답은 PREPARING, 호출은 1회, candidate_was_repaired는 False여야 한다.
```

- [x] **Step 2: 강한 검증 실패는 기존처럼 복구 후 `FAILED`인지 확인하는 테스트를 유지·보강한다.**

```python
def test_message_feedback_candidate_repair_failure_returns_failed_without_cache(self):
    # feedbackDetail이 없는 GOOD 후보를 두 번 반환한다.
    # 응답은 FAILED이고 캐시는 비어 있어야 한다.
```

- [x] **Step 3: 대상 테스트를 실행해 RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.ConversationApiTests.test_message_feedback_consistency_mismatch_skips_candidate_repair`

Expected: 후보 복구가 호출되어 호출 횟수 또는 복구 플래그 단언이 실패한다.

- [x] **Step 4: 강한 검증과 일관성 검증을 분리한다.**

```python
_RECOVERABLE_MESSAGE_FEEDBACK_CONSISTENCY_REASONS = frozenset({
    "message_feedback_context_evidence",
    "message_feedback_clarity_evidence",
    "message_feedback_language_accuracy_evidence",
    "message_feedback_context_primary_dimension",
    "message_feedback_actionable_primary_dimension",
})

def _parse_message_feedback_candidate(
    data: dict[str, Any],
    request: MessageFeedbackRequest,
    *,
    reject_generic_placeholder: bool = False,
    enforce_consistency: bool = True,
) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence,
           MessageFeedbackAdjudicationEvidence, Any]:
    # 구조·원문·표시 품질 검증은 항상 실행한다.
    # 점수·근거 일관성 검증만 enforce_consistency로 제어한다.
```

- [x] **Step 5: 일관성 불일치는 복구하지 않고 경고 후 같은 후보를 파싱한다.**

```python
try:
    parsed = _parse_message_feedback_candidate(candidate_data, request)
except AiResponseInvalidError as exc:
    if exc.reason not in _RECOVERABLE_MESSAGE_FEEDBACK_CONSISTENCY_REASONS:
        raise
    parsed = _parse_message_feedback_candidate(
        candidate_data,
        request,
        enforce_consistency=False,
    )
```

로그는 `workflow=message_feedback_candidate_consistency_warning`과 `reason`, `sessionId`, `messageId`를 포함한다.

- [x] **Step 6: 대상 테스트와 전체 대화 API 테스트를 실행한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api`

Expected: 모든 테스트가 통과한다.

- [x] **Step 7: 논리 변경을 커밋한다.**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 판정 일관성 불일치의 전체 후보 복구 제거"
```

### Task 2: 중복 출력과 원문 매칭 단순화

**Files:**
- Modify: `app/models/conversation.py`
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `MessageFeedbackCandidate`, `_validate_message_feedback_adjudication`.
- Produces: `_evidence_occurs_once(source: str, excerpt: str) -> bool`, 서버가 확인하는 대표 교정 근거.

- [x] **Step 1: `primaryFeedbackDimension`이 없는 후보와 제한된 원문 매칭 테스트를 작성한다.**

```python
def test_message_feedback_candidate_does_not_require_primary_dimension(self):
    candidate = message_feedback_candidate_with_evidence(good_message_feedback(1001))
    candidate.pop("primaryFeedbackDimension", None)
    parsed = _parse_message_feedback_candidate(candidate, request)
    self.assertEqual(parsed[0].feedbackType.value, "GOOD")

def test_evidence_match_accepts_unique_case_punctuation_whitespace_difference(self):
    self.assertTrue(_evidence_occurs_once("Why do you wanna know that?", "why do you wanna know that"))

def test_evidence_match_rejects_ambiguous_or_spelling_changed_excerpt(self):
    self.assertFalse(_evidence_occurs_once("yes, yes", "YES"))
    self.assertFalse(_evidence_occurs_once("I like pizza", "I love pizza"))
```

- [x] **Step 2: 대상 테스트를 실행해 RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api`

Expected: 필수 대표 차원 또는 exact substring 검증 때문에 새 테스트가 실패한다.

- [x] **Step 3: LLM 후보에서 대표 차원을 제거하고 실제 교정 근거를 서버가 확인한다.**

```python
class MessageFeedbackCandidate(MessageFeedbackContent):
    scoreEvidence: MessageFeedbackScoreEvidence
    coverageEvidence: list[MessageFeedbackCoverageEvidence] = Field(min_length=1)
    ignoredSpeechArtifacts: list[str]
    actionableIssues: list[MessageFeedbackActionableIssue]
```

`GOOD`은 대표 근거 검증을 생략한다. 개선 후보는 구체적 placeholder가 있는 누락 문맥 또는 `correctionExpression`에 포함된 하나의 `actionableIssue.correctionExcerpt`가 있어야 한다.

- [x] **Step 4: 비교 전용 토큰 정규화를 구현한다.**

```python
def _evidence_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    comparable = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in normalized
    )
    return comparable.split()

def _evidence_occurs_once(source: str, excerpt: str) -> bool:
    # exact substring을 우선하고, 실패한 경우 동일 토큰 구간이 한 번일 때만 True를 반환한다.
```

- [x] **Step 5: LLM 출력 스키마에서 `primaryFeedbackDimension`과 `benchmarkMessage`를 제거한다.**

`MessageFeedbackContent.benchmarkMessage`는 외부 응답 호환성을 위해 유지하고, 후보 출력에서는 생략해 서버의 catalog/default 후처리만 사용한다.

- [x] **Step 6: 전체 대화 API 테스트를 실행한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api`

Expected: 모든 테스트가 통과한다.

- [x] **Step 7: 논리 변경을 커밋한다.**

```bash
git add app/models/conversation.py app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "refactor: 메시지 피드백 중복 계약과 근거 매칭 단순화"
```

### Task 3: 운영 품질 사례 회귀 방지

**Files:**
- Create: `tests/fixtures/lan_182_feedback_quality_cases.json`
- Modify: `app/conversation/application/next_message_service.py`
- Modify: `tests/test_quality_evaluation.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `_message_feedback_evidence_policy`, 생성·검수 프롬프트, 품질 평가 fixture 형식.
- Produces: LAN-182 익명화 품질 사례 4건.

- [x] **Step 1: 운영 품질 사례 fixture 계약 테스트를 작성한다.**

fixture는 다음 문제를 포함한다.

- 완성된 자기소개에 무관한 취미 조언을 붙이지 않는다.
- 사용하지 않은 3인칭 단수 패턴을 benchmark로 칭찬하지 않는다.
- `Don't worry about`처럼 끝나지 않은 구를 `GOOD`으로 판정하지 않는다.
- 교정 표현에 원문에 없는 성공·결과 문장을 추가하지 않는다.

- [x] **Step 2: 프롬프트 계약 테스트를 작성하고 RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation tests.test_conversation_api`

Expected: 새 품질 규칙 문자열 또는 fixture 부재로 실패한다.

- [x] **Step 3: 생성·검수 프롬프트에 최소 수정과 미완성 발화 기준을 추가한다.**

```text
correctionExpression must be a minimal correction of the user's meaning.
Do not add a new proposition, result, experience, reason, or evaluation with no counterpart in the user utterance.
An utterance ending in an unfinished phrase or a word that still requires its complement is not a complete GOOD answer.
```

- [x] **Step 4: 품질 평가 테스트를 실행한다.**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation tests.test_conversation_api`

Expected: 모든 테스트가 통과한다.

- [x] **Step 5: 실제 OpenRouter 설정이 있으면 LAN-180과 LAN-182 fixture를 각각 3회 평가한다.**

Run: `.venv/bin/python scripts/evaluate_conversation_quality.py --cases tests/fixtures/lan_182_feedback_quality_cases.json --runs 3 --kind message-feedback --output /tmp/lan-182-quality.json`

Expected: 모든 결과의 `expectationMatched`가 `true`이고 최종 구조 실패가 0건이다. 설정이 없으면 미실행 이유를 계획과 PR에 기록한다.

- [x] **Step 6: 품질 변경을 커밋한다.**

```bash
git add app/conversation/application/next_message_service.py tests/fixtures/lan_182_feedback_quality_cases.json tests/test_quality_evaluation.py tests/test_conversation_api.py
git commit -m "fix: 운영 메시지 피드백 품질 사례 회귀 방지"
```

### Task 4: PR 메타데이터 문서와 최종 검증

**Files:**
- Modify: `CONTRIBUTING.md`
- Modify: `AGENTS.md`
- Modify: `.github/pull_request_template.md`
- Modify: `docs/tasks/LAN-182/plan.md`

**Interfaces:**
- Produces: PR 생성 시 작업 label과 PR 작성자 assignee를 요구하는 동일 규칙.

- [x] **Step 1: 세 문서에 같은 PR 메타데이터 규칙을 반영한다.**

```markdown
- PR 생성 시 작업 성격에 맞는 label을 설정합니다.
- PR 생성 시 PR 작성자를 assignee로 설정합니다.
```

PR 템플릿 체크리스트에는 두 항목을 각각 추가한다.

- [x] **Step 2: 전체 unittest를 실행한다.**

Run: `.venv/bin/python -m unittest discover -s tests`

Expected: 모든 테스트가 통과한다.

- [x] **Step 3: OpenAPI와 diff를 검증한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_openapi_uses_evaluation_context_contract`

Run: `git diff --check`

Expected: 두 명령이 통과하고 `scoreEvidence`, 내부 근거와 제거한 후보 필드가 외부 스키마에 노출되지 않는다.

- [x] **Step 4: 계획에 실제 검증 결과와 남은 위험을 기록한다.**

실행 명령, 테스트 수, 실제 모델 평가 실행 여부와 배포 후 확인할 로그 workflow를 적는다.

- [x] **Step 5: 문서 변경을 커밋한다.**

```bash
git add CONTRIBUTING.md AGENTS.md .github/pull_request_template.md docs/tasks/LAN-182/plan.md
git commit -m "docs: PR label과 assignee 설정 규칙 반영"
```

## 실행 결과

- 전체 unittest는 `.venv/bin/python -m unittest discover -s tests` 기준으로 실행했으며 185건이 통과했다. 작업 worktree에는 별도 `.venv`가 없어 기준 저장소의 가상환경을 사용했다.
- OpenAPI 계약 테스트 1건과 `git diff --check`가 통과했다.
- LAN-182 품질 사례는 4건을 각각 3회 평가했다. 최종 전체 실행에서 11건이 통과했고 `MISSING` coverage의 중복 `answerExcerpt` 때문에 1건이 `FAILED`였다. 해당 값을 서버에서 `null`로 정규화한 뒤 실패 사례를 3회 재평가해 3건 모두 기대 판정과 점수 범위를 통과했다.
- LAN-180 기존 품질 사례 6건을 각각 3회 평가했으며 18건 모두 기대 판정, 점수 범위와 금지 문구 기준을 통과했고 `FAILED`는 0건이었다.
- 실제 평가 중 문장부호만 다른 교정을 언어 오류로 판정하는 사례와 표시 가능한 복구 후보가 정책 검증에 실패하는 사례를 확인했다. 문장부호만 다른 actionable issue는 거부하고, 최초·복구 후보 중 Pydantic 필수 계약을 통과한 결과를 제한적으로 fallback하도록 보강했다.
- 배포 후 `message_feedback_candidate_repair`, `message_feedback_candidate_fallback`, `message_feedback_candidate_consistency_warning`, `message_feedback_copy_fallback`, `message_feedback_failed`를 `validationType`별로 확인한다.

## 남은 위험

- 실제 모델 평가는 확률적이므로 반복 실행이 운영 품질을 보장하지 않는다. 배포 후 `FAILED`와 fallback 비율을 계속 관찰해야 한다.
- 제한적 fallback은 사용자 차단을 막지만 정책 검증에 실패한 표시 문구를 제공할 수 있다. `validationType=DISPLAY`과 `validationType=EVIDENCE` fallback 비율이 높으면 프롬프트와 모델 출력을 추가 분석한다.
