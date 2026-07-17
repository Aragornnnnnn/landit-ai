# LAN-175 Evidence-Based Two-Pass Feedback Adjudication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep message feedback at two normal LLM calls while requiring source-grounded coverage and issue evidence for every score below 2.

**Architecture:** Both calls return a complete fallback-capable candidate plus internal adjudication evidence. The server validates exact source excerpts and score-to-evidence consistency without deciding English semantics; the second call independently rebuilds evidence with a shorter reviewer prompt and becomes authoritative when valid.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK through OpenRouter, standard-library `unittest`, JSON fixtures.

## Global Constraints

- The normal message-feedback path makes exactly two LLM calls.
- Do not add an unconditional or conditional third call in this change.
- Do not add question-specific regexes, Korean phrase-list scoring, or runtime English grammar rules.
- Keep public API models, OpenAPI, backend DTOs, database schema, score formula, model, and token limits unchanged.
- Evidence fields are internal-only and must not appear in public response models or OpenAPI.
- Preserve supplied AI and USER `message_content` values byte-for-byte in the quality fixture.

---

### Task 1: Model and validate source-grounded adjudication evidence

**Files:**
- Modify: `app/models/conversation.py`
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Produces: `MessageFeedbackCoverageStatus`, `MessageFeedbackIssueDimension`, `MessageFeedbackCoverageEvidence`, `MessageFeedbackActionableIssue`, and `MessageFeedbackAdjudicationEvidence`.
- Extends: `MessageFeedbackCandidate` with `coverageEvidence`, `ignoredSpeechArtifacts`, and `actionableIssues`.
- Produces: `_message_feedback_adjudication_evidence(candidate) -> MessageFeedbackAdjudicationEvidence`.
- Produces: `_validate_message_feedback_adjudication(candidate, request) -> None`.

- [ ] **Step 1: Write RED model and validation tests**

Add focused tests that construct candidate dictionaries and call `_parse_message_feedback_candidate`.

```python
def test_message_feedback_rejects_score_without_matching_evidence(self):
    candidate = good_message_feedback_candidate(1001)
    candidate["scoreEvidence"]["languageAccuracy"] = 1
    candidate["coverageEvidence"] = [{
        "requestExcerpt": "What are you into?",
        "answerExcerpt": "I'm into reading books",
        "status": "ANSWERED",
    }]
    candidate["ignoredSpeechArtifacts"] = []
    candidate["actionableIssues"] = []

    with self.assertRaisesRegex(
        AiResponseInvalidError,
        "message_feedback_language_accuracy_evidence",
    ):
        next_message_service._parse_message_feedback_candidate(
            candidate,
            message_feedback_request_for(
                ai_message="What are you into?",
                user_message="I'm into reading books",
            ),
        )
```

Add separate cases for a non-source `requestExcerpt`, a non-source `answerExcerpt`, `contextFit=2` with `MISSING`, `contextFit=1` without `MISSING`, duplicate issue dimensions, and an ignored artifact reused as an issue source.

- [ ] **Step 2: Run tests and verify RED**

Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_rejects_score_without_matching_evidence`

Expected: FAIL because evidence fields and validation do not exist.

- [ ] **Step 3: Add the internal Pydantic evidence models**

Add the following shapes near `MessageFeedbackScoreEvidence`.

```python
class MessageFeedbackCoverageStatus(StrEnum):
    ANSWERED = "ANSWERED"
    MISSING = "MISSING"


class MessageFeedbackIssueDimension(StrEnum):
    CLARITY = "CLARITY"
    LANGUAGE_ACCURACY = "LANGUAGE_ACCURACY"


class MessageFeedbackCoverageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requestExcerpt: str
    answerExcerpt: str | None
    status: MessageFeedbackCoverageStatus

    @field_validator("requestExcerpt", "answerExcerpt")
    @classmethod
    def excerpts_must_not_be_blank(cls, value: str | None) -> str | None:
        return _optional_not_blank(value)

    @model_validator(mode="after")
    def answer_must_match_status(self) -> Self:
        if self.status == MessageFeedbackCoverageStatus.ANSWERED:
            if self.answerExcerpt is None:
                raise ValueError("ANSWERED coverage requires answerExcerpt")
        elif self.answerExcerpt is not None:
            raise ValueError("MISSING coverage requires null answerExcerpt")
        return self


class MessageFeedbackActionableIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: MessageFeedbackIssueDimension
    sourceExcerpt: str
    correctionExcerpt: str
    rule: str

    @field_validator("sourceExcerpt", "correctionExcerpt", "rule")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        return _validate_not_blank(value)


class MessageFeedbackAdjudicationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverageEvidence: list[MessageFeedbackCoverageEvidence] = Field(min_length=1)
    ignoredSpeechArtifacts: list[str]
    actionableIssues: list[MessageFeedbackActionableIssue]

    @field_validator("ignoredSpeechArtifacts")
    @classmethod
    def artifacts_must_not_be_blank(cls, values: list[str]) -> list[str]:
        return [_validate_not_blank(value) for value in values]

    @model_validator(mode="after")
    def issue_dimensions_must_be_unique(self) -> Self:
        dimensions = [issue.dimension for issue in self.actionableIssues]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("actionable issue dimensions must be unique")
        return self
```

Add the same three fields to `MessageFeedbackCandidate` and construct `MessageFeedbackAdjudicationEvidence` from them after validation.

- [ ] **Step 4: Implement deterministic request-level evidence validation**

After Pydantic validation in `_parse_message_feedback_candidate`, call a new helper before assembling public feedback.

```python
def _validate_message_feedback_adjudication(
    candidate: MessageFeedbackCandidate,
    request: MessageFeedbackRequest,
) -> None:
    evidence = _message_feedback_adjudication_evidence(candidate)
    for coverage in evidence.coverageEvidence:
        if coverage.requestExcerpt not in request.evaluationContext.content:
            raise AiResponseInvalidError("message_feedback_request_evidence")
        if (
            coverage.answerExcerpt is not None
            and coverage.answerExcerpt not in request.userMessage
        ):
            raise AiResponseInvalidError("message_feedback_answer_evidence")

    for artifact in evidence.ignoredSpeechArtifacts:
        if artifact not in request.userMessage:
            raise AiResponseInvalidError("message_feedback_speech_artifact_evidence")
    for issue in evidence.actionableIssues:
        if issue.sourceExcerpt not in request.userMessage:
            raise AiResponseInvalidError("message_feedback_actionable_issue_evidence")
        if issue.sourceExcerpt in evidence.ignoredSpeechArtifacts:
            raise AiResponseInvalidError("message_feedback_ignored_issue_overlap")

    missing_coverage = any(
        item.status == MessageFeedbackCoverageStatus.MISSING
        for item in evidence.coverageEvidence
    )
    if (candidate.scoreEvidence.contextFit == 2) == missing_coverage:
        raise AiResponseInvalidError("message_feedback_context_evidence")

    issue_dimensions = {issue.dimension for issue in evidence.actionableIssues}
    score_dimensions = (
        (
            candidate.scoreEvidence.clarity,
            MessageFeedbackIssueDimension.CLARITY,
            "message_feedback_clarity_evidence",
        ),
        (
            candidate.scoreEvidence.languageAccuracy,
            MessageFeedbackIssueDimension.LANGUAGE_ACCURACY,
            "message_feedback_language_accuracy_evidence",
        ),
    )
    for score, dimension, reason in score_dimensions:
        if (score == 2) == (dimension in issue_dimensions):
            raise AiResponseInvalidError(reason)
```

Raise stable `AiResponseInvalidError` reasons for each failed contract. Compare exact strings without case folding or semantic regexes.

- [ ] **Step 5: Run Task 1 tests GREEN**

Run all newly added evidence tests and expect PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add app/models/conversation.py app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "feat: 메시지 피드백 판정 근거 계약 추가"
```

---

### Task 2: Carry final evidence through both calls and cache

**Files:**
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Changes: `_parse_message_feedback_candidate(...) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence, MessageFeedbackAdjudicationEvidence, Any]`.
- Changes: `_generate_message_feedback_candidate(...) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence, MessageFeedbackAdjudicationEvidence, Any, bool]`.
- Changes: `_review_message_feedback_candidate(...) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence, MessageFeedbackAdjudicationEvidence, Any, bool]`.
- Extends: `_MessageFeedbackCacheEntry.adjudication_evidence` and `_store_message_feedback(..., adjudication_evidence=...)`.

- [ ] **Step 1: Write RED authoritative and fallback evidence tests**

Add one test where first and second candidates have different evidence and assert the cache stores the second evidence. Add one review-failure test and assert it stores the first evidence.

```python
self.assertEqual(
    entry.adjudication_evidence.coverageEvidence[0].status,
    MessageFeedbackCoverageStatus.ANSWERED,
)
self.assertEqual(
    entry.adjudication_evidence.actionableIssues,
    [],
)
```

- [ ] **Step 2: Run both tests and verify RED**

Expected: FAIL because cache entries do not store adjudication evidence.

- [ ] **Step 3: Thread evidence through parsing, generation, review, and storage**

Build `MessageFeedbackAdjudicationEvidence` from each validated candidate. Select `final_adjudication_evidence` together with `final_score_evidence`. If review fails, keep the first evidence and candidate. Store only the selected final evidence.

- [ ] **Step 4: Remove the preference-specific runtime score override**

Delete `_normalize_preference_only_candidate`, `_is_like_infinitive_gerund_alternative`, and `_gerund_forms`. Remove the parser call that rewrites `languageAccuracy` for only `like to watch` and `like watching`; the general evidence contract replaces this special case.

Add an `rg` assertion test or source scan ensuring those names no longer exist.

- [ ] **Step 5: Run Task 2 tests GREEN**

Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: all message-feedback tests PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "refactor: 최종 피드백과 판정 근거를 함께 선택하도록 변경"
```

---

### Task 3: Replace the long reviewer with a compact evidence-first adjudicator

**Files:**
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Produces: `_message_feedback_evidence_policy() -> str` shared by candidate and reviewer prompts.
- Changes: `_message_feedback_review_user_prompt(..., adjudication_evidence, ...)` to include first evidence explicitly.
- Preserves: current two-call and one-step-per-stage repair behavior.

- [ ] **Step 1: Write RED prompt-contract tests**

Assert both prompts require exact excerpts and score-to-evidence consistency. Assert the reviewer says to rebuild evidence independently and does not contain the long scenario-specific cleaning, daily-rhythm, or roommate examples.

```python
for prompt in (candidate_prompt, review_prompt):
    self.assertIn("coverageEvidence", prompt)
    self.assertIn("ignoredSpeechArtifacts", prompt)
    self.assertIn("actionableIssues", prompt)
    self.assertIn("exact substring", prompt)

self.assertIn("rebuild the evidence independently", review_prompt)
self.assertNotIn("cleaning-preference question", review_prompt)
self.assertNotIn("daily-rhythm question", review_prompt)
self.assertNotIn("roommate question about a bad experience", review_prompt)
```

- [ ] **Step 2: Run prompt tests and verify RED**

Expected: FAIL because the current output schema omits adjudication evidence and the reviewer repeats the long rubric.

- [ ] **Step 3: Add one shared evidence policy and output schema**

The policy must state these general rules.

```text
Every coverageEvidence.requestExcerpt is an exact evaluation-context substring.
ANSWERED requires an exact user answerExcerpt; MISSING requires null.
Every ignoredSpeechArtifacts and actionableIssues.sourceExcerpt is an exact user substring.
An ignored speech artifact cannot be an actionable issue.
contextFit below 2 requires MISSING coverage.
clarity or languageAccuracy below 2 requires a matching actionable issue.
A grammatical, understandable expression is not actionable merely because another form is more common or concise.
```

Include the evidence fields in both JSON schemas. Keep them internal and continue omitting `feedbackType` and `messageId` from model output.

- [ ] **Step 4: Make the reviewer concise and independent**

Keep only the shared evidence policy, score definitions, learner-field contract, output schema, safety policy, original request, and first candidate/evidence. Tell the reviewer to reconstruct evidence before comparing it with the first candidate. Do not preserve candidate fields by default.

- [ ] **Step 5: Run Task 3 tests GREEN**

Run all prompt and message-feedback API tests and expect PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 2차 피드백을 증거 우선 판정기로 단순화"
```

---

### Task 4: Report adjudication evidence in the private quality evaluator

**Files:**
- Modify: `scripts/evaluate_conversation_quality.py`
- Modify: `tests/fixtures/lan_175_feedback_session_case.json`
- Test: `tests/test_quality_evaluation.py`

**Interfaces:**
- Extends each private `messageResults` item with `adjudicationEvidence`.
- Extends expected fixture boundaries with `expectedMissingCoverageCount`, `expectedActionableIssueDimensions`, `forbiddenActionableSourceTerms`, and `requiredAnyActionableRuleTerms`.
- Keeps public API and OpenAPI unchanged.

- [ ] **Step 1: Write RED evaluator tests**

Build cache entries with adjudication evidence and assert the evaluator detects these failures.

```python
self.assertFalse(result["missingCoverageCountMatchesExpectation"])
self.assertFalse(result["actionableIssueDimensionsMatchExpectation"])
self.assertEqual(result["foundForbiddenActionableSourceTerms"], ["I I"])
self.assertFalse(result["requiredAnyActionableRuleTermMatched"])
```

- [ ] **Step 2: Run evaluator tests and verify RED**

Expected: FAIL because evidence is not reported or evaluated.

- [ ] **Step 3: Add evidence expectations without changing supplied messages**

Set messages 60 and 62 to zero missing coverage and no actionable issues. For message 62, forbid `I I` as an actionable source. Set message 64 to zero missing coverage and one `LANGUAGE_ACCURACY` issue whose rule includes one of `subject-verb`, `agreement`, or `plural`.

- [ ] **Step 4: Implement evidence reporting and gates**

Serialize `entry.adjudication_evidence` into each result and combine all new evidence checks into `expectationMatched`. Do not serialize evidence in the FastAPI response.

- [ ] **Step 5: Run Task 4 tests GREEN**

Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest tests.test_quality_evaluation.QualityEvaluationTests`

Expected: all quality evaluator tests PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/evaluate_conversation_quality.py tests/fixtures/lan_175_feedback_session_case.json tests/test_quality_evaluation.py
git commit -m "test: 실제 세션 판정 근거 품질 게이트 추가"
```

---

### Task 5: Verify locally and run the final real-session gate

**Files:**
- Generate outside git: `/tmp/landit-ai-lan-175-results.json`

**Interfaces:**
- Consumes: completed two-pass implementation and exact supplied-session fixture.
- Produces: local verification evidence and one final three-run OpenRouter report.

- [ ] **Step 1: Run full local verification**

```bash
/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests
/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m compileall app tests scripts
/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m pip check
git diff --check
```

Expected: all tests PASS, compileall exits 0, pip reports no broken requirements, and diff check exits 0.

- [ ] **Step 2: Verify internal evidence is absent from public OpenAPI**

Serialize the FastAPI OpenAPI schema and assert it does not contain `coverageEvidence`, `ignoredSpeechArtifacts`, `actionableIssues`, `scoreEvidence`, `detectedPatterns`, or repair/fallback flags.

- [ ] **Step 3: Run the exact session three times through OpenRouter**

Because this Codex tenant blocks outbound transcript transfer, the user runs the existing evaluator locally.

```bash
/Users/sangmin8817/Soma/landit-ai/.venv/bin/python \
  scripts/evaluate_conversation_quality.py \
  --cases tests/fixtures/lan_175_feedback_session_case.json \
  --runs 3 \
  --kind feedback-session \
  --output /tmp/landit-ai-lan-175-results.json
```

- [ ] **Step 4: Evaluate the final quality gate**

Require all three runs to produce `GOOD`, `GOOD`, `NEEDS_IMPROVEMENT`; message scores 100, 100, and 70-85; session score 83-87; star rating 2.5; evidence expectations matched; no universal-praise contradiction; no validation errors or missing messages. Report message, session, and total P50 and maximum latency.

- [ ] **Step 5: Stop on failure instead of adding prompt rules**

If any run fails, do not add another prompt example or runtime exception. Report the evidence and treat conditional third-call or model-change design as the next decision.

- [ ] **Step 6: Final branch review**

Run: `git status --short --branch && git log --oneline origin/main..HEAD && git diff --stat origin/main...HEAD && git diff --check`

Expected: clean worktree, only LAN-175 files changed, reviewable semantic commits, and no whitespace errors.
