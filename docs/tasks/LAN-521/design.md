# LAN-521 — 장기기억을 피드백 재료로 쓰기 설계

## 1. 결정

새 BE→AI 호출 없이 기존 네 호출에 입출력만 얹는다.

| 기능 | 엔드포인트 | 추가 입력 | 추가 출력 |
| --- | --- | --- | --- |
| 표현 재사용 판정 | `expression-recommendations` | `learnedExpressions` (최대 50) | `usedExpressions` |
| 후속 질문 생성 | `memory-candidates` | `existingMemories` (최대 20), `askedMemoryIds`, `sessionEndedBy` | `followUpQuestion` (필수) |
| 후속 질문 꺼내기 | `opening`, `turn`(첫 사용자 턴만) | `pendingFollowUp` | `followUpAsked`, `followUpId` |
| 기억 근거 교정 | `inner-thought` | `memoryContext` (최대 3) | `correction.usedMemoryId` |

보조 판정(재사용·후속 질문·교정)은 절대 본 응답을 실패시키지 않는다. 실패하면 빈 값으로 내려주고 WARNING 로그를 남긴다.
로그에는 사용자 문장과 프롬프트 텍스트를 쓰지 않는다.

## 2. 표현 재사용 판정

- 추천이 확정된 **뒤에 순차로** 별도 LLM 호출을 한 번 한다(`expression_reuse_service.find_used_expressions`).
  비동기 잡이라 지연이 문제되지 않으므로 스레드를 쓰지 않는다. `learnedExpressions`가 비면 호출하지 않는다.
- 입력은 USER 메시지의 `{messageId, content}`와 `learnedExpressions`뿐이다. 추천 프롬프트에는 `learnedExpressions`를 넣지 않는다.
- 서버 검증(`domain/expression_reuse_rules.py`)은 항목 단위로 버린다: 목록 밖 ID, USER 메시지가 아닌 ID,
  원문에 없는 `matchedText`. 포함 검사는 LAN-518의 `locate_original_sentence`를 재사용하며(대소문자·공백 무시)
  `matchedText`를 원문 조각으로 교체한다. 같은 표현·같은 메시지는 한 건.
- 완료 기준 측정: 검증에서 버린 수를 `workflow=free_talk_expression_reuse_dropped dropped= total=`로 남긴다.

## 3. 후속 질문

선택 규칙은 **서버 코드**가 지킨다(`domain/follow_up_rules.py`). LLM은 질문 문장을 쓰고 계기를 분류할 뿐이다.

1. `askedMemoryIds`의 기억은 프롬프트에 아예 넣지 않는다 → 같은 기억으로 두 번 묻는 일이 불가능하다.
2. `validTo`가 지난 EVENT(`temporalStatus = EXPIRED`)가 있으면 **그 기억들만** 프롬프트에 넣는다 → 지나간 일정이
   고민·목표보다 먼저 뽑힌다. 시간 상태는 기존 `memory_context_with_time_status`로 계산한다.
3. LLM이 후보 질문을 최대 3개 낸다(`memoryId | candidateIndex`, `triggerType`, `question`, `invite`).
4. 서버가 항목을 검증하고 `FollowUpTriggerType` 선언 순서(CUT_OFF > PAST_EVENT > CONCERN > GOAL > MOOD > HOBBY)로
   하나를 고른다. 같은 순위면 먼저 나온 것.
5. 고를 게 없거나 호출이 실패하면 `NONE` + 기본 문구. 기존 기억도 새 후보도 없으면 LLM을 호출하지 않는다.

항목 검증: 프롬프트에 보인 기억의 ID만 / `candidateIndex`는 이번 후보 범위 안 / 둘 중 정확히 하나 /
`CUT_OFF`는 새 후보만 / `PAST_EVENT`는 EVENT 타입 기존 기억만 / 문구가 비었거나 느낌표가 있으면 버림.

### `validTo`가 없는 일정

`validTo`는 후보 추출 LLM이 채우며, 추출 프롬프트는 "끝 날짜를 알 때만 23:59:59, 아니면 null"이라고 시킨다.
하루짜리 일정("8월 28일에 면접이 있다")은 null로 저장될 수 있고, 이 경우 서버는 지났는지 계산할 수 없다.
그래서 PAST_EVENT 판정은 2단이다.

- `validTo`가 있는 EVENT: 서버 계산만 믿는다. 아직 유효하면 모델이 PAST_EVENT라고 해도 버린다.
- `validTo`가 null인 EVENT: 모델이 `content`의 달력 날짜와 프롬프트의 현재 시각을 비교해 PAST_EVENT를 붙일 수 있다.
  추출 규칙상 상대 시간 표현은 달력 날짜로 바뀌어 `content`에 남아 있다. 정렬은 여전히 서버가 한다.

후보 추출 프롬프트(v10)에는 새 입력 세 개가 들어가지 않는다. 추출 규칙과 `extractorVersion`은 그대로다.

## 4. 오프닝·첫 턴에서 질문 꺼내기

- `pendingFollowUp`이 **있을 때만** 시스템 프롬프트 끝에 `Pending Follow-up:` 절을 덧붙이고, `followUpAsked`가 있는
  structured output 하위 모델을 쓴다. 없을 때는 시스템·사용자 프롬프트와 스키마가 기존과 같아 품질 회귀가 없다.
- `followUpId`는 모델을 거치지 않고 서버가 입력값을 그대로 돌려준다. 입력이 없거나 종료 의사가 감지되면
  `followUpAsked = false`.
- 후속 질문을 꺼냈고 그 근거 기억이 `memoryContext`에 있으면 서버가 `usedMemoryIds`에 확정적으로 포함한다.
  기존 단어 겹침 검증(고유 단어 2개 이상)은 "면접 어떻게 됐어?" 같은 짧은 질문을 통과시키지 못한다.
- `turn`은 `isFirstUserTurn = false`인데 `pendingFollowUp`이 오면 400이다.

## 5. 기억 근거 교정

- `memoryContext`는 교정 프롬프트에만 `{memoryId, content, observedAt}`로 들어간다. 속마음 프롬프트에는 넘기지 않아
  공유 속마음 프롬프트·계약은 그대로다.
- 교정 프롬프트에 `Memory Grounding:` 절을 추가했다. 기억이 정답을 바꿀 때만 근거로 쓰고 `usedMemoryId`를 돌려준다.
  기억이 없으면 "듣는 사람이 이미 안다"는 추측으로 a/an→the, this/that을 고치지 않는다.
- LAN-518의 ARTICLE 예시 `at a gym (a place both know) -> at the gym`은 기억 없이도 the gym으로 고치게 유도할 수 있어
  일반 관사 예시로 바꾸고, 서로 아는 대상의 관사는 Memory Grounding 절로 옮겼다.
- 요청에 없던 기억 ID는 `usedMemoryId = null`로 버리고 WARNING을 남긴다. 교정 문장은 유지한다.

## 6. 명세서와 다른 점 (Notion 반영 필요)

현재 코드가 기준이며 명세서 예시가 오래된 항목이다.

- `correction.mistakePattern` 목록은 `FreeTalkMistakePattern`(16 + OTHER)이다. 명세서의 `PAST_TENSE`, `THIRD_PERSON_S`,
  `VOCAB_CHOICE`는 없다.
- `reactedToPartner`는 교정 판정이 실패하면 `null`이다(명세서는 필수 Boolean).
- `extractorVersion`은 `memory-candidate-v10`이다(명세서 예시는 `memory-v3`).
- `opening`/`turn`의 `emotion`은 서버가 항상 `null`로 내려준다.
- 이슈 본문의 `usedMemoryIdForCorrection`은 명세서대로 `correction.usedMemoryId`로 구현했다.
- `ExpressionRecommendationsRequest`에는 `extra="forbid"`가 없어 정의되지 않은 최상위 필드는 400이 아니라 무시된다.
  조이면 현재 백엔드 요청이 깨질 수 있어 이번에 바꾸지 않았다. `learnedExpressions[]` 항목은 `extra="forbid"`다.

## 7. 배포 순서

요청·응답 모델이 `extra="forbid"`이므로 **AI 서버를 먼저 배포**한 뒤 백엔드가 새 요청 필드를 보내기 시작한다.
AI 서버만 배포된 상태에서는 새 응답 필드(`usedExpressions = []`, `followUpQuestion = NONE`, `followUpAsked = false`,
`usedMemoryId = null`)가 기본값으로 나가며 사용자에게 보이는 변화가 없다. `followUpQuestion`은 필수 응답 필드이므로
백엔드 역직렬화가 모르는 필드를 허용하는지 배포 전에 확인한다.

## 8. 검증

- `tests/test_free_talk_expression_reuse_api.py`: 변형·끼어듦·축약 매치, 원문 조각 교체, 항목별 버림과 집계 로그,
  중복 처리, 빈 목록이면 호출 없음, 실패 3종에도 추천 정상, 두 프롬프트의 입력 분리, 400 5종, OpenAPI, 순수 규칙.
- `tests/test_free_talk_follow_up_api.py`: PAST_EVENT > CONCERN, EXPIRED 게이팅, asked 제외, CUT_OFF, 아직 유효한 일정
  거부, 호출 생략, 실패 3종에도 후보 정상, 추출 프롬프트 불변, 400 5종, OpenAPI, 우선순위 표와 항목 검증 규칙.
- `tests/test_free_talk_pending_follow_up_api.py`: 오프닝·첫 턴의 true/false, ID 에코, 입력 없이 true 주장 무시,
  종료 감지, 근거 기억 사용 확정, 첫 턴 아님 400, 입력 형식 400 5종, 프롬프트는 뒤에만 덧붙음, OpenAPI.
- `tests/test_free_talk_correction_api.py`: 기억 근거 ID 반환, 모르는 ID 버림, 기억은 교정 프롬프트에만, 속마음
  프롬프트 불변, 기억 없는 추측 금지 문구, 기억 4개 400.
