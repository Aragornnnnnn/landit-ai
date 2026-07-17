# LAN-175 Two-Pass Feedback Adjudication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the normal message-feedback path at two LLM calls while allowing the second call to correct the first call's score and copy, then replay the user's exact session through OpenRouter and report quality and latency.

**Architecture:** The first call remains a structurally valid fallback candidate. The second call returns the same internal candidate shape, including `scoreEvidence`, and becomes authoritative when valid; the server derives `feedbackType` from the selected evidence. Session feedback remains one call, but its prompt must reject absolute praise that contradicts any cached `NEEDS_IMPROVEMENT`. The quality evaluator gains a grouped session case that generates all message feedbacks in one cache, generates session feedback, and records outcomes and timings.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK through OpenRouter, standard-library `unittest`, JSON fixtures.

## Global Constraints

- The normal message-feedback path must make exactly two LLM calls.
- Do not add a third semantic judge or blind retry.
- Remove LAN-175 runtime semantic regexes and Korean phrase-list score overrides.
- Keep deterministic schema, placeholder, spoken-form, and benchmark-catalog validation.
- Keep the external API, OpenAPI, backend DTO, database schema, scoring formula, model, and token limits unchanged.
- Preserve the supplied AI and USER `message_content` values byte-for-byte in the live-quality fixture.
- Do not expose secrets, raw provider metadata, `scoreEvidence`, `detectedPatterns`, or internal repair/fallback flags through public APIs.

---

### Task 1: Rebase the approved design onto current main without the hardcoded prototype

**Files:**
- Preserve: `docs/superpowers/specs/2026-07-17-lan-175-two-pass-feedback-adjudication-design.md`
- Remove through history rewrite: prototype changes from commit `ee0a9c8`

**Interfaces:**
- Consumes: `origin/main` with LAN-174 response recovery and the LAN-175 design commit `b848f8c`.
- Produces: `hotfix/LAN-175` based on current `origin/main`, containing the design but no LAN-175 production implementation.

- [ ] **Step 1: Confirm the exact commit range**

Run: `git rev-list --left-right --count HEAD...origin/main && git log --oneline --decorate -6`

Expected: branch contains `ee0a9c8` followed by `b848f8c` and is behind `origin/main` by four commits.

- [ ] **Step 2: Move only commits after the prototype onto main**

Run: `git rebase --onto origin/main ee0a9c8 hotfix/LAN-175`

Expected: the design commit is replayed and the hardcoded prototype commit is absent from the new branch history.

- [ ] **Step 3: Verify the clean implementation baseline**

Run: `git status --short --branch && git log --oneline --decorate -6 && git diff origin/main...HEAD --stat`

Expected: only the approved design differs from `origin/main`; the worktree is clean.

---

### Task 2: Make the second call authoritative for score and copy

**Files:**
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `_generate_message_feedback_candidate(...) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence, Any, bool]`.
- Produces: `_review_message_feedback_candidate(...) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence, Any, bool]`.
- Produces: `_parse_message_feedback_candidate(...) -> tuple[MessageFeedbackData, MessageFeedbackScoreEvidence, Any]` for both first and second outputs.
- Preserves: `_MessageFeedbackCacheEntry.score_evidence` as the evidence used for the final stored feedback.

- [ ] **Step 1: Write a RED test proving review can upgrade NEEDS to GOOD**

Add a test that feeds a first candidate with `contextFit=1` and a second candidate with all scores equal to 2.

```python
def test_message_feedback_review_can_upgrade_candidate_score(self):
    candidate = message_feedback_candidate(
        needs_improvement_message_feedback(1001),
    )
    reviewed = message_feedback_candidate(good_message_feedback(1001))
    fake_openai = FakeOpenAI(
        contents=[json.dumps(candidate), json.dumps(reviewed)],
    )
    app = create_app(make_settings(
        openrouter_api_key="test-openrouter-key",
        openrouter_model="openrouter-test-model",
    ))

    with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
        response = make_client(app).post(
            "/api/v1/conversation/message-feedback",
            json=valid_message_feedback_payload(),
        )

    entry = next_message_service._get_expected_message_feedback_entries(
        100,
        [1001],
    )[0]
    self.assertEqual(response.status_code, 202)
    self.assertEqual(entry.feedback.feedbackType.value, "GOOD")
    self.assertEqual(entry.score_evidence.model_dump(), {
        "contextFit": 2,
        "clarity": 2,
        "languageAccuracy": 2,
    })
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_review_can_upgrade_candidate_score`

Expected: FAIL because the current review schema rejects `scoreEvidence` or keeps the first evidence locked.

- [ ] **Step 3: Write a RED test proving review can downgrade GOOD to NEEDS**

Use a first all-2 candidate and a reviewed candidate with `languageAccuracy=1`; assert final type `NEEDS_IMPROVEMENT` and final score evidence `2,2,1`.

- [ ] **Step 4: Run both focused tests and verify RED**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_review_can_upgrade_candidate_score tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_review_can_downgrade_candidate_score`

Expected: both tests fail for the locked-review behavior.

- [ ] **Step 5: Implement the minimal authoritative-review flow**

Change `generate_message_feedback` so the selected evidence follows the selected feedback.

```python
final_score_evidence = score_evidence
try:
    (
        feedback,
        final_score_evidence,
        detected_patterns,
        copy_was_repaired,
    ) = _review_message_feedback_candidate(
        request,
        candidate,
        score_evidence,
        detected_patterns,
        resolved_settings,
    )
except (AiGenerationFailedError, AiResponseInvalidError):
    feedback = candidate
    copy_was_fallback = True

_store_message_feedback(
    request.sessionId,
    feedback,
    score_evidence=final_score_evidence,
    user_message=request.userMessage,
    candidate_was_repaired=candidate_was_repaired,
    copy_was_repaired=copy_was_repaired,
    copy_was_fallback=copy_was_fallback,
)
```

Rename the review helper and parse its output through `_parse_message_feedback_candidate(reviewed_data, request)`. Return reviewed evidence and use the same parser for review repair output. Keep first-candidate fallback unchanged.

- [ ] **Step 6: Change the review prompt from locked copy to independent adjudication**

The review system prompt must require a complete `MessageFeedbackCandidate` JSON with `scoreEvidence` and must explicitly state the six adjudication steps from the design. Remove statements that score and type are locked. Keep the candidate and original request in the review user prompt, labeling the first evidence as candidate evidence rather than locked evidence.

- [ ] **Step 7: Run focused GREEN verification**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_review_can_upgrade_candidate_score tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_review_can_downgrade_candidate_score`

Expected: PASS.

- [ ] **Step 8: Add and verify fallback evidence regression**

Update the existing review provider-failure and repair-failure tests to assert that the stored evidence is the first candidate evidence. Run those focused tests and expect PASS.

- [ ] **Step 9: Add prompt contract regression tests**

Assert the review prompt contains `Re-evaluate scoreEvidence`, immediate spoken repetition guidance, remaining-error guidance, and correction-expression/reason consistency. Assert it does not contain `locked by the server` or `do not return or change them`.

- [ ] **Step 10: Run all message-feedback API tests**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS with no failed or errored tests.

- [ ] **Step 11: Commit the authoritative review change**

Run: `git add app/conversation/application/next_message_service.py tests/test_conversation_api.py && git commit -m "fix: 2차 검수가 피드백 점수와 문구를 재심사하도록 수정"`

Expected: one implementation commit containing only the review-flow and its tests.

---

### Task 3: Remove LAN-175 semantic hardcoding and enforce session-summary consistency in prompts

**Files:**
- Modify: `app/conversation/application/next_message_service.py`
- Test: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: final cached `MessageFeedbackData` values in `_session_feedback_user_prompt`.
- Produces: session prompt rule that disallows universal praise whenever `NEEDS_IMPROVEMENT count > 0`.
- Removes: `_normalize_self_introduction_candidate`, `_normalize_spoken_repetition_only_candidate`, `_answers_open_self_introduction`, `_feedback_mentions_only_spoken_repetition`, `_normalize_session_feedback_praise`, and `_ABSOLUTE_SESSION_PRAISE_TERMS` if present after rebase.

- [ ] **Step 1: Write a RED prompt test for mixed feedback**

```python
def test_session_feedback_prompt_rejects_absolute_praise_for_mixed_feedback(self):
    prompt = next_message_service._session_feedback_system_prompt()

    self.assertIn("NEEDS_IMPROVEMENT count is greater than 0", prompt)
    self.assertIn("do not claim that every answer was natural or perfect", prompt)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.SessionFeedbackApiTests.test_session_feedback_prompt_rejects_absolute_praise_for_mixed_feedback`

Expected: FAIL because current main only handles the `GOOD=0` boundary.

- [ ] **Step 3: Add the minimal session prompt rule**

Add one general instruction to `_session_feedback_system_prompt` stating that any nonzero `NEEDS_IMPROVEMENT` count forbids claims that all or every answer was natural, correct, or perfect. Require strengths to come from cached GOOD feedback or factual `positiveFeedback`.

- [ ] **Step 4: Verify GREEN and hardcoding absence**

Run the focused session prompt test, then run:

`rg -n "_normalize_self_introduction_candidate|_normalize_spoken_repetition_only_candidate|_answers_open_self_introduction|_feedback_mentions_only_spoken_repetition|_normalize_session_feedback_praise|_ABSOLUTE_SESSION_PRAISE_TERMS" app tests`

Expected: focused test PASS and `rg` returns no matches.

- [ ] **Step 5: Run session-feedback API tests**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.SessionFeedbackApiTests`

Expected: PASS.

- [ ] **Step 6: Commit the session-summary rule**

Run: `git add app/conversation/application/next_message_service.py tests/test_conversation_api.py && git commit -m "fix: 혼합 피드백과 세션 총평의 칭찬이 모순되지 않도록 수정"`

Expected: one prompt-policy commit and its regression test.

---

### Task 4: Replay the exact supplied session through the quality evaluator

**Files:**
- Modify: `scripts/evaluate_conversation_quality.py`
- Modify: `tests/test_quality_evaluation.py`
- Create: `tests/fixtures/lan_175_feedback_session_case.json`

**Interfaces:**
- Consumes: a case with `kind="feedback-session"`, `messageFeedbackPayloads`, `sessionFeedbackPayload`, expected message boundaries, expected native-score range, and expected star rating.
- Produces: one result per run containing `messageResults`, `nativeScore`, `starRating`, `highlightMessage`, `summaryMessage`, `messageFeedbacks`, `messageLatenciesMs`, `sessionFeedbackLatencyMs`, `totalLatencyMs`, and validation fields.
- Extends: CLI `--kind` choices with `feedback-session`.

- [ ] **Step 1: Write a RED fixture-integrity test**

Load `lan_175_feedback_session_case.json` and assert the six `evaluationContext.content` and `userMessage` values exactly equal the six supplied `message_content` strings, including punctuation and repeated tokens. Assert message IDs `[60, 62, 64]` and expected boundaries `GOOD`, `GOOD`, `NEEDS_IMPROVEMENT`.

- [ ] **Step 2: Run the fixture test and verify RED**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation.QualityEvaluationTests.test_lan_175_session_fixture_preserves_supplied_messages`

Expected: FAIL because the exact-session fixture does not exist.

- [ ] **Step 3: Add the exact session fixture**

Create a one-case JSON array. Copy the three AI messages and three USER messages exactly from the supplied table. Use session ID 14, message IDs 60/62/64, turn numbers 1/2/3, sequences 2/4/6, and a consistent scenario payload. Set expected message scores to `[100,100]`, `[100,100]`, and `[70,85]`; set expected native score range `[83,87]` and expected star rating `2.5`.

- [ ] **Step 4: Verify the fixture test GREEN**

Run the focused fixture-integrity test and expect PASS.

- [ ] **Step 5: Write RED evaluator tests for grouped session replay**

Patch `generate_message_feedback`, `_get_expected_message_feedback_entries`, and `generate_session_feedback` with deterministic values. Assert message order, score checks, session score checks, and nonnegative latency fields. Add an error-path test that records `validationError` instead of aborting the batch.

- [ ] **Step 6: Run grouped evaluator tests and verify RED**

Run the two new `QualityEvaluationTests` methods and expect failure because `feedback-session` is unsupported.

- [ ] **Step 7: Implement grouped session evaluation**

Import `perf_counter`, `generate_session_feedback`, `SessionFeedbackRequest`, and the final cache entry helper. Add `feedback-session` to accepted kinds and dispatch it from `_evaluate_case`. Clear the cache before and after each run. Time each message call, read its final cache entry, generate session feedback once, and return all requested output fields. Convert generation, validation, or missing-cache failures into one structured result with the case ID, run, error type, error reason, and elapsed time.

- [ ] **Step 8: Run grouped evaluator tests GREEN**

Run the focused grouped evaluator tests and expect PASS.

- [ ] **Step 9: Run all quality-evaluator tests**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation`

Expected: PASS.

- [ ] **Step 10: Commit the exact-session evaluator**

Run: `git add scripts/evaluate_conversation_quality.py tests/test_quality_evaluation.py tests/fixtures/lan_175_feedback_session_case.json && git commit -m "test: 전달 세션 원문 기반 피드백 품질 평가 추가"`

Expected: one test-tool commit with the exact fixture and evaluator support.

---

### Task 5: Verify locally and run the real OpenRouter demonstration

**Files:**
- Generate outside git: `/tmp/landit-ai-lan-175-results.json`

**Interfaces:**
- Consumes: the completed code and `tests/fixtures/lan_175_feedback_session_case.json`.
- Produces: fresh local verification evidence and a three-run OpenRouter report tied to fixture SHA-256 and model name.

- [ ] **Step 1: Run focused and full local verification**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall app tests scripts
.venv/bin/python -m pip check
git diff --check
```

Expected: all unittest cases pass, compileall exits 0, pip reports no broken requirements, and diff check exits 0.

- [ ] **Step 2: Verify public OpenAPI does not expose internal fields**

Generate the FastAPI schema using the existing app factory and assert serialized components do not contain `scoreEvidence`, `detectedPatterns`, `candidateWasRepaired`, `copyWasRepaired`, or `copyWasFallback`.

Expected: assertion exits 0.

- [ ] **Step 3: Run the supplied session three times through OpenRouter**

Run:

```bash
.venv/bin/python scripts/evaluate_conversation_quality.py \
  --cases tests/fixtures/lan_175_feedback_session_case.json \
  --runs 3 \
  --kind feedback-session \
  --output /tmp/landit-ai-lan-175-results.json
```

Expected: three result objects are written without exposing credentials.

- [ ] **Step 4: Evaluate the report against the design gates**

Check all three runs for message types `GOOD`, `GOOD`, `NEEDS_IMPROVEMENT`; scores 100, 100, and 70-85; session score 83-87; star rating 2.5; no hobby omission for message 60; no repetition-only criticism for message 62; accurate explanation for message 64 if `is` changes to `are`; no universal-praise contradiction; zero final validation errors and missing messages. Summarize per-call and total P50 and maximum latency from the recorded fields.

- [ ] **Step 5: Quality-failure loop if a gate fails**

For each failed semantic gate, add one prompt-contract regression test, watch it fail, make the smallest general prompt change, run the focused unit test, then rerun only the failed live case three times. Do not add runtime regexes, phrase-list scoring, a third semantic call, model downgrade, or token reduction.

- [ ] **Step 6: Record exact evidence**

Report the commands, test count, model, fixture hash, per-run types/scores/session results, repair/fallback counts, and latency summary in the final response and PR body. Do not commit the `/tmp` report or any secret.

- [ ] **Step 7: Final branch review**

Run: `git status --short --branch && git log --oneline origin/main..HEAD && git diff --stat origin/main...HEAD && git diff --check`

Expected: clean worktree, reviewable commits, only LAN-175 files changed, and no whitespace errors.
