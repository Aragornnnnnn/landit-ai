# LAN-167 피드백 판정·문구 분리와 세션 점수 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 메시지 피드백의 의미 판정을 사용자용 문구 생성과 분리하고, 세 발화 이상 세션의 점수에 GOOD 비율을 반영해 피드백 유형·점수·별점이 일관되게 보이도록 한다.

**Architecture:** 첫 번째 LLM 호출은 `evaluationContext`의 핵심 요청과 사용자 발화 근거, 세 평가 항목만 반환한다. 서버가 근거와 점수의 불변식을 검증한 뒤 `feedbackType`을 확정한다. 판정 형식 검증이 실패한 경우에만 판정 복구를 한 번 수행하고, 두 번째 정상 단계는 확정된 판정을 입력받아 사용자용 문구만 생성한다. 문구 검증 실패도 한 번만 복구하며 검증되지 않은 결과로 fallback하지 않는다. 메시지 점수는 유지하되 3개 이상 세션은 원시 평균 70%와 GOOD 비율 30%를 정수 반올림해 `nativeScore`를 만들고 별점은 최종 점수에서만 계산한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI Python SDK, unittest.

## 작업 원칙

- 현재 작업 브랜치 `fix/LAN-167`에서 진행한다.
- 외부 API, backend DTO, DB 스키마를 변경하지 않는다.
- `openai/gpt-5.4-mini`를 판정과 문구 생성에 우선 사용한다. 모델 분리는 전체 품질 재평가 결과가 나온 뒤 별도 결정한다.
- 판정 프롬프트는 `evaluationContext`만 핵심 요청으로 분해한다. 시나리오 목표를 추가 질문으로 취급하지 않는다.
- 기존 전체 피드백 생성·검수 프롬프트와 첫 후보 fallback은 제거한다.
- `detectedPatterns`와 benchmark catalog 후처리는 문구 생성 뒤 내부 단계로 유지한다.
- 현재 작업 트리의 미커밋 소스·테스트 변경은 폐기하지 않는다. 아래 테스트와 새 구조에 필요한 줄만 교체하고 문서 커밋과 섞지 않는다.

---

### Task 1: 판정 전용 내부 모델과 불변식 검증 추가

**Files**

- Modify: `app/models/conversation.py:287-380`.
- Modify: `tests/test_conversation_api.py:606-1020`.

**Interfaces**

- Add internal `MessageFeedbackCoreAsk`.
- Add internal `MessageFeedbackJudgement`.
- Keep public `MessageFeedbackData`, `MessageFeedbackResponse`, `SessionFeedbackResponse` unchanged.

- [ ] **Step 1: 판정 DTO의 RED 테스트를 작성한다.**

`tests/test_conversation_api.py`에 판정 JSON helper를 추가한다.

```python
def message_feedback_judgement(
    message_id=1001,
    *,
    context_fit=2,
    clarity=2,
    language_accuracy=2,
    core_asks=None,
    stated_facts=None,
):
    return {
        "messageId": message_id,
        "coreAsks": core_asks or [
            {
                "ask": "say what activity you like",
                "addressed": True,
                "evidence": "jogging",
                "requiredPlaceholder": None,
            },
        ],
        "statedFacts": stated_facts or ["jogging"],
        "scoreEvidence": {
            "contextFit": context_fit,
            "clarity": clarity,
            "languageAccuracy": language_accuracy,
        },
    }
```

다음 모델 검증 사례를 추가한다.

- `coreAsks=[]`는 거부한다.
- 0, 1, 2가 아닌 점수와 문자열·불리언 점수를 거부한다.
- `addressed=true`인데 `evidence=null`이면 거부한다.
- `addressed=false`인데 `evidence`가 있으면 거부한다.
- 답하지 않은 요청의 `requiredPlaceholder`는 `[your hobby]` 같은 형식만 허용한다.
- 답한 요청에는 `requiredPlaceholder`를 허용하지 않는다.

- [ ] **Step 2: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: FAIL because the judgement models do not exist.

- [ ] **Step 3: 내부 Pydantic 모델을 최소 구현한다.**

`app/models/conversation.py`에 다음 구조를 추가한다.

```python
class MessageFeedbackCoreAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ask: str
    addressed: bool
    evidence: str | None = None
    requiredPlaceholder: str | None = None


class MessageFeedbackJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messageId: int = Field(gt=0)
    coreAsks: list[MessageFeedbackCoreAsk] = Field(min_length=1)
    statedFacts: list[str]
    scoreEvidence: MessageFeedbackScoreEvidence
```

필드 validator로 공백을 거부하고, model validator로 `addressed`, `evidence`, `requiredPlaceholder`의 조합과 정규식 `^\[your [a-z][a-z ]*\]$`을 확인한다. 사용자 발화 부분 문자열 검증과 `contextFit` 계산은 요청 문맥이 필요한 서비스 계층에 둔다.

- [ ] **Step 4: 모델 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS for the new model-validation cases; existing API cases may still fail until Task 3.

---

### Task 2: 사용자 발화 근거와 contextFit을 서버에서 검증

**Files**

- Modify: `app/conversation/application/next_message_service.py:200-285`.
- Modify: `tests/test_conversation_api.py:735-1020`.

**Interfaces**

- Add `_parse_message_feedback_judgement(data, request)`.
- Add `_feedback_type_from_score_evidence(score_evidence)`.
- Reuse `_normalize_evidence(value)`.

- [ ] **Step 1: 요청 문맥 불변식의 RED 테스트를 작성한다.**

다음 API 또는 helper 테스트를 추가한다.

- `addressed=true`의 evidence가 정규화된 `userMessage`에 없으면 `AiResponseInvalidError`다.
- `statedFacts` 값이 사용자 발화에 없으면 `AiResponseInvalidError`다.
- 모든 핵심 요청을 답했는데 `contextFit`이 2가 아니면 거부한다.
- 일부만 답했는데 `contextFit`이 1이 아니면 거부한다.
- 하나도 답하지 않았는데 `contextFit`이 0이 아니면 거부한다.
- 세 점수가 모두 2이면 서버 판정은 GOOD이다.
- 하나라도 2보다 낮으면 서버 판정은 NEEDS_IMPROVEMENT다.

- [ ] **Step 2: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: FAIL because judgement parsing and server-side feedback-type calculation are missing.

- [ ] **Step 3: 판정 파서와 검증 함수를 구현한다.**

```python
def _feedback_type_from_score_evidence(
    score_evidence: MessageFeedbackScoreEvidence,
) -> FeedbackType:
    scores = (
        score_evidence.contextFit,
        score_evidence.clarity,
        score_evidence.languageAccuracy,
    )
    return (
        FeedbackType.GOOD
        if all(score == 2 for score in scores)
        else FeedbackType.NEEDS_IMPROVEMENT
    )
```

`_parse_message_feedback_judgement`는 DTO 검증 뒤 다음 순서로 확인한다.

1. `messageId`가 요청값과 같은지 확인한다.
2. answered 개수로 기대 `contextFit`을 0, 1, 2 중 하나로 계산한다.
3. evidence와 stated fact를 `_normalize_evidence(request.userMessage)`에 포함되는지 확인한다.
4. 불일치하면 `AiResponseInvalidError`를 발생시킨다.

- [ ] **Step 4: 판정 검증 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS for judgement invariants.

---

### Task 3: 판정 전용 첫 호출과 판정이 잠긴 문구 생성 구현

**Files**

- Modify: `app/models/conversation.py:287-390`.
- Modify: `app/conversation/application/next_message_service.py:200-285`.
- Modify: `app/conversation/application/next_message_service.py:1080-1320`.
- Modify: `tests/test_conversation_api.py:606-1450`.

**Interfaces**

- Replace `_message_feedback_system_prompt` with `_message_feedback_judgement_system_prompt`.
- Replace `_message_feedback_user_prompt` with `_message_feedback_judgement_user_prompt`.
- Replace `_message_feedback_review_*` with `_message_feedback_copy_*`.
- Add internal `MessageFeedbackCopy` without `feedbackType` or `scoreEvidence`.
- Add `_assemble_message_feedback(judgement, copy, request)`.

- [ ] **Step 1: 두 호출의 역할 분리 RED 테스트를 작성한다.**

`FakeOpenAI`에 첫 호출의 판정 JSON과 두 번째 호출의 문구 JSON을 순서대로 반환하게 하고 다음을 확인한다.

- 첫 system prompt는 `Judgement Task`를 포함하고 사용자용 피드백 필드를 요구하지 않는다.
- 첫 user prompt는 `evaluationContext`와 `userMessage`를 포함한다.
- 첫 prompt는 scenario goal을 핵심 요청으로 분해하지 말라고 명시한다.
- 두 번째 system prompt는 `Copy Task`와 `authoritative judgement`를 포함한다.
- 두 번째 문구 JSON에는 `feedbackType`과 `scoreEvidence`가 없다.
- 서버가 판정 결과로 GOOD 또는 NEEDS_IMPROVEMENT를 조립한다.
- 문구 모델이 추가 필드로 `feedbackType`을 반환하면 `extra="forbid"`로 거부한다.

대표 부분 답변 테스트는 다음 데이터를 사용한다.

```python
judgement = message_feedback_judgement(
    context_fit=1,
    core_asks=[
        {
            "ask": "say what activity you like",
            "addressed": True,
            "evidence": "jogging",
            "requiredPlaceholder": None,
        },
        {
            "ask": "say why you like it",
            "addressed": False,
            "evidence": None,
            "requiredPlaceholder": "[your reason]",
        },
    ],
)
copy = {
    "messageId": 1001,
    "baseLocaleAnalogy": "좋아하는 활동만 말하고 이유는 덧붙이지 않은 것과 같아요.",
    "positiveFeedback": "좋아하는 활동을 분명히 말했어요.",
    "feedbackDetail": None,
    "correctionExpression": "I like jogging because [your reason].",
    "correctionReason": "좋아하는 이유가 빠졌어요. [your reason]에 이유를 넣어 보세요.",
    "benchmarkMessage": None,
    "detectedPatterns": [],
}
```

- [ ] **Step 2: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: FAIL because production still generates and reviews two complete feedback objects.

- [ ] **Step 3: 내부 문구 DTO와 조립 함수를 구현한다.**

`MessageFeedbackCopy`는 외부 문구 필드만 가지며 `detectedPatterns`는 기존처럼 파싱 전에 분리한다. `_assemble_message_feedback`는 서버가 계산한 `feedbackType`을 넣고 `MessageFeedbackData.model_validate`로 GOOD/NEEDS 필드 계약을 재검증한다.

NEEDS_IMPROVEMENT에서는 다음도 검사한다.

- 모든 `requiredPlaceholder`가 `correctionExpression`에 포함된다.
- 교정 표현에서 찾은 모든 대괄호 표현이 `^\[your [a-z][a-z ]*\]$`에 맞는다.
- `correctionReason`에 `re.search(r"[가-힣]", value)`가 성공한다.
- 기존 내부 정책 금지 문구 validator를 그대로 적용한다.

- [ ] **Step 4: `generate_message_feedback`의 정상 경로를 교체한다.**

```python
judgement_data = _request_json_completion(...max_tokens=512)
judgement = _parse_message_feedback_judgement(judgement_data, request)
copy_data = _request_json_completion(...max_tokens=768)
feedback, detected_patterns = _parse_and_assemble_message_feedback_copy(
    copy_data,
    judgement,
    request,
)
feedback = _postprocess_message_feedback_benchmark(
    feedback,
    detected_patterns,
    request.userMessage,
)
```

기존 전체 후보의 `MessageFeedbackEvaluation` 파싱과 `_message_feedback_review_*` 호출, 첫 후보 fallback을 제거한다. 캐시에는 최종 `MessageFeedbackData`와 판정 단계의 `scoreEvidence`만 저장한다.

- [ ] **Step 5: 판정 잠금과 외부 계약 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS. Response and cached feedback must not expose judgement internals.

- [ ] **Step 6: 첫 논리 커밋을 만든다.**

```bash
git add app/models/conversation.py app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 메시지 피드백 판정과 문구 생성을 분리"
```

---

### Task 4: 문구 검증 실패 시 한 번만 복구하고 잘못된 fallback 제거

**Files**

- Modify: `app/conversation/application/next_message_service.py:200-285`.
- Modify: `app/conversation/application/next_message_service.py:1190-1320`.
- Modify: `tests/test_conversation_api.py:800-1100`.

**Interfaces**

- Add `_message_feedback_copy_repair_system_prompt()`.
- Add `_message_feedback_copy_repair_user_prompt(request, judgement, invalid_data, validation_error)`.
- Normal path has 2 LLM calls; repair path has 3.

- [ ] **Step 1: 복구 정책의 RED 테스트를 작성한다.**

다음 호출 순서를 검증한다.

- 유효한 판정과 유효한 문구는 정확히 2회 호출한다.
- `[A little about yourself]`처럼 잘못된 플레이스홀더는 세 번째 복구 호출을 수행한다.
- 영어로만 작성된 `correctionReason`도 세 번째 복구 호출을 수행한다.
- 복구 문구가 유효하면 확정 판정과 함께 저장한다.
- 복구 문구도 유효하지 않으면 API가 `AI_RESPONSE_INVALID` 502를 반환하고 캐시에 저장하지 않는다.
- 판정 호출 자체가 실패하거나 판정 근거가 유효하지 않으면 문구 호출 없이 실패한다.
- 기존 첫 전체 피드백 fallback 로그와 동작이 남아 있지 않다.

- [ ] **Step 2: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: FAIL because copy repair does not exist and current code falls back to the first complete candidate.

- [ ] **Step 3: 복구 호출을 최소 구현한다.**

문구 파싱·조립에서 `AiResponseInvalidError`가 발생한 경우에만 원본 요청, 잠긴 판정, 유효하지 않은 문구 JSON, 검증 오류의 비민감 요약을 복구 prompt에 전달한다. LLM 또는 파싱 실패도 같은 한 번의 복구 기회를 사용한다. 복구 뒤에는 같은 parser와 조립 검증을 다시 사용하고 두 번째 실패는 그대로 전파한다.

- [ ] **Step 4: benchmark 후처리 회귀를 확인한다.**

다음 기존 테스트를 유지하거나 새 흐름에 맞게 fixture만 분리한다.

- 검증된 catalog pattern이 있는 GOOD은 catalog 문구로 덮어쓴다.
- 검증된 pattern이 없는 GOOD은 안전한 비정량 LLM 문구를 유지한다.
- 정량·출처 주장이 검증되지 않았으면 기본 문구를 사용한다.
- NEEDS_IMPROVEMENT는 `benchmarkMessage=null`이다.
- `detectedPatterns`는 외부 응답과 cache에 노출되지 않는다.

- [ ] **Step 5: 관련 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS.

- [ ] **Step 6: 두 번째 논리 커밋을 만든다.**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 유효한 피드백 문구만 저장하도록 검증"
```

---

### Task 5: 세션 점수에 GOOD 비율을 반영하고 별점을 최종 점수에만 연결

**Files**

- Modify: `app/conversation/application/next_message_service.py:300-310`.
- Modify: `app/conversation/application/next_message_service.py:533-555`.
- Modify: `app/conversation/application/next_message_service.py:640-665`.
- Modify: `tests/test_conversation_api.py:1600-1760`.

**Interfaces**

- Change `_native_score_from_message_feedback_entries(entries)` behavior for 3+ entries.
- Change `_star_rating_from_native_score(native_score, feedback_entries)` to `_star_rating_from_native_score(native_score)`.
- Keep response fields and enum values unchanged.

- [ ] **Step 1: 새 점수 경계의 RED 테스트를 작성한다.**

기존 별점 상한 테스트를 다음 점수 테스트로 교체한다.

- 메시지 1개 85점 NEEDS_IMPROVEMENT는 기존처럼 85점, 별 2.5개다.
- 메시지 2개의 원시 평균은 GOOD 비율 가중치 없이 기존 반올림을 유지한다.
- 원시 평균 82점, GOOD 0/3은 57점, 별 1.5개다.
- 원시 평균 90점, GOOD 1/3은 73점, 별 2.0개다.
- 원시 평균 95점, GOOD 2/3은 87점, 별 2.5개다.
- 원시 평균 100점, GOOD 3/3은 100점, 별 3.0개다.
- 원시 점수가 낮아 결합 점수가 50 미만이면 50점, 별 1.0개다.
- 별점 helper는 feedback entries를 받지 않고 같은 nativeScore에 항상 같은 별점을 반환한다.

- [ ] **Step 2: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.SessionFeedbackApiTests`

Expected: FAIL because nativeScore is still a raw average and starRating has a separate GOOD-ratio cap.

- [ ] **Step 3: 이중 반올림 없는 정수 계산을 구현한다.**

```python
def _native_score_from_message_feedback_entries(
    feedback_entries: list[_MessageFeedbackCacheEntry],
) -> int:
    if not feedback_entries:
        return 0

    message_scores = [
        _message_score_from_evidence(entry.score_evidence)
        for entry in feedback_entries
    ]
    message_count = len(message_scores)
    total_score = sum(message_scores)
    if message_count < 3:
        return (total_score * 2 + message_count) // (message_count * 2)

    good_count = sum(
        entry.feedback.feedbackType == FeedbackType.GOOD
        for entry in feedback_entries
    )
    numerator = total_score * 7 + good_count * 300
    denominator = message_count * 10
    rounded_score = (numerator * 2 + denominator) // (denominator * 2)
    return max(50, rounded_score)
```

`_star_rating_from_native_score`에서는 GOOD 개수와 별점 상한 코드를 제거한다. 호출부도 `native_score`만 전달한다.

- [ ] **Step 4: 점수와 별점 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.SessionFeedbackApiTests`

Expected: PASS with the exact boundary values above.

- [ ] **Step 5: 세 번째 논리 커밋을 만든다.**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 세션 점수에 원어민 발화 비율을 반영"
```

---

### Task 6: 실제 데이터 품질 평가 도구와 회귀 fixture를 새 단계에 맞게 수정

**Files**

- Modify: `scripts/evaluate_conversation_quality.py`.
- Modify: `tests/fixtures/lan_167_feedback_quality_cases.json`.
- Modify: `tests/test_quality_evaluation.py`.

**Interfaces**

- Quality result records judgement, locked feedback type, message score, generated copy, copy validation, and final feedback separately.
- Do not print or persist API keys.

- [ ] **Step 1: 새 결과 구조의 RED 테스트를 작성한다.**

평가 결과에 다음 필드를 요구한다.

- `judgement.coreAsks`.
- `judgement.statedFacts`.
- `scoreEvidence`.
- `lockedFeedbackType`.
- `messageScore`.
- `copyValidationPassed`.
- `finalFeedback`.
- `expectedFeedbackTypeMatched`.
- `expectedScoreRangeMatched`.

fixture의 중요 사례에는 기대 `contextFit`, 필수 플레이스홀더, 금지된 추가 사실을 기록한다. 특히 31, 52, 56, 146, 208, 257, 283, 292, 296, 317, 324, 329, 330, 335번을 포함한다.

- [ ] **Step 2: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation`

Expected: FAIL because the evaluator still expects one complete feedback candidate.

- [ ] **Step 3: 운영과 같은 판정·문구 흐름을 평가하도록 수정한다.**

평가 도구가 운영 서비스의 내부 helper를 재사용해 규칙이 중복되지 않게 한다. 각 단계의 원시 비민감 결과와 검증 결과는 분석 파일에 기록하되, 외부 API 응답 구조를 바꾸지 않는다.

- [ ] **Step 4: 평가 도구 단위 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation`

Expected: PASS.

- [ ] **Step 5: 품질 평가 변경을 커밋한다.**

```bash
git add scripts/evaluate_conversation_quality.py tests/fixtures/lan_167_feedback_quality_cases.json tests/test_quality_evaluation.py
git commit -m "test: 판정과 문구 품질을 분리해 평가"
```

---

### Task 7: 전체 검증과 실제 115개 발화 재평가

**Files**

- Modify: `context-notes.md` only if implementation discoveries differ from this approved design.
- Modify: `checklist.md` as each gate completes.
- Verify: FastAPI OpenAPI schema generated from `app/main.py`.

- [ ] **Step 1: 전체 정적·단위 검증을 실행한다.**

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall app scripts tests
.venv/bin/python -m pip check
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: 외부 계약이 유지되는지 확인한다.**

OpenAPI를 생성해 메시지 피드백과 세션 피드백 응답에 다음 내부 필드가 없는지 확인한다.

- `scoreEvidence`.
- `coreAsks`.
- `statedFacts`.
- `requiredPlaceholder`.
- `detectedPatterns`.

기존 `nativeScore` 정수 범위와 `starRating`의 `1.0`, `1.5`, `2.0`, `2.5`, `3.0` 계약이 유지되는지 확인한다.

- [ ] **Step 3: 중요 사례 14개를 각 3회 평가한다.**

Run the evaluator with `openai/gpt-5.4-mini` after confirming `OPENROUTER_API_KEY` is set without printing its value.

통과 기준은 다음과 같다.

- 42개 판정 모두 기대 `contextFit`과 feedback type이 일치한다.
- 146, 283, 329, 330번은 3회 모두 NEEDS_IMPROVEMENT다.
- 31번은 3회 모두 GOOD이다.
- 56, 208, 296, 329, 330, 335번에 사용자 발화에 없는 사실이나 이유가 추가되지 않는다.
- 필수 플레이스홀더와 한국어 `correctionReason` 검증 실패가 없다.

- [ ] **Step 4: 전체 115개 발화를 한 번 재평가한다.**

초기 기준선인 false GOOD 9/22, 중대한 교정 품질 문제 55/93과 비교한다. 중요 사례에서 반복되는 중대 오류가 하나라도 남거나 전체 중대 오류가 감소하지 않으면 완료 처리하지 않고 판정 또는 문구 단계 중 원인이 있는 쪽만 수정한다.

- [ ] **Step 5: 최종 diff와 커밋 범위를 검토한다.**

```bash
git status --short
git diff --stat origin/release/LAN-161...HEAD
git log --oneline origin/release/LAN-161..HEAD
```

Expected: 변경 줄은 판정·문구 분리, 세션 점수, 품질 평가와 문서에만 연결돼 있고 비밀 값이나 평가 원문 덤프가 커밋되지 않는다.

- [ ] **Step 6: 구현 기록을 마무리한다.**

`context-notes.md`에는 실제 모델 반복 평가 결과와 남은 위험만 추가하고, `checklist.md`의 완료된 항목을 체크한다. 문서 변경을 별도 커밋한다.

```bash
git add context-notes.md checklist.md
git commit -m "docs: LAN-167 품질 검증 결과 기록"
```

## 완료 기준

- [ ] 판정 단계가 핵심 요청, 원문 근거, 세 평가 점수만 생성하고 서버 검증을 통과한다.
- [ ] `feedbackType`과 메시지 점수는 서버가 확정하며 문구 생성 단계가 변경하지 못한다.
- [ ] 문구 단계가 필수 플레이스홀더, 한국어 이유, GOOD/NEEDS 필드 계약을 지킨다.
- [ ] 문구 실패는 한 번만 복구하고 검증되지 않은 전체 피드백으로 fallback하지 않는다.
- [ ] benchmark catalog와 내부 `detectedPatterns` 정책이 유지된다.
- [ ] 1~2개 발화 세션 점수는 기존 평균을 유지한다.
- [ ] 3개 이상 세션 점수는 원시 평균 70%와 GOOD 비율 30%를 반영한다.
- [ ] 별점은 최종 `nativeScore`에서만 계산한다.
- [ ] 중요 사례 14개 3회와 전체 115개 평가의 품질 기준을 충족한다.
- [ ] 전체 unittest, compileall, pip check, OpenAPI 회귀, diff check가 통과한다.

---

## 운영 안정화 후속 계획

### Task 8: 판정 형식 오류를 한 번만 복구한다

**Files**

- Modify: `app/conversation/application/next_message_service.py:105-125, 205-285, 1208-1385`.
- Modify: `tests/test_conversation_api.py:1020-1130, 1840-1870`.

**Interfaces**

- Add `_generate_message_feedback_judgement(request: MessageFeedbackRequest, settings: Settings) -> tuple[MessageFeedbackJudgement, bool]`.
- Add `_message_feedback_judgement_repair_system_prompt(evaluation_context_type: EvaluationContextType) -> str`.
- Add `_message_feedback_judgement_repair_user_prompt(request: MessageFeedbackRequest, invalid_judgement: dict[str, Any] | None, error: Exception) -> str`.
- Keep `generate_message_feedback()`의 외부 반환형과 API 오류 계약을 유지한다.

- [ ] **Step 1: 판정 복구 성공·실패의 RED 테스트를 작성한다.**

`tests/test_conversation_api.py`에 다음 두 테스트를 추가한다.

```python
def test_message_feedback_repairs_invalid_judgement_once(self):
    valid_judgement = message_feedback_judgement(
        context_fit=1,
        core_asks=[
            {
                "ask": "say what activity you like",
                "addressed": True,
                "evidence": "jogging",
                "requiredPlaceholder": None,
            },
            {
                "ask": "say why you like it",
                "addressed": False,
                "evidence": None,
                "requiredPlaceholder": "[your reason]",
            },
        ],
    )
    invalid_judgement = dict(valid_judgement)
    invalid_judgement["messageId"] = 9999
    fake_openai = FakeOpenAI(contents=[
        json.dumps(invalid_judgement),
        json.dumps(valid_judgement),
        json.dumps(message_feedback_copy()),
    ])
    app = create_app(make_settings(
        openrouter_api_key="test-openrouter-key",
        openrouter_model="openrouter-test-model",
    ))

    with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
        response = make_client(app).post(
            "/api/v1/conversation/message-feedback",
            json=multiple_hobby_questions_payload(),
        )

    self.assertEqual(response.status_code, 202)
    self.assertEqual(len(fake_openai.completions.calls), 3)
    self.assertIn(
        "Judgement Repair Task",
        fake_openai.completions.calls[1]["messages"][0]["content"],
    )


def test_message_feedback_rejects_invalid_judgement_after_one_repair(self):
    invalid_judgement = message_feedback_judgement(
        context_fit=1,
        core_asks=[
            {
                "ask": "say what activity you like",
                "addressed": True,
                "evidence": "jogging",
                "requiredPlaceholder": None,
            },
            {
                "ask": "say why you like it",
                "addressed": False,
                "evidence": None,
                "requiredPlaceholder": "[your reason]",
            },
        ],
    )
    invalid_judgement["messageId"] = 9999
    fake_openai = FakeOpenAI(contents=[
        json.dumps(invalid_judgement),
        json.dumps(invalid_judgement),
    ])
    app = create_app(make_settings(
        openrouter_api_key="test-openrouter-key",
        openrouter_model="openrouter-test-model",
    ))

    with patch("app.core.openai_client.OpenAI", return_value=fake_openai):
        response = make_client(app).post(
            "/api/v1/conversation/message-feedback",
            json=multiple_hobby_questions_payload(),
        )

    self.assertEqual(response.status_code, 502)
    self.assertEqual(len(fake_openai.completions.calls), 2)
    self.assertIsNone(get_cached_message_feedback(100, 1001))
```

- [ ] **Step 2: provider 실패를 복구하지 않는 RED 테스트를 보강한다.**

기존 `test_message_feedback_generation_failure_returns_503` 마지막에 다음 단언을 추가한다.

```python
self.assertEqual(len(fake_openai.completions.calls), 1)
```

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: 판정 복구 테스트는 호출 수와 repair prompt 단언에서 FAIL하고, provider 실패 테스트는 기존 503 계약을 유지한다.

- [ ] **Step 3: 판정 생성과 한 번의 복구를 최소 구현한다.**

`generate_message_feedback()`의 첫 호출과 parser 호출을 다음 helper로 옮긴다.

```python
def _generate_message_feedback_judgement(
    request: MessageFeedbackRequest,
    settings: Settings,
) -> tuple[MessageFeedbackJudgement, bool]:
    judgement_data: dict[str, Any] | None = None
    try:
        judgement_data = _request_json_completion(
            settings,
            system_prompt=_message_feedback_judgement_system_prompt(
                request.evaluationContext.type,
            ),
            user_prompt=_message_feedback_judgement_user_prompt(request),
            max_tokens=512,
        )
        return _parse_message_feedback_judgement(judgement_data, request), False
    except AiResponseInvalidError as exc:
        logger.warning(
            "AI 메시지별 피드백 판정을 복구합니다. "
            "workflow=message_feedback_judgement_repair sessionId=%s messageId=%s",
            request.sessionId,
            request.messageId,
        )
        repaired_data = _request_json_completion(
            settings,
            system_prompt=_message_feedback_judgement_repair_system_prompt(
                request.evaluationContext.type,
            ),
            user_prompt=_message_feedback_judgement_repair_user_prompt(
                request,
                judgement_data,
                exc,
            ),
            max_tokens=512,
        )
        return _parse_message_feedback_judgement(repaired_data, request), True
```

repair system prompt는 기존 판정 system prompt에 다음 규칙만 추가한다.

```text
Judgement Repair Task:
The previous judgement is invalid. Return one replacement that follows the judgement schema, evidence grounding, contextFit invariant, and [your ...] placeholder format exactly.
```

repair user prompt는 원본 요청, `invalid_judgement`의 JSON 또는 `null`, `type(error).__name__`만 전달한다. 로그에는 원시 판정 JSON과 사용자 발화를 넣지 않는다.

`generate_message_feedback()`에서는 다음처럼 사용한다.

```python
judgement, judgement_was_repaired = _generate_message_feedback_judgement(
    request,
    resolved_settings,
)
```

`AiGenerationFailedError`는 helper에서 잡지 않으므로 기존 503 흐름을 유지한다.

- [ ] **Step 4: 판정 복구 테스트와 메시지 피드백 전체 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: 정상 경로 2회, 판정 복구 성공 경로 3회, 판정 복구 재실패 2회, provider 실패 1회 호출이 모두 통과한다.

- [ ] **Step 5: 판정 복구 구현을 커밋한다.**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 유효하지 않은 메시지 판정을 한 번 복구"
```

### Task 9: 판정 복구 여부를 내부 품질 결과에 기록한다

**Files**

- Modify: `app/conversation/application/next_message_service.py:105-125, 610-640`.
- Modify: `scripts/evaluate_conversation_quality.py:120-245`.
- Modify: `tests/test_quality_evaluation.py:250-500`.

**Interfaces**

- Add internal `_MessageFeedbackCacheEntry.judgement_was_repaired: bool = False`.
- Add internal quality result field `judgementWasRepaired: bool`.
- Do not add the field to `MessageFeedbackData`, API responses, or OpenAPI.

- [ ] **Step 1: 내부 복구 여부 결과의 RED 테스트를 작성한다.**

평가 도구 mock cache entry에 `judgement_was_repaired=True`를 넣고 다음을 단언한다.

```python
self.assertTrue(results[0]["judgementWasRepaired"])
```

오류 결과에는 다음 단언을 추가한다.

```python
self.assertFalse(results[0]["judgementWasRepaired"])
```

- [ ] **Step 2: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation`

Expected: FAIL because cache entries and evaluation results do not expose the internal repair flag.

- [ ] **Step 3: cache와 평가 결과에 내부 flag를 연결한다.**

```python
@dataclass(frozen=True)
class _MessageFeedbackCacheEntry:
    feedback: MessageFeedbackData
    score_evidence: MessageFeedbackScoreEvidence
    user_message: str
    expires_at: float
    judgement: MessageFeedbackJudgement | None = None
    generated_copy: MessageFeedbackCopy | None = None
    judgement_was_repaired: bool = False
    copy_was_repaired: bool = False
```

`_store_message_feedback()` 인자와 생성부에 같은 flag를 추가하고, 평가 성공 결과에는 다음 값을 기록한다.

```python
"judgementWasRepaired": feedback_entry.judgement_was_repaired,
```

평가 오류 결과에는 `False`를 기록한다.

- [ ] **Step 4: 평가 도구와 OpenAPI 회귀를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_quality_evaluation tests.test_conversation_api.MessageFeedbackApiTests.test_message_feedback_openapi_uses_evaluation_context_contract`

Expected: PASS and OpenAPI contains no `judgementWasRepaired` field.

- [ ] **Step 5: 평가 계측 변경을 커밋한다.**

```bash
git add app/conversation/application/next_message_service.py scripts/evaluate_conversation_quality.py tests/test_quality_evaluation.py
git commit -m "test: 판정 복구 사용 여부를 품질 결과에 기록"
```

### Task 10: 실제 데이터로 운영 가능 기준을 검증한다

**Files**

- Modify: `context-notes.md`.
- Modify: `checklist.md`.
- Verify: `tests/fixtures/lan_167_feedback_quality_cases.json` and the approved 115-row CSV input under `/tmp`.

**Acceptance Gates**

- 전체 115건 중 최종 `AiResponseInvalidError`는 최대 1건이다. 1/115는 0.87%이므로 실패율 1% 이하를 만족한다.
- 정상 사례는 판정 복구 없이 2회 호출을 유지한다.
- 판정 복구는 최초 판정 검증 실패에서만 한 번 사용한다.
- 중요 사례의 `feedbackType`, 점수, 플레이스홀더, 사용자 사실 보존 품질은 기존 통과 결과보다 나빠지지 않는다.
- 목표를 넘으면 두 번째 blind retry를 추가하지 않고 실패 단계와 검증 원인을 다시 분류한다.

- [ ] **Step 1: 전체 정적·단위 검증을 실행한다.**

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall app scripts tests
.venv/bin/python -m pip check
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: 고정 품질 사례를 각 3회 평가한다.**

```bash
.venv/bin/python scripts/evaluate_conversation_quality.py \
  --cases tests/fixtures/lan_167_feedback_quality_cases.json \
  --runs 3 \
  --kind message-feedback \
  --output /tmp/lan-167-judgement-repair-fixture-results.json
```

Expected: 21개 결과의 기대 피드백 유형, `contextFit`, 점수 범위, 필수 플레이스홀더, 금지 문구 검사가 모두 통과한다.

- [ ] **Step 3: 기존 중요 사례 14개를 각 3회 평가한다.**

기존 `/tmp/lan-167-important-*.json` 입력을 사용해 총 42개 결과를 생성한다. 통과 기준은 다음과 같다.

- 31번은 3회 모두 GOOD이다.
- 146, 283, 329, 330번은 3회 모두 NEEDS_IMPROVEMENT다.
- 208, 321, 333, 335번의 교정 표현은 검증된 의미별 플레이스홀더를 사용한다.
- 사용자 발화에 없는 구체적인 이름, 장소, 취미, 경험, 이유가 추가되지 않는다.

- [ ] **Step 4: 전체 115개 발화를 한 번 평가한다.**

기존 승인된 CSV를 `/tmp/lan-167-user-data-cases.json`으로 변환한 입력을 사용한다. 결과 집계는 다음 값을 기록한다.

```text
totalResults
validationErrorCount
judgementRepairCount
copyRepairCount
GOODCount
NEEDS_IMPROVEMENTCount
messageScoreDistribution
```

Expected: `totalResults=115`, `validationErrorCount<=1`.

- [ ] **Step 5: 실패율과 문구 품질 gate를 판정한다.**

`validationErrorCount>1`이면 완료 처리하지 않는다. 실패 사례를 판정 호출, 판정 복구, 문구 호출, 문구 복구로 나눠 원인을 기록하고 추가 재시도 없이 설계를 다시 검토한다.

- [ ] **Step 6: 외부 계약과 최종 diff를 확인한다.**

OpenAPI에 `judgementWasRepaired`, `coreAsks`, `statedFacts`, `scoreEvidence`, `detectedPatterns`가 노출되지 않는지 확인한다.

```bash
git status --short
git diff --check
git log --oneline origin/release/LAN-161..HEAD
```

- [ ] **Step 7: 검증 결과를 문서화하고 커밋한다.**

```bash
git add context-notes.md checklist.md
git commit -m "docs: LAN-167 판정 복구 품질 검증 결과 기록"
```

## 운영 안정화 완료 기준

- [ ] 판정 형식 검증 실패만 한 번 복구한다.
- [ ] provider 실패는 재시도하지 않고 기존 503 계약을 유지한다.
- [ ] 판정 복구 결과도 유효하지 않으면 502를 반환하고 cache에 저장하지 않는다.
- [ ] 정상 경로는 LLM 2회, 판정 또는 문구 단일 복구 경로는 3회, 두 단계 모두 복구하면 최대 4회다.
- [ ] 전체 115건 실제 평가의 최종 형식 실패가 최대 1건이다.
- [ ] 고정 사례 21건과 중요 사례 42건의 기존 품질 기준이 유지된다.
- [ ] 내부 복구 flag가 외부 API와 OpenAPI에 노출되지 않는다.
- [ ] 전체 unittest, compileall, pip check, OpenAPI, diff check가 통과한다.

---

## 운영 배포 안정화 2차 실행 계획

### Task 11: 내부 검증 원인 코드를 계측한다

**Files**

- Modify: `app/conversation/application/next_message_service.py`.
- Modify: `scripts/evaluate_conversation_quality.py`.
- Modify: `tests/test_conversation_api.py`.
- Modify: `tests/test_quality_evaluation.py`.

**Interfaces**

- `AiResponseInvalidError(reason: str = "ai_response_invalid")`.
- 평가 성공 결과의 `validationReason=None`.
- 평가 실패 결과의 `validationReason=error.reason`.
- 외부 API 오류 코드는 계속 `AI_RESPONSE_INVALID`이다.

- [ ] **Step 1: 검증 원인 기록의 RED 테스트를 작성한다.**

문구에 필수 플레이스홀더가 없을 때 다음을 확인한다.

```python
with self.assertRaisesRegex(
    AiResponseInvalidError,
    "message_feedback_copy_missing_placeholder",
):
    next_message_service._validate_message_feedback_copy(judgement, feedback)
```

품질 평가 오류 결과에는 다음을 단언한다.

```python
self.assertEqual(results[0]["validationReason"], "test_validation_reason")
```

- [ ] **Step 2: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests tests.test_quality_evaluation`

Expected: error reason과 `validationReason`이 없어 FAIL한다.

- [ ] **Step 3: 원인 코드를 최소 구현한다.**

```python
class AiResponseInvalidError(Exception):
    def __init__(self, reason: str = "ai_response_invalid") -> None:
        super().__init__(reason)
        self.reason = reason
```

판정과 문구 파서의 각 검증 지점에서 사용자 데이터가 없는 고정 reason을 전달한다. 평가 오류 결과에는 `getattr(error, "reason", type(error).__name__)`를 기록한다.

- [ ] **Step 4: 테스트와 외부 계약을 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests tests.test_quality_evaluation`

Expected: PASS and API body remains unchanged.

- [ ] **Step 5: 커밋한다.**

```bash
git add app/conversation/application/next_message_service.py scripts/evaluate_conversation_quality.py tests/test_conversation_api.py tests/test_quality_evaluation.py
git commit -m "test: 메시지 피드백 검증 실패 원인을 내부 기록"
```

### Task 12: 이유 판정과 교정 근거 이탈을 문구 복구로 보낸다

**Files**

- Modify: `app/conversation/application/next_message_service.py`.
- Modify: `tests/test_conversation_api.py`.

**Interfaces**

- Add `_is_bare_evaluation_reason(core_ask: MessageFeedbackCoreAsk) -> bool`.
- Add `_meaningful_evidence_words(value: str) -> set[str]`.
- Extend `_validate_message_feedback_copy(judgement, feedback)` with evidence retention.

- [x] **Step 1: 이유 판정 근거의 RED 테스트를 작성한다.**

명시적인 why 핵심 요청에서 `Busan is best`의 `best`만 evidence로 사용하면 판정 파서가 `message_feedback_judgement_bare_reason`으로 거부하는지 확인한다. what-do-you-like-about 핵심 요청에서 `This is so cool`은 같은 검증에 걸리지 않아야 한다.

- [x] **Step 2: 교정 내용 근거의 RED 테스트를 작성한다.**

```python
with self.assertRaisesRegex(
    AiResponseInvalidError,
    "message_feedback_copy_unsupported_content",
):
    next_message_service._validate_message_feedback_copy(judgement, feedback)
```

`I like reading books because it is so cool.`과 `I recommend Busan because [your reason].`은 통과시킨다.

- [x] **Step 3: RED를 확인한다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: 이유 판정 불변식과 unsupported-content 검증이 없어 FAIL한다.

- [x] **Step 4: 이유 판정 불변식을 구현한다.**

핵심 요청의 `ask`가 why 또는 reason을 포함하고, addressed evidence의 의미 단어가 `best`, `good`, `great`, `cool`, `nice`, `awesome`으로만 구성되면 `message_feedback_judgement_bare_reason`으로 거부한다. 판정 프롬프트에도 같은 구분을 명시한다.

- [x] **Step 5: evidence 유지 검증을 구현한다.**

영문 단어를 소문자로 토큰화하고 기능어를 제외한다. addressed evidence에 의미 단어가 있으면 교정 표현과 하나 이상 겹쳐야 한다. 하나도 겹치지 않으면 `message_feedback_copy_unsupported_content`로 거부한다.

- [x] **Step 6: 문구 복구 프롬프트에 검증 원인을 전달한다.**

`type(error).__name__` 대신 `error.reason`을 전달한다. 복구 프롬프트에는 판정의 모든 필수 플레이스홀더를 별도 목록으로 넣고, unsupported-content에서는 evidence의 핵심 단어를 유지하라고 명시한다.

- [x] **Step 7: 메시지 피드백 전체 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests`

Expected: PASS with normal path 2 calls and repair path at most 3 calls.

- [ ] **Step 8: 커밋한다.**

```bash
git add app/conversation/application/next_message_service.py tests/test_conversation_api.py
git commit -m "fix: 사용자 근거 밖의 교정 내용을 문구 복구로 제한"
```

### Task 13: 언어 정확도 점수에 사용자 발화 근거를 요구한다

**Files**

- Modify: `app/models/conversation.py`.
- Modify: `app/conversation/application/next_message_service.py`.
- Modify: `tests/test_conversation_api.py`.

- [x] **Step 1: 점수와 근거 조합의 RED 테스트를 작성한다.**

`languageAccuracy<2`인데 근거가 없거나, 2인데 근거가 있으면 거부한다. 근거가 사용자 발화에 없으면 `message_feedback_judgement_language_issue_evidence`로 거부한다.

- [x] **Step 2: 판정 모델과 근거 검증을 구현한다.**

내부 `MessageFeedbackJudgement.languageIssueEvidence`를 추가하고 점수 조합과 사용자 발화 포함 여부를 검증한다.

- [x] **Step 3: 판정 프롬프트와 내부 출력 스키마를 갱신한다.**

0 또는 1이면 교정 가능한 문제를 포함한 가장 작은 사용자 발화 부분 문자열을 요구하고, 2면 `null`을 요구한다.

- [x] **Step 4: 메시지 피드백 회귀 테스트를 통과시킨다.**

Run: `.venv/bin/python -m unittest tests.test_conversation_api.MessageFeedbackApiTests tests.test_quality_evaluation`

Expected: PASS while the public response and normal two-call path remain unchanged.

- [x] **Step 5: 근거 단어를 남긴 채 새 사실을 추가하는 우회를 막는다.**

교정 표현의 내용어가 내부 판정 근거와 제한된 문장 뼈대 어휘 안에 있는지 검증한다. 판정·문구 복구 프롬프트에는 내부 실패 원인을 전달한다.

- [x] **Step 6: 모호한 일반 평가의 명료도 경계를 고정한다.**

`This is so cool` 같은 답은 what-do-you-like-about 요청에 `contextFit=2`, `clarity=1`, `languageAccuracy=2`가 되도록 판정 불변식과 프롬프트를 추가한다.

- [x] **Step 7: contextFit=0 교정 근거와 문법 뼈대를 분리한다.**

핵심 요청을 하나도 답하지 않은 경우 무관한 사용자 사실을 허용 어휘에서 제외한다. 자기소개와 여행 증빙 문장을 완성하는 제한된 뼈대 어휘는 허용하고, 모호한 일반 평가의 명료도는 서버가 결정적으로 정규화한다.

### Task 14: 운영 배포 gate를 다시 검증한다

**Files**

- Modify: `context-notes.md`.
- Modify: `checklist.md`.

- [ ] **Step 1: 전체 정적·단위 검증을 실행한다.**

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall app scripts tests
.venv/bin/python -m pip check
git diff --check
```

- [ ] **Step 2: 고정 21건과 중요 42건을 평가한다.**

고정 사례의 모든 자동 expectation이 통과하고, 중요 사례의 최종 형식 실패와 근거 없는 구체 내용 추가가 0건인지 확인한다.

- [ ] **Step 3: 전체 115건을 평가한다.**

Expected: `validationErrorCount<=1` and normal cases keep two model calls.

- [ ] **Step 4: 결과를 문서화하고 커밋한다.**

```bash
git add context-notes.md checklist.md
git commit -m "docs: LAN-167 운영 배포 품질 검증 결과 기록"
```
