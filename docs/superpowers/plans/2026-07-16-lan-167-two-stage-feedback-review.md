# LAN-167 피드백 판정·문구 분리와 세션 점수 Implementation Plan

**Goal:** 메시지 피드백의 의미 판정을 사용자용 문구 생성과 분리하고, 세 발화 이상 세션의 점수에 GOOD 비율을 반영해 피드백 유형·점수·별점이 일관되게 보이도록 한다.

**Architecture:** 첫 번째 LLM 호출은 `evaluationContext`의 핵심 요청과 사용자 발화 근거, 세 평가 항목만 반환한다. 서버가 근거와 점수의 불변식을 검증한 뒤 `feedbackType`을 확정한다. 두 번째 호출은 확정된 판정을 입력받아 사용자용 문구만 생성하며, 서버가 판정을 결합하고 플레이스홀더·한국어 이유·기존 GOOD/NEEDS 필드 계약을 검증한다. 문구 검증 실패 때만 한 번 복구 호출하고, 검증되지 않은 전체 피드백으로 fallback하지 않는다. 메시지 점수는 유지하되 3개 이상 세션은 원시 평균 70%와 GOOD 비율 30%를 정수 반올림해 `nativeScore`를 만들고 별점은 최종 점수에서만 계산한다.

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
