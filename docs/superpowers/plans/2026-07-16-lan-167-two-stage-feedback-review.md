# LAN-167 메시지 피드백 2단계 검수 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 메시지별 피드백을 생성 단계와 검수 단계로 나누고 검수 실패 시 유효한 생성 후보를 저장한다.

**Architecture:** 첫 호출의 JSON을 `MessageFeedbackEvaluation`으로 검증해 생성 후보와 내부 `detectedPatterns`를 보관한다. 두 번째 호출은 원본 요청과 후보를 검수해 완성된 JSON을 반환하며, 유효한 검수 후보만 최종값으로 사용한다. 검수 호출·파싱·DTO·메시지 ID 검증 실패는 생성 후보 fallback으로 처리하고, 최종 후보에만 기존 benchmark 후처리를 적용한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK, unittest.

## Global Constraints

- 외부 메시지 피드백 API, backend DTO, DB 스키마를 변경하지 않는다.
- `detectedPatterns`는 AI 서버 내부에서만 사용하고 API 응답·캐시에 저장하지 않는다.
- 생성 단계 실패는 기존처럼 요청 실패로 처리하고, 검수 단계 실패만 생성 후보로 fallback한다.
- 검수 단계는 최대 한 번만 호출한다. 추가 재시도를 하지 않는다.
- 대문자·문장부호·의미 중립 필러만의 차이는 NEEDS_IMPROVEMENT 사유가 아니다.
- 교정 표현은 사용자 발화의 의도, 시제, 부정, 알려진 사실을 보존하고, 누락된 개인 정보는 구체적인 대괄호 플레이스홀더를 사용한다.

---

### Task 1: 검수 결과가 생성 후보를 교체하는 회귀 테스트

**Files:**
- Modify: `tests/test_conversation_api.py:214-240`
- Modify: `tests/test_conversation_api.py:600-940`

**Interfaces:**
- Consumes: `POST /api/v1/conversation/message-feedback`, `FakeOpenAI`.
- Produces: 두 JSON 응답을 순서대로 반환하는 `FakeCompletions`와 검수 결과 저장을 보장하는 API 테스트.

- [ ] **Step 1: Write the failing test**

`FakeCompletions`가 `contents: list[str]`와 `errors: list[Exception | None]`를 받아 호출 순서대로 처리하도록 확장한다. 기존 단일 `content`, `error`, `kwargs` 사용 테스트를 유지하려면 첫 번째 호출 인자를 해당 속성에 그대로 남긴다.

```python
class FakeCompletions:
    def __init__(self, content=None, error=None, *, contents=None, errors=None):
        self.contents = list(contents) if contents is not None else [content]
        self.errors = list(errors) if errors is not None else [error]
        self.kwargs = None
        self.calls = []

    def create(self, **kwargs):
        self.kwargs = kwargs
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        error = self.errors[index] if index < len(self.errors) else None
        if error is not None:
            raise error
        content = self.contents[index]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )


class FakeOpenAI:
    def __init__(self, content=None, error=None, *, contents=None, errors=None):
        self.completions = FakeCompletions(
            content=content,
            error=error,
            contents=contents,
            errors=errors,
        )
        self.chat = SimpleNamespace(completions=self.completions)
```

테스트 모듈에 아래 두 helper도 추가한다.

```python
def good_message_feedback_response(message_id=1001):
    return {
        "messageId": message_id,
        "feedbackType": "GOOD",
        "scoreEvidence": {
            "contextFit": 2,
            "clarity": 2,
            "languageAccuracy": 2,
        },
        "baseLocaleAnalogy": '"조깅을 좋아해"라고 자연스럽게 답하는 것과 같아요.',
        "positiveFeedback": None,
        "feedbackDetail": "좋아하는 활동을 자연스럽게 말했어요.",
        "correctionExpression": None,
        "correctionReason": None,
        "benchmarkMessage": "좋아하는 활동을 자연스럽게 답했어요.",
    }


def partial_hobby_feedback_response(message_id=1001):
    return {
        "messageId": message_id,
        "feedbackType": "NEEDS_IMPROVEMENT",
        "scoreEvidence": {
            "contextFit": 1,
            "clarity": 2,
            "languageAccuracy": 2,
        },
        "baseLocaleAnalogy": '"조깅은 좋아하지만 왜 좋은지는 말 안 할게"라고 일부만 답하는 것과 같아요.',
        "positiveFeedback": "좋아하는 활동을 분명히 말했어요.",
        "feedbackDetail": None,
        "correctionExpression": "I like jogging because [your reason].",
        "correctionReason": "좋아하는 활동에는 답했지만 이유가 빠졌어요. [your reason]에 조깅을 좋아하는 이유를 넣어 보세요.",
        "benchmarkMessage": None,
    }
```

`multi_ask_feedback_payload`은 `valid_message_feedback_payload()`의 `evaluationContext`와 `userMessage`만 바꿔 만든다.

```python
def multi_ask_feedback_payload(user_message):
    payload = valid_message_feedback_payload()
    payload["evaluationContext"] = {
        "type": "AI_MESSAGE",
        "content": "What are you into? What do you love about it?",
        "translatedContent": "무엇을 좋아해? 그것의 어떤 점이 좋아?",
    }
    payload["userMessage"] = user_message
    return payload
```

아래처럼 첫 번째 GOOD 후보가 두 번째 NEEDS_IMPROVEMENT 후보로 교체되는 테스트를 추가한다.

```python
def test_message_feedback_stores_valid_reviewed_candidate(self):
    generated = good_message_feedback_response()
    reviewed = partial_hobby_feedback_response()
    fake_openai = FakeOpenAI(contents=[json.dumps(generated), json.dumps(reviewed)])
    app = create_app(make_settings(
        openrouter_api_key="test-openrouter-key",
        openrouter_model="openrouter-test-model",
    ))

    with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
        response = make_client(app).post(
            "/api/v1/conversation/message-feedback",
            json=multi_ask_feedback_payload("I like jogging."),
        )

    self.assertEqual(response.status_code, 202)
    cached = get_cached_message_feedback(100, 1001)
    self.assertEqual(cached.feedbackType, "NEEDS_IMPROVEMENT")
    self.assertEqual(cached.correctionExpression, "I like jogging because [your reason].")
    self.assertIn("Review Task", fake_openai.completions.calls[1]["messages"][0]["content"])
    self.assertIn("Generated candidate", fake_openai.completions.calls[1]["messages"][1]["content"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_stores_valid_reviewed_candidate`

Expected: FAIL because the current implementation makes one model call and stores the generated GOOD candidate.

- [ ] **Step 3: Do not change production code yet**

Keep the failure as the RED baseline. The test must fail due to the one-call implementation, not due to malformed test JSON or missing helper data.

- [ ] **Step 4: Commit after Task 2 becomes green**

Do not commit this test alone. It is part of the same public message-feedback behavior as Task 2.

### Task 2: 검수 단계 실패 fallback 회귀 테스트

**Files:**
- Modify: `tests/test_conversation_api.py:214-240`
- Modify: `tests/test_conversation_api.py:600-940`

**Interfaces:**
- Consumes: 생성 단계의 유효한 `MessageFeedbackEvaluation` JSON, 검수 단계의 `AiGenerationFailedError` 또는 메시지 ID 불일치 JSON.
- Produces: 검수 실패에도 생성 후보를 저장하는 API 테스트.

- [ ] **Step 1: Write the failing tests**

검수 호출이 실패해도 첫 번째 후보를 저장하는 테스트와, 검수 후보의 `messageId`가 다른 경우 첫 번째 후보로 fallback하는 테스트를 추가한다.

```python
def test_message_feedback_falls_back_when_review_call_fails(self):
    generated = good_message_feedback_response()
    fake_openai = FakeOpenAI(
        contents=[json.dumps(generated)],
        errors=[None, RuntimeError("review unavailable")],
    )

    with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
        response = make_client(app).post(
            "/api/v1/conversation/message-feedback",
            json=valid_message_feedback_payload(),
        )

    self.assertEqual(response.status_code, 202)
    cached = get_cached_message_feedback(100, 1001)
    self.assertEqual(cached.feedbackType, "GOOD")

def test_message_feedback_falls_back_when_review_message_id_differs(self):
    generated = good_message_feedback_response()
    invalid_review = good_message_feedback_response(message_id=9999)
    fake_openai = FakeOpenAI(contents=[json.dumps(generated), json.dumps(invalid_review)])

    with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
        response = make_client(app).post(
            "/api/v1/conversation/message-feedback",
            json=valid_message_feedback_payload(),
        )

    self.assertEqual(response.status_code, 202)
    self.assertEqual(get_cached_message_feedback(100, 1001).feedbackType, "GOOD")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_falls_back_when_review_call_fails tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_falls_back_when_review_message_id_differs`

Expected: FAIL because the current implementation does not make a second call and cannot distinguish a review failure from a generation failure.

- [ ] **Step 3: Do not change production code yet**

Confirm the expected failure before starting Task 3.

### Task 3: 생성·검수 후보 파싱과 fallback 구현

**Files:**
- Modify: `app/conversation/application/next_message_service.py:1-240`
- Modify: `app/conversation/application/next_message_service.py:1030-1245`
- Test: `tests/test_conversation_api.py:214-240,600-940`

**Interfaces:**
- Consumes: `MessageFeedbackRequest`, raw completion JSON, `MessageFeedbackEvaluation`.
- Produces: `_parse_message_feedback_candidate(data, expected_message_id) -> tuple[MessageFeedbackEvaluation, Any]`, `_review_message_feedback_candidate(request, evaluation) -> tuple[MessageFeedbackEvaluation, Any]`, and `_message_feedback_review_system_prompt(evaluation_context_type) -> str`.

- [ ] **Step 1: Add the shared candidate parser**

Add a helper that removes `detectedPatterns`, validates `MessageFeedbackEvaluation`, and verifies the candidate message ID before returning the evaluation and raw detected patterns.

```python
def _parse_message_feedback_candidate(
    data: dict[str, Any],
    expected_message_id: int,
) -> tuple[MessageFeedbackEvaluation, Any]:
    detected_patterns = data.pop("detectedPatterns", None)
    try:
        evaluation = MessageFeedbackEvaluation.model_validate(data)
    except ValidationError as exc:
        raise AiResponseInvalidError from exc
    if evaluation.messageId != expected_message_id:
        raise AiResponseInvalidError
    return evaluation, detected_patterns
```

- [ ] **Step 2: Add the review prompt and request**

Reuse the existing message-feedback policy as the baseline and append a review instruction that receives the original request and full candidate JSON. The prompt must require a complete final JSON, not an approval flag.

```python
def _message_feedback_review_system_prompt(
    evaluation_context_type: EvaluationContextType,
) -> str:
    return "\n\n".join([
        _message_feedback_system_prompt(evaluation_context_type),
        (
            "Review Task:\n"
            "Review the generated candidate against the original evaluation context and user utterance. "
            "Return a complete final JSON object. Correct a candidate that misses any explicit core ask, "
            "answers a different question, invents a personal fact or reason, changes known facts or intent, "
            "or treats capitalization, punctuation, a neutral filler, or a natural grammatical alternative as an actionable issue."
        ),
    ])

def _message_feedback_review_user_prompt(
    request: MessageFeedbackRequest,
    evaluation: MessageFeedbackEvaluation,
    detected_patterns: Any,
) -> str:
    candidate = evaluation.model_dump(mode="json")
    candidate["detectedPatterns"] = detected_patterns
    return (
        f"{_message_feedback_user_prompt(request)}\n\n"
        "Generated candidate:\n"
        f"{json.dumps(candidate, ensure_ascii=False, separators=(\",\", \":\"))}"
    )
```

- [ ] **Step 3: Add the review call and fallback boundary**

Keep generation failures outside the fallback boundary. Wrap only the second call, raw response parsing, and reviewer candidate validation. On any `AiGenerationFailedError` or `AiResponseInvalidError`, keep the generation candidate and emit a non-sensitive warning.

```python
generated_data = _request_json_completion(...)
evaluation, detected_patterns = _parse_message_feedback_candidate(
    generated_data,
    request.messageId,
)
try:
    reviewed_data = _request_json_completion(
        settings,
        system_prompt=_message_feedback_review_system_prompt(request.evaluationContext.type),
        user_prompt=_message_feedback_review_user_prompt(
            request,
            evaluation,
            detected_patterns,
        ),
        max_tokens=768,
    )
    evaluation, detected_patterns = _parse_message_feedback_candidate(
        reviewed_data,
        request.messageId,
    )
except (AiGenerationFailedError, AiResponseInvalidError):
    logger.warning(
        "AI 메시지별 피드백 검수에 실패해 생성 후보를 사용합니다. workflow=message_feedback_review sessionId=%s messageId=%s",
        request.sessionId,
        request.messageId,
    )
```

Convert the selected evaluation to `MessageFeedbackData`, run the existing benchmark postprocess once, and store the selected score evidence.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_stores_valid_reviewed_candidate tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_falls_back_when_review_call_fails tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_falls_back_when_review_message_id_differs`

Expected: PASS. The valid reviewer replaces the candidate; review transport and ID failures retain it.

- [ ] **Step 5: Run adjacent message-feedback tests**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS. Existing GOOD/NEEDS contract, benchmark catalog behavior, and prompt tests remain valid after the extra call.

- [ ] **Step 6: Commit**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 메시지 피드백 2단계 검수와 fallback 추가"
```

### Task 4: 실제 품질 경계 fixture와 문서 기록

**Files:**
- Modify: `tests/fixtures/lan_167_feedback_quality_cases.json`
- Modify: `tests/test_quality_evaluation.py:120-160`
- Modify: `context-notes.md`
- Modify: `checklist.md`

**Interfaces:**
- Consumes: `scripts/evaluate_conversation_quality.py`의 message-feedback fixture 형식.
- Produces: 복합 질문, 무관한 답변, 근거 없는 이유, 표기만 다른 답변을 포함하는 LAN-167 회귀 사례.

- [ ] **Step 1: Add the failing fixture assertions**

기존 fixture 집합 검증 테스트에 다음 case ID를 추가한다.

```python
self.assertEqual(
    set(cases_by_id),
    {
        "lan167-capitalization-and-period-only",
        "lan167-meaning-neutral-filler",
        "lan167-valid-like-to-watch",
        "lan167-partial-self-introduction",
        "lan167-off-topic-answer",
        "lan167-partial-hobby-reason",
        "lan167-preserve-unknown-reason",
    },
)
```

`lan167-partial-hobby-reason`은 `What are you into? What do you love about it?`와 `I like jogging.`을 사용해 NEEDS_IMPROVEMENT, 80점, `[your reason]`을 요구한다. `lan167-preserve-unknown-reason`은 `I like reading a book. This is so cool.`을 사용해 NEEDS_IMPROVEMENT, `[your reason]`을 요구하고 `relax`를 금지한다.

- [ ] **Step 2: Run fixture test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation.QualityEvaluationTests.test_lan_167_fixture_covers_feedback_quality_boundaries`

Expected: FAIL because the two cases are absent.

- [ ] **Step 3: Add the fixture cases and make the test pass**

Add exact payloads that mirror the user-data findings. Use `requiredCorrectionPlaceholders` and `forbiddenFeedbackTerms` to make fact-preservation requirements observable in the evaluator output.

- [ ] **Step 4: Run quality-evaluation tests**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation`

Expected: PASS.

- [ ] **Step 5: Record verification scope**

Append the implementation decision, fallback behavior, and actual repeat-evaluation result to `context-notes.md`. Mark the corresponding `checklist.md` items complete only after the commands and real model evaluation finish.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/lan_167_feedback_quality_cases.json tests/test_quality_evaluation.py context-notes.md checklist.md
git commit -m "test: 메시지 피드백 검수 품질 경계 보강"
```

### Task 5: 전체 회귀와 실제 모델 재평가

**Files:**
- Verify: `app/conversation/application/next_message_service.py`
- Verify: `tests/test_conversation_api.py`
- Verify: `tests/test_quality_evaluation.py`
- Verify: `tests/fixtures/lan_167_feedback_quality_cases.json`

**Interfaces:**
- Consumes: 현재 `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, 승인된 사용자 데이터.
- Produces: 전체 unittest 통과 기록과 중요 사례 14개의 3회 재평가 결과.

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m unittest discover -s tests`

Expected: PASS with no test failures.

- [ ] **Step 2: Run static checks**

Run: `.venv/bin/python -m compileall -q app tests scripts`

Expected: PASS with no output.

- [ ] **Step 3: Re-evaluate critical real cases**

Run each command with approved user data and a fresh output file.

```bash
.venv/bin/python /tmp/evaluate_landit_lan167_csv.py \
  --input '/Users/sangmin8817/Downloads/Supabase Snippet Untitled query-3.csv' \
  --output /tmp/landit-ai-lan167-two-stage-run1.jsonl \
  --workers 1 \
  --message-ids 31,52,56,146,208,257,283,292,296,317,324,329,330,335
```

Repeat with output paths ending in `run2.jsonl` and `run3.jsonl`. Compare each output with the pre-change three-run findings. The target is fewer than nine cases with the same material issue in all three runs.

- [ ] **Step 4: Review the final diff and commit records**

Run: `git diff --check`

Expected: PASS.

Confirm `git status --short` contains only intentional changes and that Tasks 3 and 4 have separate logical commits.
