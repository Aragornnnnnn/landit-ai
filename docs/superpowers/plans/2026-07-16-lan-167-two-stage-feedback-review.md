# LAN-167 메시지 피드백 생성·검수 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 과적합된 판정·문구 분리 규칙을 제거하고, 전체 피드백 생성 후 전체 피드백을 검수·재작성하는 정상 2회 호출 구조로 메시지 피드백을 안정화한다.

**Architecture:** 첫 번째 LLM은 `MessageFeedbackEvaluation` 전체 JSON과 내부 `detectedPatterns`를 생성한다. 두 번째 LLM은 원본 요청과 1차 후보를 받아 최종 전체 JSON을 다시 작성한다. 서버는 Pydantic 스키마, 점수와 GOOD/NEEDS_IMPROVEMENT 관계, 패턴 catalog, 플레이스홀더 문법, 내부 정책 문구만 검증하며 자연어 의미를 영문 키워드나 어휘 겹침으로 다시 판정하지 않는다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK, unittest.

**Implementation status:** 2026-07-17에 Task 1~3과 Task 4의 로컬 검증을 완료했다. 전체 실제 사용자 발화 운영 재평가는 별도 품질 측정으로 남긴다.

## Global Constraints

- 정상 메시지 피드백 요청은 LLM 호출을 정확히 2회 수행한다.
- 구조 검증 실패만 각 단계에서 한 번 복구한다. provider와 네트워크 실패는 복구하지 않는다.
- 외부 API, OpenAPI, backend DTO, DB 스키마를 변경하지 않는다.
- `scoreEvidence`, `detectedPatterns`는 내부 데이터이며 외부 응답에 노출하지 않는다.
- 세션 점수·별점과 검증된 `benchmarkMessage` catalog 후처리를 유지한다.
- 새 사례별 정규식, 질문 키워드 분기, 안전 교정 템플릿을 추가하지 않는다.
- 테스트는 실제 LLM 네트워크를 호출하지 않는다.

---

### Task 1: 전체 피드백 내부 DTO와 구조 계약 복원

**Files:**

- Modify: `app/models/conversation.py:335-470`.
- Modify: `tests/test_conversation_api.py:730-1100`.

**Interfaces:**

- Produce `MessageFeedbackEvaluation(MessageFeedbackData)` with `scoreEvidence: MessageFeedbackScoreEvidence`.
- `MessageFeedbackEvaluation.score_evidence_must_match_feedback_type()` rejects GOOD with a non-2 score and NEEDS_IMPROVEMENT with all 2 scores.
- Remove `MessageFeedbackCoreAsk`, `MessageFeedbackLanguageCorrection`, `MessageFeedbackJudgement`, `MessageFeedbackCopy`.

- [ ] **Step 1: Write the failing test.**

```python
def test_message_feedback_evaluation_rejects_type_and_score_mismatch(self):
    payload = good_message_feedback()
    payload["scoreEvidence"] = {
        "contextFit": 2,
        "clarity": 2,
        "languageAccuracy": 1,
    }

    with self.assertRaises(ValueError):
        conversation_models.MessageFeedbackEvaluation.model_validate(payload)
```

Delete tests that directly assert `MessageFeedbackJudgement`, `MessageFeedbackCopy`, `coreAsks`, or `languageCorrections`. Retain tests for public `MessageFeedbackData` contracts.

- [ ] **Step 2: Verify RED.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_evaluation_rejects_type_and_score_mismatch`

Expected: FAIL because the current module exposes split judgement/copy models instead of the restored evaluation contract.

- [ ] **Step 3: Implement the minimal DTO.**

```python
class MessageFeedbackEvaluation(MessageFeedbackData):
    scoreEvidence: MessageFeedbackScoreEvidence

    @model_validator(mode="after")
    def score_evidence_must_match_feedback_type(self) -> Self:
        all_scores_are_max = all(
            score == 2
            for score in (
                self.scoreEvidence.contextFit,
                self.scoreEvidence.clarity,
                self.scoreEvidence.languageAccuracy,
            )
        )
        if (self.feedbackType == FeedbackType.GOOD) != all_scores_are_max:
            raise ValueError("scoreEvidence must match feedbackType")
        return self
```

- [ ] **Step 4: Verify GREEN.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS for retained public feedback contract and restored evaluation contract tests.

- [ ] **Step 5: Commit.**

```bash
git add app/models/conversation.py tests/test_conversation_api.py
git commit -m "refactor: 메시지 피드백 내부 DTO를 전체 평가로 단순화"
```

### Task 2: 2회 전체 생성·검수와 구조 복구 구현

**Files:**

- Modify: `app/conversation/application/next_message_service.py:20-700`.
- Modify: `tests/test_conversation_api.py:900-2300`.

**Interfaces:**

- Add `_parse_message_feedback_candidate(data: dict[str, Any], expected_message_id: int) -> tuple[MessageFeedbackEvaluation, Any]`.
- Change `_MessageFeedbackCacheEntry` to retain `feedback`, `score_evidence`, `user_message`, `expires_at` only.
- `generate_message_feedback()` performs first candidate call, second review call, benchmark postprocess and cache store.

- [ ] **Step 1: Write the failing test.**

```python
def test_message_feedback_uses_reviewed_full_candidate(self):
    first = needs_improvement_message_feedback(1001)
    first["scoreEvidence"] = {
        "contextFit": 1,
        "clarity": 2,
        "languageAccuracy": 2,
    }
    reviewed = good_message_feedback()
    reviewed["scoreEvidence"] = {
        "contextFit": 2,
        "clarity": 2,
        "languageAccuracy": 2,
    }
    fake_openai = FakeOpenAI(contents=[json.dumps(first), json.dumps(reviewed)])

    response = post_message_feedback(fake_openai, valid_message_feedback_payload())

    self.assertEqual(response.status_code, 202)
    self.assertEqual(len(fake_openai.completions.calls), 2)
    self.assertEqual(get_cached_message_feedback(100, 1001).feedbackType, FeedbackType.GOOD)
```

Add one test where candidate structural repair succeeds and one where review structural repair succeeds. Each must assert three calls. Add a final-invalid test that asserts no cache write after the second structural failure.

- [ ] **Step 2: Verify RED.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_uses_reviewed_full_candidate`

Expected: FAIL because the current workflow returns the server-assembled judgement/copy result and does not let the reviewer replace `feedbackType` and `scoreEvidence`.

- [ ] **Step 3: Implement parsing and bounded structural repair.**

```python
def _parse_message_feedback_candidate(
    data: dict[str, Any],
    expected_message_id: int,
) -> tuple[MessageFeedbackEvaluation, Any]:
    candidate_data = dict(data)
    detected_patterns = candidate_data.pop("detectedPatterns", None)
    try:
        evaluation = MessageFeedbackEvaluation.model_validate(candidate_data)
    except ValidationError as exc:
        raise AiResponseInvalidError("message_feedback_schema") from exc
    if evaluation.messageId != expected_message_id:
        raise AiResponseInvalidError("message_feedback_message_id")
    return evaluation, detected_patterns
```

Use one bounded helper for each stage. It retries only `AiResponseInvalidError`; it lets `AiGenerationFailedError` propagate unchanged. The repair prompt receives a structural reason, never raw user data in logs.

- [ ] **Step 4: Replace `generate_message_feedback`.**

```python
candidate, detected_patterns = _generate_message_feedback_candidate(request, settings)
reviewed, detected_patterns = _review_message_feedback_candidate(
    request,
    candidate,
    detected_patterns,
    settings,
)
feedback = MessageFeedbackData.model_validate(
    reviewed.model_dump(exclude={"scoreEvidence"}),
)
feedback = _postprocess_message_feedback_benchmark(
    feedback,
    detected_patterns,
    request.userMessage,
)
_store_message_feedback(
    request.sessionId,
    feedback,
    score_evidence=reviewed.scoreEvidence,
    user_message=request.userMessage,
)
```

Remove judgement/copy cache fields, prompt calls, parsing, validation and semantic repair paths.

- [ ] **Step 5: Verify GREEN.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS with two normal calls, at most one structural repair per stage, no unreviewed-candidate fallback and no cache write for final failure.

### Task 3: 전체 생성·검수 프롬프트와 deterministic 후처리 정리

**Files:**

- Modify: `app/conversation/application/next_message_service.py:1000-2200`.
- Modify: `tests/test_conversation_api.py:2250-2520`.

**Interfaces:**

- Add `_message_feedback_system_prompt(evaluation_context_type)` and `_message_feedback_user_prompt(request)` for the first candidate.
- Add `_message_feedback_review_system_prompt(evaluation_context_type)` and `_message_feedback_review_user_prompt(request, candidate, detected_patterns)` for final review.
- Retain `_postprocess_message_feedback_benchmark(feedback, detected_patterns, user_message)` and `_native_score_from_message_feedback_entries(entries)`.

- [ ] **Step 1: Write the failing test.**

```python
def test_review_prompt_requests_complete_final_json_and_preserves_user_facts(self):
    prompt = next_message_service._message_feedback_review_system_prompt(
        EvaluationContextType.AI_MESSAGE,
    )

    self.assertIn("Return the complete final JSON object", prompt)
    self.assertIn("may correct feedbackType and scoreEvidence", prompt)
    self.assertIn("Do not invent names, places, hobbies, feelings, habits, experiences, or reasons", prompt)
    self.assertIn("Do not make capitalization, punctuation, or a meaning-neutral filler the only improvement", prompt)

def test_review_prompt_does_not_require_keyword_overlap_or_core_asks(self):
    prompt = next_message_service._message_feedback_review_system_prompt(
        EvaluationContextType.AI_MESSAGE,
    )

    self.assertNotIn("coreAsks", prompt)
    self.assertNotIn("meaningful evidence words", prompt)
```

Keep the catalog test that verifies only catalog-supplied patterns are offered. Keep the test that `detectedPatterns` and `scoreEvidence` are absent from the public response.

- [ ] **Step 2: Verify RED.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_review_prompt_requests_complete_final_json_and_preserves_user_facts`

Expected: FAIL because the current copy prompt calls the judgement authoritative and requires `coreAsks` evidence.

- [ ] **Step 3: Implement the two complete JSON prompts.**

The first prompt defines a short scoring rubric and full JSON schema. The second includes the original request, the first candidate and catalog pattern definitions. It tells the model to keep valid fields, rewrite invalid fields, return only JSON, preserve user facts, use specific `[your ...]` placeholders for missing personal information and avoid internal-policy wording. Do not add scenario-specific templates or English keyword instructions.

- [ ] **Step 4: Delete runtime semantic rules.**

```text
_GENERIC_EVALUATION_WORDS
_CORRECTION_SCAFFOLD_WORDS
_EVIDENCE_FUNCTION_WORDS
_parse_message_feedback_judgement
_parse_and_assemble_message_feedback_copy
_validate_message_feedback_copy
_with_safe_correction_template
_safe_correction_expression
_meaningful_evidence_words
_with_inferred_required_placeholders
_required_placeholder_for_ask
```

Do not delete benchmark evidence matching, placeholder syntax validation in Pydantic, score calculation or external response validation.

- [ ] **Step 5: Verify GREEN.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS with no `coreAsks`, lexical-overlap or scenario-template runtime behavior left in the message-feedback path.

- [ ] **Step 6: Commit.**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "refactor: 메시지 피드백을 전체 생성·검수 흐름으로 전환"
```

### Task 4: 회귀 검증과 작업 기록 갱신

**Files:**

- Modify: `tests/test_quality_evaluation.py` only if the quality runner depends on removed internal fields.
- Modify: `checklist.md`.
- Modify: `context-notes.md`.

**Interfaces:**

- The quality runner consumes only external request data and final feedback fields.
- The test suite retains public API and OpenAPI behavior without exposing `scoreEvidence` or `detectedPatterns`.

- [ ] **Step 1: Verify remaining split-model regressions.**

Run: `.venv/bin/python -m unittest discover -s tests`

Expected: any remaining failure identifies a removed split-model reference or an externally observable regression. Do not weaken assertions merely to make the suite pass.

- [ ] **Step 2: Implement minimal test and evaluator cleanup.**

Replace internal judgement/copy assertions with complete candidate, review, public-field and cache-score assertions. Keep the fixed 21-case and full 115-case runners independent from live test execution.

- [ ] **Step 3: Update work records.**

Append the actual architecture decision and measured verification results to `context-notes.md`. Add completed LAN-167 items to `checklist.md` only after their evidence exists.

- [ ] **Step 4: Run full verification.**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall app tests scripts
.venv/bin/python -m pip check
git diff --check
```

Expected: every command exits 0.

Run the fixed 21-case, important 42-case and full 115-case evaluator with the configured model. Accept the change only when fixed cases pass, important cases have zero critical factual additions and the full set has at most one final structural failure.

- [ ] **Step 5: Commit.**

```bash
git add tests/test_quality_evaluation.py checklist.md context-notes.md
git commit -m "test: LAN-167 전체 생성·검수 회귀 기준 정리"
```
