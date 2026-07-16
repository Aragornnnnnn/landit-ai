# LAN-167 메시지 피드백 판정 잠금과 문구 fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 1차 호출에서 점수 근거와 fallback 가능한 피드백 후보를 확보하고, 2차 호출은 잠긴 판정을 바꾸지 않은 채 사용자 문구만 개선하도록 재설계한다. 스피킹 서비스에서 대소문자와 문장부호 차이만을 교정하는 피드백은 서버 검증으로 차단한다.

**Architecture:** 1차 LLM 출력은 `scoreEvidence`와 사용자용 후보 문구만 포함하며 `messageId`와 `feedbackType`은 서버가 주입한다. 서버는 점수 근거로 유형을 확정하고 유형별 불필요 필드를 제거해 검증된 fallback 후보를 만든다. 2차 LLM은 잠긴 점수와 유형을 입력으로 받아 문구 필드만 반환한다. 2차 생성과 2차 구조 복구가 모두 실패하면 1차 후보를 사용한다. 1차 provider 실패 또는 1차 구조 복구 실패는 기존 503 또는 502 계약을 유지한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK, unittest.

## Success Criteria

- 정상 요청은 1차 후보 생성과 2차 문구 검수로 LLM을 2회 호출한다.
- `feedbackType`은 서버가 `scoreEvidence`에서 계산하며 2차 모델이 바꿀 수 없다.
- 1차 후보는 검증 완료 후에만 fallback 후보가 된다.
- 2차 생성 또는 2차 복구 실패 시 검증된 1차 후보가 캐시에 저장된다.
- 1차 provider 실패는 503, 1차 구조 복구 실패는 502를 유지하며 점수를 임의 생성하지 않는다.
- 사용자 발화와 교정 표현이 대소문자, 문장부호, 공백을 제외하고 같으면 유효하지 않은 개선 피드백으로 처리한다.
- 사용자용 설명에서 대문자, 소문자, 쉼표, 마침표, 문장부호만을 개선 이유로 제시하지 않는다.
- `scoreEvidence`, `detectedPatterns`, 내부 복구·fallback 지표는 외부 API와 OpenAPI에 노출하지 않는다.
- backend DTO와 DB 스키마는 변경하지 않는다.

## Non-Goals

- 점수 가중치, 세션 `nativeScore`, 별점 매핑을 변경하지 않는다.
- 질문 유형별 정규식이나 사례별 교정 문장 템플릿을 추가하지 않는다.
- 문장부호가 포함된 모든 `correctionExpression`을 거부하지 않는다. 실제 말하는 단어나 의미도 개선된 경우에는 정상 문장부호를 허용한다.
- 1차 호출 실패를 일반 문구나 기본 점수로 숨기지 않는다.
- 테스트에서 실제 LLM 네트워크를 호출하지 않는다.

---

### Task 1: 내부 후보 DTO와 서버 판정 조립 추가

**Files**

- Modify: `app/models/conversation.py:288-397`.
- Modify: `app/conversation/application/next_message_service.py:90-380`.
- Modify: `tests/test_conversation_api.py:645-1100`.

**Interfaces**

```python
class MessageFeedbackContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseLocaleAnalogy: str
    positiveFeedback: str | None = None
    feedbackDetail: str | None = None
    correctionExpression: str | None = None
    correctionReason: str | None = None
    benchmarkMessage: str | None = None


class MessageFeedbackCandidate(MessageFeedbackContent):
    scoreEvidence: MessageFeedbackScoreEvidence
```

`MessageFeedbackContent`는 현재 `MessageFeedbackData`의 문자열, 플레이스홀더, 내부 정책 문구 validator를 재사용한다. 유형별 필드 조합 검증은 `MessageFeedbackData`에 유지한다.

서버 조립 함수의 계약은 다음과 같다.

```python
def _feedback_type_from_score_evidence(
    score_evidence: MessageFeedbackScoreEvidence,
) -> FeedbackType:
    scores = (
        score_evidence.contextFit,
        score_evidence.clarity,
        score_evidence.languageAccuracy,
    )
    return FeedbackType.GOOD if all(score == 2 for score in scores) else (
        FeedbackType.NEEDS_IMPROVEMENT
    )


def _assemble_message_feedback(
    content: MessageFeedbackContent,
    *,
    message_id: int,
    score_evidence: MessageFeedbackScoreEvidence,
) -> MessageFeedbackData:
    values = content.model_dump()
    feedback_type = _feedback_type_from_score_evidence(score_evidence)
    if feedback_type == FeedbackType.GOOD:
        values.update(
            positiveFeedback=None,
            correctionExpression=None,
            correctionReason=None,
        )
    else:
        values.update(feedbackDetail=None, benchmarkMessage=None)
    return MessageFeedbackData(
        messageId=message_id,
        feedbackType=feedback_type,
        **values,
    )
```

- [ ] **Step 1: Write RED tests for server-owned identity and type.**

Add these tests to `MessageFeedbackApiTests`.

```python
def test_message_feedback_assembles_good_from_score_and_discards_needs_fields(self):
    content = MessageFeedbackContent.model_validate({
        "baseLocaleAnalogy": "질문에 맞게 자연스럽게 답했어요.",
        "positiveFeedback": "이 값은 제거되어야 해요.",
        "feedbackDetail": "핵심을 자연스럽게 전달했어요.",
        "correctionExpression": "Written-only correction.",
        "correctionReason": "이 값도 제거되어야 해요.",
        "benchmarkMessage": "질문에 맞는 핵심을 자연스럽게 전달했어요.",
    })
    score_evidence = MessageFeedbackScoreEvidence(
        contextFit=2,
        clarity=2,
        languageAccuracy=2,
    )

    feedback = _assemble_message_feedback(
        content,
        message_id=1001,
        score_evidence=score_evidence,
    )

    self.assertEqual(feedback.messageId, 1001)
    self.assertEqual(feedback.feedbackType, FeedbackType.GOOD)
    self.assertIsNone(feedback.positiveFeedback)
    self.assertIsNone(feedback.correctionExpression)
    self.assertIsNone(feedback.correctionReason)
```

Add the inverse NEEDS test and assert that `feedbackDetail` and `benchmarkMessage` are discarded while required correction fields remain.

- [ ] **Step 2: Verify RED.**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_assembles_good_from_score_and_discards_needs_fields
```

Expected: FAIL because `MessageFeedbackContent`, `MessageFeedbackCandidate`, and `_assemble_message_feedback` do not exist.

- [ ] **Step 3: Implement the minimal models and assembler.**

Move shared field validators from `MessageFeedbackData` to `MessageFeedbackContent`, then make `MessageFeedbackData` inherit from `MessageFeedbackContent` and add `messageId`, `feedbackType`, and the existing type-specific model validator. Add `MessageFeedbackCandidate` for the new path. Keep `MessageFeedbackEvaluation` temporarily so the current service remains valid until the atomic workflow replacement in Task 4.

Do not introduce a generic validator framework. Keep the two small server functions beside the message-feedback parse path.

- [ ] **Step 4: Verify GREEN and existing public model behavior.**

Run:

```bash
.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests
```

Expected: all existing message-feedback tests and the new assembler tests pass because the current evaluation path remains available during this preparatory change.

- [ ] **Step 5: Commit the DTO unit.**

```bash
git add app/models/conversation.py \
  app/conversation/application/next_message_service.py \
  tests/test_conversation_api.py
git commit -m "refactor: 메시지 피드백 판정을 서버 조립으로 전환"
```

### Task 2: 스피킹 표기 차이의 deterministic 검증 추가

**Files**

- Modify: `app/conversation/application/next_message_service.py:340-430`.
- Modify: `tests/test_conversation_api.py:900-1250`.

**Interfaces**

```python
_WRITTEN_FORM_FEEDBACK_TERMS = (
    "대문자",
    "소문자",
    "쉼표",
    "마침표",
    "문장부호",
    "capitalization",
    "uppercase",
    "lowercase",
    "comma",
    "period",
    "punctuation",
    "full stop",
)


def _normalize_spoken_form(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in normalized
    )
    return " ".join(without_punctuation.split())


def _validate_spoken_message_feedback(
    feedback: MessageFeedbackData,
    user_message: str,
) -> None:
    feedback_text = " ".join(
        value
        for value in (
            feedback.baseLocaleAnalogy,
            feedback.positiveFeedback,
            feedback.feedbackDetail,
            feedback.correctionReason,
            feedback.benchmarkMessage,
        )
        if value is not None
    ).casefold()
    if any(term in feedback_text for term in _WRITTEN_FORM_FEEDBACK_TERMS):
        raise AiResponseInvalidError("message_feedback_written_form_feedback")
    if (
        feedback.feedbackType == FeedbackType.NEEDS_IMPROVEMENT
        and feedback.correctionExpression is not None
        and _normalize_spoken_form(feedback.correctionExpression)
        == _normalize_spoken_form(user_message)
    ):
        raise AiResponseInvalidError("message_feedback_spoken_form_only")
```

`_validate_spoken_message_feedback`는 사용자용 설명 필드인 `baseLocaleAnalogy`, `positiveFeedback`, `feedbackDetail`, `correctionReason`, `benchmarkMessage`에서 금지 용어를 case-insensitive하게 검사한다. NEEDS의 `correctionExpression`과 사용자 발화가 `_normalize_spoken_form` 기준으로 같으면 `AiResponseInvalidError("message_feedback_spoken_form_only")`를 발생시킨다.

- [ ] **Step 1: Write RED tests for the screenshot regression.**

Add three focused tests.

```python
def test_message_feedback_rejects_case_and_punctuation_only_correction(self):
    feedback = needs_improvement_message_feedback(
        message_id=1001,
        correction_expression="Hi, my name is Sangmin.",
        correction_reason="인사 뒤에 쉼표를 넣고 이름을 대문자로 쓰면 자연스러워요.",
    )

    with self.assertRaisesRegex(
        AiResponseInvalidError,
        "message_feedback_written_form_feedback",
    ):
        _validate_spoken_message_feedback(feedback, "hi my name is sangmin")
```

Also assert the following boundaries.

- `I no like pizza` → `I don't like pizza.` is accepted because spoken words and grammar changed.
- `hi my name is sangmin` → `Hi, my name is Sangmin.` is rejected even if the reason avoids the forbidden words.
- A GOOD explanation containing `punctuation` or `문장부호` is rejected.

- [ ] **Step 2: Verify RED.**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_rejects_case_and_punctuation_only_correction
```

Expected: FAIL because the spoken-form validator does not exist.

- [ ] **Step 3: Implement normalization and validation.**

Use only Python `unicodedata` and string operations. Treat every Unicode punctuation category as spacing, then collapse whitespace. Do not remove letters or numbers, and do not compare semantic similarity.

Run this validation after server assembly for both the 1차 candidate and the 2차 copy. A candidate that fails this validation cannot become fallback.

- [ ] **Step 4: Verify GREEN.**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_rejects_case_and_punctuation_only_correction \
  tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_accepts_spoken_word_correction
```

Expected: both tests pass without rejecting meaningful spoken corrections.

- [ ] **Step 5: Commit the spoken-service guard.**

```bash
git add app/conversation/application/next_message_service.py \
  tests/test_conversation_api.py
git commit -m "fix: 표기 차이만 지적하는 스피킹 피드백 차단"
```

### Task 3: 1차 후보 생성과 제한된 구조 복구 재작성

**Files**

- Modify: `app/conversation/application/next_message_service.py:207-380`.
- Modify: `app/conversation/application/next_message_service.py:1150-1700`.
- Modify: `tests/test_conversation_api.py:730-1900`.

**Interfaces**

- `_generate_message_feedback_candidate(request: MessageFeedbackRequest, settings: Settings) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence, Any, bool]`.
- 반환값은 검증된 fallback 피드백, 잠긴 점수 근거, `detectedPatterns`, `candidate_was_repaired`다.
- `_parse_message_feedback_candidate(data, request) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence, Any]`는 LLM 응답에서 `detectedPatterns`를 분리하고, 단순 플레이스홀더를 보정한 뒤 `MessageFeedbackCandidate`를 검증한다.
- 첫 응답이 `AiResponseInvalidError`인 경우에만 한 번 구조 복구한다. 첫 provider 실패는 복구 없이 전파한다.

단순 플레이스홀더 보정은 대괄호 안이 영문 소문자와 공백만으로 구성되고 `your ` 접두어가 없는 경우만 적용한다.

```python
def _normalize_message_feedback_placeholders(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    expression = normalized.get("correctionExpression")
    if isinstance(expression, str):
        normalized["correctionExpression"] = re.sub(
            r"\[([a-z][a-z ]*)\]",
            r"[your \1]",
            expression,
        )
    return normalized
```

`[my hobby]`, 대문자·하이픈이 포함된 값, 중첩 괄호는 의미를 추측해 바꾸지 않고 기존 validator에서 거부한다.

- [ ] **Step 1: Write RED tests for candidate ownership and normalization.**

Add tests that prove all of these conditions.

- LLM candidate JSON has no `messageId` and no `feedbackType`.
- all-2 score produces GOOD and removes NEEDS-only fields without repair.
- a non-2 score produces NEEDS and removes GOOD-only fields without repair.
- `[hobby]` becomes `[your hobby]` before validation.
- a missing required content field triggers exactly one candidate repair call.
- candidate repair failure raises `AiResponseInvalidError` after exactly two helper calls.
- first provider failure raises `AiGenerationFailedError` after one helper call and is not repaired.

The key test shape is as follows.

```python
def test_candidate_type_is_derived_without_structure_repair(self):
    candidate = message_feedback_candidate(
        score_evidence={
            "contextFit": 2,
            "clarity": 2,
            "languageAccuracy": 2,
        },
        positive_feedback="이 값은 서버가 제거해요.",
    )
    request = MessageFeedbackRequest.model_validate(valid_message_feedback_payload())

    feedback, score_evidence, detected_patterns = (
        _parse_message_feedback_candidate(candidate, request)
    )

    self.assertEqual(feedback.messageId, request.messageId)
    self.assertEqual(feedback.feedbackType, FeedbackType.GOOD)
    self.assertEqual(score_evidence.contextFit, 2)
    self.assertIsNone(feedback.positiveFeedback)
    self.assertIsNone(detected_patterns)
```

- [ ] **Step 2: Verify RED.**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_conversation_api.MessageFeedbackApiTests.test_candidate_type_is_derived_without_structure_repair
```

Expected: FAIL because the current parser requires model-owned `messageId` and `feedbackType` and validates their consistency before server assembly.

- [ ] **Step 3: Implement the candidate parser and generator without switching the public flow.**

Change the first system prompt schema to output only these top-level fields.

```text
scoreEvidence
baseLocaleAnalogy
positiveFeedback
feedbackDetail
correctionExpression
correctionReason
benchmarkMessage
detectedPatterns
```

Do not include example `messageId` or `feedbackType`. Keep the existing scoring rubric, multiple-question completeness, fact preservation, filler, natural alternative, placeholder, and benchmark pattern instructions.

Add the new candidate parser and generator beside the current implementation, but keep `generate_message_feedback` wired to the current complete-evaluation path until Task 4 replaces generation and review together. The new parse order must be deterministic.

1. Copy raw data and remove `detectedPatterns`.
2. Normalize only supported shorthand placeholders.
3. Validate `MessageFeedbackCandidate`.
4. Derive `feedbackType` from `scoreEvidence`.
5. Assemble `MessageFeedbackData` with the request `messageId`.
6. Validate spoken-feedback rules against `request.userMessage`.
7. Return the validated fallback candidate and internal metadata.

- [ ] **Step 4: Verify GREEN.**

Run the new candidate-focused tests only:

```bash
.venv/bin/python -m unittest \
  tests.test_conversation_api.MessageFeedbackApiTests.test_candidate_type_is_derived_without_structure_repair \
  tests.test_conversation_api.MessageFeedbackApiTests.test_candidate_structure_repair_is_bounded \
  tests.test_conversation_api.MessageFeedbackApiTests.test_candidate_provider_failure_is_not_repaired
```

Expected: candidate ownership, one bounded repair, and provider error tests pass. Do not run or commit an intermediate public workflow that mixes the new candidate with the old full-evaluation reviewer.

- [ ] **Step 5: Continue directly to Task 4 without committing the intermediate path.**

Task 3 and Task 4 form one runtime data-flow change. Commit them together only after the message-feedback API tests pass.

### Task 4: 2차 문구 전용 검수와 candidate fallback 구현

**Files**

- Modify: `app/conversation/application/next_message_service.py:108-360`.
- Modify: `app/conversation/application/next_message_service.py:575-610`.
- Modify: `app/conversation/application/next_message_service.py:1700-2200`.
- Modify: `tests/test_conversation_api.py:730-2300`.

**Interfaces**

- `_review_message_feedback_copy(request: MessageFeedbackRequest, candidate: MessageFeedbackData, score_evidence: MessageFeedbackScoreEvidence, detected_patterns: Any, settings: Settings) -> tuple[MessageFeedbackData, Any, bool]`.
- 2차 출력은 `MessageFeedbackContent` 필드와 내부 후처리용 `detectedPatterns`만 포함하며 `messageId`, `feedbackType`, `scoreEvidence`를 반환하지 않는다.
- 검수 프롬프트 입력에는 잠긴 `feedbackType`과 `scoreEvidence`, 원본 요청, 1차 후보, 검증된 catalog 정의를 포함한다.
- 검수 결과는 1차의 `messageId`와 `scoreEvidence`로 서버 조립한 뒤 spoken validator를 통과해야 한다.
- 2차 `AiResponseInvalidError`는 한 번 복구한다. 복구도 실패하거나 2차 호출이 `AiGenerationFailedError`이면 1차 후보를 사용한다.

Cache entry를 다음과 같이 바꾼다.

```python
@dataclass(frozen=True)
class _MessageFeedbackCacheEntry:
    feedback: MessageFeedbackData
    score_evidence: MessageFeedbackScoreEvidence
    user_message: str
    candidate_was_repaired: bool
    copy_was_repaired: bool
    copy_was_fallback: bool
    expires_at: float
```

- [ ] **Step 1: Replace full-review tests with locked-copy RED tests.**

Delete assertions that allow the second model to change `feedbackType` or `scoreEvidence`. Add tests for these paths.

- Normal path performs two calls and stores `candidate_was_repaired=False`, `copy_was_repaired=False`, `copy_was_fallback=False`.
- A valid second copy cannot change score or type because those fields are absent from its schema.
- Invalid second copy followed by a valid repair performs three calls and stores `copy_was_repaired=True`.
- Invalid second copy and invalid repair use the first candidate and store `copy_was_fallback=True`.
- Second provider failure uses the first candidate without attempting structural repair.
- A fallback retains the first candidate's `detectedPatterns`; a valid second copy uses its own `detectedPatterns` for benchmark postprocessing.
- Candidate repair failure returns HTTP 502 and writes no cache entry.
- First provider failure returns HTTP 503, performs one call, and writes no cache entry.

```python
def test_review_copy_cannot_change_locked_score_or_feedback_type(self):
    candidate = needs_candidate(context_fit=1)
    reviewed_copy = needs_copy()
    fake_openai = FakeOpenAI(
        contents=[json.dumps(candidate), json.dumps(reviewed_copy)],
    )

    response = post_message_feedback(fake_openai, valid_message_feedback_payload())

    self.assertEqual(response.status_code, 202)
    entry = get_cached_message_feedback(100, 1001)
    self.assertEqual(entry.feedback.feedbackType, FeedbackType.NEEDS_IMPROVEMENT)
    self.assertEqual(entry.score_evidence.contextFit, 1)
    self.assertFalse(entry.copy_was_fallback)
```

- [ ] **Step 2: Verify RED.**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_conversation_api.MessageFeedbackApiTests.test_review_copy_cannot_change_locked_score_or_feedback_type
```

Expected: FAIL because the current reviewer returns a complete `MessageFeedbackEvaluation` and owns score/type.

- [ ] **Step 3: Implement copy-only review and bounded fallback.**

Wire the Task 3 candidate path and the new copy-only review in one change. Remove `MessageFeedbackEvaluation` and the old full-evaluation review parser only after no runtime or test reference remains. The normal flow must be explicit.

```python
candidate, score_evidence, detected_patterns, candidate_was_repaired = (
    _generate_message_feedback_candidate(request, resolved_settings)
)
copy_was_repaired = False
copy_was_fallback = False
try:
    feedback, detected_patterns, copy_was_repaired = _review_message_feedback_copy(
        request,
        candidate,
        score_evidence,
        detected_patterns,
        resolved_settings,
    )
except (AiGenerationFailedError, AiResponseInvalidError) as exc:
    logger.warning(
        "AI 메시지별 피드백 문구 검수에 실패해 생성 후보를 사용합니다. "
        "workflow=message_feedback_copy_fallback reason=%s "
        "sessionId=%s messageId=%s",
        getattr(exc, "reason", type(exc).__name__),
        request.sessionId,
        request.messageId,
    )
    feedback = candidate
    copy_was_fallback = True

feedback = _postprocess_message_feedback_benchmark(
    feedback,
    detected_patterns,
    request.userMessage,
)
```

Do not catch errors from 1차 generation in this fallback block. Keep logs limited to workflow, reason, sessionId, and messageId.

The 2차 repair prompt must return the same `MessageFeedbackContent` fields and `detectedPatterns`. It must not request a score or type correction.

- [ ] **Step 4: Verify GREEN.**

Run:

```bash
.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests
```

Expected: all message-feedback API tests pass with locked score/type, two normal calls, one bounded copy repair, safe candidate fallback, and unchanged external response.

- [ ] **Step 5: Commit the review path.**

```bash
git add app/conversation/application/next_message_service.py \
  app/models/conversation.py \
  tests/test_conversation_api.py
git commit -m "fix: 판정을 잠그고 문구 검수 실패에 후보 fallback 적용"
```

### Task 5: 프롬프트와 실제 스크린샷 회귀 fixture 갱신

**Files**

- Modify: `app/conversation/application/next_message_service.py:1150-2200`.
- Modify: `tests/fixtures/lan_167_feedback_quality_cases.json:1-35`.
- Modify: `tests/test_conversation_api.py:2200-2600`.
- Modify: `tests/test_quality_evaluation.py:100-180`.

- [ ] **Step 1: Write RED prompt-contract tests.**

Assert the first prompt excludes `messageId` and `feedbackType` from its output schema. Assert the second prompt excludes `messageId`, `feedbackType`, and `scoreEvidence` from its output schema while including the locked values as read-only context. Both schemas retain internal `detectedPatterns` for benchmark postprocessing.

Both prompts must say that capitalization and punctuation alone are not spoken-language improvements. The copy prompt must explicitly prohibit mentioning commas, periods, uppercase, lowercase, or punctuation as the learner-facing reason.

Avoid brittle whole-prompt equality. Assert only required schema keys and policy sentences.

- [ ] **Step 2: Replace the first fixed fixture with the screenshot case.**

Keep the fixed fixture at seven cases. Change `lan167-capitalization-and-period-only` to use the exact spoken boundary.

```json
{
  "caseId": "lan167-capitalization-and-period-only",
  "kind": "message-feedback",
  "expectedFeedbackType": "GOOD",
  "expectedContextFit": 2,
  "expectedMessageScoreRange": [100, 100],
  "forbiddenFeedbackTerms": [
    "대문자",
    "소문자",
    "쉼표",
    "마침표",
    "문장부호",
    "capitalization",
    "uppercase",
    "lowercase",
    "comma",
    "period",
    "punctuation",
    "full stop"
  ],
  "payload": {
    "evaluationContext": {
      "type": "AI_MESSAGE",
      "content": "What's your name?",
      "translatedContent": "이름이 뭐야?"
    },
    "userMessage": "hi my name is sangmin"
  }
}
```

Retain valid scenario, session, message, turn, and sequence fields from the current fixture. Keep the separate partial self-introduction case as NEEDS because its question asks for both a name and additional self-introduction.

- [ ] **Step 3: Verify RED.**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_conversation_api.MessageFeedbackApiTests \
  tests.test_quality_evaluation.QualityEvaluationTests
```

Expected: prompt and fixture assertions fail until schemas and evaluation expectations are updated.

- [ ] **Step 4: Implement prompt and fixture changes.**

Preserve the established quality rules from the current LAN-167 prompts.

- Multiple requests must all be answered for `contextFit=2`.
- A natural short answer can receive all 2s and 100 points.
- Meaning-neutral fillers and natural grammatical alternatives are not defects.
- User facts, intention, tense, and negation must be preserved.
- Missing personal information uses a specific `[your ...]` placeholder.
- Internal generation policy wording is not user-facing copy.
- GOOD benchmark handling remains server-side catalog postprocessing.

Do not reintroduce `coreAsks`, lexical overlap, or scenario-specific runtime templates.

- [ ] **Step 5: Verify GREEN.**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_conversation_api.MessageFeedbackApiTests \
  tests.test_quality_evaluation.QualityEvaluationTests
```

Expected: prompt contracts and all seven fixed-case fixture validations pass without a network call.

- [ ] **Step 6: Commit prompts and fixture.**

```bash
git add app/conversation/application/next_message_service.py \
  tests/fixtures/lan_167_feedback_quality_cases.json \
  tests/test_conversation_api.py \
  tests/test_quality_evaluation.py
git commit -m "test: 스피킹 표기 차이 회귀 사례 고정"
```

### Task 6: 품질 측정 지표와 운영 검증 갱신

**Files**

- Modify: `scripts/evaluate_conversation_quality.py:130-230`.
- Modify: `tests/test_quality_evaluation.py:260-430`.
- Modify: `checklist.md:383-395`.
- Modify: `context-notes.md` at the final LAN-167 section.

**Output fields**

Replace `reviewWasFallback` with these internal evaluation fields.

```text
candidateWasRepaired
copyWasRepaired
copyWasFallback
```

These fields belong only to the local quality report and cache entry. They must not appear in `MessageFeedbackData`, the API response, or OpenAPI.

- [ ] **Step 1: Write RED evaluator tests.**

Update the `SimpleNamespace` cache fixtures in `tests/test_quality_evaluation.py` and assert all three metrics for success, candidate repair, copy repair, and fallback paths. Add an explicit assertion that `reviewWasFallback` is absent from new results.

- [ ] **Step 2: Verify RED.**

Run:

```bash
.venv/bin/python -m unittest tests.test_quality_evaluation
```

Expected: FAIL because the evaluator and cache still expose `review_was_fallback`.

- [ ] **Step 3: Implement the metric rename.**

Update `_MessageFeedbackCacheEntry`, `_store_message_feedback`, all test fixtures, and `evaluate_message_feedback_case`. Do not add these values to structured logs or external DTOs.

- [ ] **Step 4: Run the complete local verification.**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall app tests scripts
.venv/bin/python -m pip check
.venv/bin/python -c \
  'from app.main import app; schema=app.openapi(); assert "scoreEvidence" not in str(schema); assert "candidateWasRepaired" not in str(schema); assert "copyWasFallback" not in str(schema)'
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 5: Run actual-model quality gates after explicit network execution is available.**

Run the repository's quality evaluator with the configured `OPENROUTER_API_KEY` and `openai/gpt-5.4-mini`.

1. Run the seven fixed cases three times each for 21 results.
2. Run the approved important-case fixture three times each if it is present.
3. Run the 115-case de-identified fixture if it is present and readable.

Accept the implementation only when these gates hold.

- Fixed 21 results have zero final failures.
- Fixed 21 results have zero feedback type, context range, score range, required placeholder, or forbidden written-form term violations.
- The screenshot case is GOOD with 100 points in all three runs and never mentions punctuation or capitalization.
- `copyWasFallback` is reported rather than treated as a request failure.
- Actual first-candidate and second-copy repair/fallback counts are recorded in `context-notes.md` without secret or raw prompt output.
- The 115-case run, when input is available, has zero final structural failures and zero missing message feedbacks.

If a gate fails, record the exact case ID and failure reason. Change code only when the failure maps to the approved invariants; do not add case-specific templates to make a metric pass.

- [ ] **Step 6: Update work records with measured evidence.**

Mark the LAN-167 checklist items complete only for checks that actually ran. Append the final commands, counts, remaining quality risk, and any unavailable dataset to `context-notes.md`.

- [ ] **Step 7: Commit the verification unit.**

```bash
git add scripts/evaluate_conversation_quality.py \
  tests/test_quality_evaluation.py \
  checklist.md \
  context-notes.md
git commit -m "test: LAN-167 생성과 문구 검수 지표 분리"
```

## Final Review Gate

Before publishing the branch, inspect the complete diff against `origin/release/LAN-161`.

```bash
git diff --stat origin/release/LAN-161...HEAD
git diff origin/release/LAN-161...HEAD -- \
  app/models/conversation.py \
  app/conversation/application/next_message_service.py \
  scripts/evaluate_conversation_quality.py \
  tests/test_conversation_api.py \
  tests/test_quality_evaluation.py \
  tests/fixtures/lan_167_feedback_quality_cases.json
```

Confirm every changed production line supports one of these responsibilities.

1. Server-owned identity and feedback type.
2. Validated first-candidate fallback.
3. Copy-only second-stage generation and bounded repair.
4. Spoken-form written-style rejection.
5. Internal repair and fallback measurement.

Remove any lexical semantic validator, per-question template, duplicate retry loop, or external-contract change that does not map to those responsibilities. Then rerun the complete local verification commands before creating or updating a PR.
