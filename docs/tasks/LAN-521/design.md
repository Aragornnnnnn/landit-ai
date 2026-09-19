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
- 재사용 판정과 후속 질문 호출은 재시도 없이 `free_talk_auxiliary_timeout_seconds`(기본 20초) 안에서만 돈다. 이미 계산한
  추천·후보 응답을 보조 호출이 오래 붙잡지 않게 하기 위함이다.
- 완료 기준 측정: 검증에서 버린 수를 `workflow=free_talk_expression_reuse_dropped dropped= total=`로 남긴다.

## 3. 후속 질문

선택 규칙은 **서버 코드**가 지킨다(`domain/follow_up_rules.py`). LLM은 질문 문장을 쓰고 계기를 분류할 뿐이다.

1. `askedMemoryIds`의 기억은 프롬프트에 아예 넣지 않는다 → 같은 기억으로 두 번 묻는 일이 불가능하다.
2. 지나간 예정 일정(EVENT이고 `validTo`가 지났거나, `validTo`가 없으면 `content`의 날짜가 지남 — 아래 절)이 있으면
   **그 기억들만** 프롬프트에 넣는다 → 지나간 일정이 고민·목표보다 먼저 뽑힌다. `validTo` 기준 시간 상태는 기존
   `memory_context_with_time_status`로 계산한다.
3. LLM이 후보 질문을 최대 3개 낸다(`memoryId | candidateIndex`, `triggerType`, `question`, `invite`).
4. 서버가 항목을 검증하고 `FollowUpTriggerType` 선언 순서(CUT_OFF > PAST_EVENT > CONCERN > GOAL > MOOD > HOBBY)로
   하나를 고른다. 같은 순위면 먼저 나온 것.
5. 고를 게 없거나 호출이 실패하면 `NONE` + 기본 문구. 기존 기억도 새 후보도 없으면 LLM을 호출하지 않는다.

항목 검증: 프롬프트에 보인 기억의 ID만 / `candidateIndex`는 이번 후보 범위 안 / 둘 중 정확히 하나 /
`CUT_OFF`는 새 후보만 / `PAST_EVENT`는 EVENT 타입 기존 기억 중 서버가 지났다고 판정했거나 판정할 수 없는 것만 /
문구가 비었거나 느낌표가 있으면 버림.

### `validTo`가 없는 일정

`validTo`는 후보 추출 LLM이 채우며, 추출 프롬프트는 "끝 날짜를 알 때만 23:59:59, 아니면 null"이라고 시킨다.
실측에서 하루짜리 미래 일정 7건은 **전부 `validTo = null`**이었고 기간이 명시된 일정 1건만 채워졌다(8절). 즉 `validTo`만
보면 지나간 일정은 사실상 뽑히지 않는다. 모델에게 `content`의 날짜와 현재 시각을 비교시키는 방식도 0/3으로 실패했다.

그래서 `validTo`가 없는 EVENT는 서버가 `content`의 달력 날짜를 직접 읽는다(`scheduled_date_status`). 추출 규칙이 상대
시간 표현을 금지하고 달력 날짜로 바꿔 적게 하므로 읽을 수 있다. 형식은 `YYYY-MM-DD`와 `YYYY년 M월 D일` 두 가지다.

| 판정 | 조건 | 처리 |
| --- | --- | --- |
| `PASSED` | 가장 늦은 날짜가 관찰일보다 뒤이고 오늘보다 앞 | 지나간 예정 일정. 게이팅 대상이며 PAST_EVENT 허용 |
| `UPCOMING` | 가장 늦은 날짜가 오늘 이후 | PAST_EVENT 거부 |
| `NOT_SCHEDULED` | 가장 늦은 날짜가 관찰일 이전 ("9월 7일에 영화를 봤다") | 말할 때 이미 끝난 일이라 PAST_EVENT 거부 |
| `UNKNOWN` | 날짜를 못 읽었거나 관찰일을 모름 | 모델이 PAST_EVENT를 붙이면 받아들인다. 정렬은 서버가 한다 |

`validTo`가 있으면 항상 `validTo`가 우선한다. 관찰일은 `observedAt`, 없으면 `validFrom`이며 요청 시간대 기준 날짜로 비교한다.
영어 등 다른 표기(`September 23, 2026`)는 `UNKNOWN`으로 떨어진다. `content`가 기준 언어(KR)로 저장되는 현재는 해당이 없다.

후보 추출 프롬프트(v10)에는 새 입력 세 개가 들어가지 않는다. 추출 규칙과 `extractorVersion`은 그대로다.

## 4. 오프닝·첫 턴에서 질문 꺼내기

- `pendingFollowUp`이 **있을 때만** 시스템 프롬프트 끝에 `Pending Follow-up:` 절을 덧붙이고, `followUpAsked`가 있는
  structured output 하위 모델을 쓴다. 없을 때는 시스템·사용자 프롬프트와 스키마가 기존과 같아 품질 회귀가 없다.
- `followUpId`는 모델을 거치지 않고 서버가 입력값을 그대로 돌려준다. 입력이 없거나 종료 의사가 감지되면
  `followUpAsked = false`.
- 후속 질문을 꺼냈고 그 근거 기억이 `memoryContext`에 있으면 서버가 `usedMemoryIds`에 확정적으로 포함한다.
  기존 단어 겹침 검증(고유 단어 2개 이상)은 "면접 어떻게 됐어?" 같은 짧은 질문을 통과시키지 못한다.
- **`followUpAsked`는 모델의 자기 보고를 그대로 믿지 않는다.** 실측에서 모델은 자기 질문("어디로 등산 가?")을 하고도
  `true`라고 보고했다(첫 턴 10건 중 2건). 잘못 `true`가 되면 백엔드가 재시도를 멈춰 화면에서 약속한 질문이 조용히
  사라진다. 서버는 `translatedMessage`에 질문 원문이나 근거 기억의 어간이 하나도 없으면 `false`로 내리고
  `workflow=free_talk_follow_up_unverified` 경고를 남긴다. 조사·어미 차이(`제주` ⊂ `제주도는`) 때문에 토큰 일치가 아니라
  어간 포함으로 본다. 질문과 번역문이 같은 기준 언어라 가능한 비교다. 질문이 너무 짧아 대조할 단어가 없으면("왜?")
  검증할 수 없으므로 보고를 그대로 믿는다. 잘못 `false`가 되면 다음 세션에 한 번 더 물을 뿐이다.
- **첫 턴은 질문이 빠지면 한 번 복구 재호출한다**(`free_talk_turn_follow_up_repair`). 기존 턴 프롬프트의 "반응한 뒤 후속
  질문 하나"가 강해 프롬프트만으로는 7/10이었다. 같은 함수의 `CONTINUE` 복구와 같은 패턴이며, 복구가 실패하거나 또 묻지
  않았거나 종료 판정을 뒤집거나 응답 계약을 어기면(메시지 누락 등) 첫 응답을 그대로 쓴다. 세션당 첫 턴 한 번, 질문이 빠졌을 때만 추가 호출이 생긴다.
- **기준 언어 질문 원문을 `aiMessage`에 붙여 넣은 응답은 묻지 않은 것으로 본다.** 실측에서 모델이 한국어 질문을 영어
  메시지에 그대로 붙여 넣고 `true`라고 보고한 경우가 오프닝 40건 중 2건 있었다. 학습 언어와 기준 언어가 다를 때만 검사한다.
  오프닝도 이 경우와 질문 누락 시 한 번 복구 재호출한다(`free_talk_opening_follow_up_repair`). 복구가 실패하면 첫 응답을
  쓰되, 첫 응답이 원문을 붙여 넣은 것이면 학습 언어 메시지 계약 위반이라 `AI_RESPONSE_INVALID`(502)로 돌려 백엔드의 기존
  오프닝 재시도 경로를 타게 한다.
- `turn`은 `isFirstUserTurn = false`인데 `pendingFollowUp`이 오면 400이다.

## 5. 기억 근거 교정

- `memoryContext`는 교정 프롬프트에만 `{memoryId, content, observedAt}`로 들어간다. 속마음 프롬프트에는 넘기지 않아
  공유 속마음 프롬프트·계약은 그대로다.
- 교정 프롬프트에 `Memory Grounding:` 절을 추가했다. 기억이 정답을 바꿀 때만 근거로 쓰고 `usedMemoryId`를 돌려준다.
  기억이 없으면 "듣는 사람이 이미 안다"는 추측으로 a/an→the, this/that을 고치지 않는다.
- LAN-518의 ARTICLE 예시 `at a gym (a place both know) -> at the gym`은 기억 없이도 the gym으로 고치게 유도할 수 있어
  일반 관사 예시로 바꾸고, 서로 아는 대상의 관사는 Memory Grounding 절로 옮겼다.
- 요청에 없던 기억 ID는 `usedMemoryId = null`로 버리고 WARNING을 남긴다. 교정 문장은 유지하되, 그 교정이 관사 교체뿐이면
  근거가 사라진 것이므로 아래 규칙에 따라 교정도 함께 버린다.
- **기억 근거 없이 `a/an → the`만 바꾼 교정은 서버가 버린다**(`is_only_definite_article_swap`). "at the gym"은 영어에서
  관용적으로 자연스러워 모델이 기억 없이도 계속 고치려 했고(실측 7/10), 프롬프트로는 완료 기준을 보장할 수 없었다.
  반응 판정은 유지하고 교정만 `null`로 내린다. 단어를 더하거나 다른 곳도 고친 교정(`go to gym → go to the gym`)은 해당 없다.
  한계: 같은 메시지 안에서 두 번째로 언급해 the가 맞는 경우도 함께 버려진다.

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
- `tests/test_free_talk_correction_api.py`: 기억 근거 ID 반환, 모르는 ID 버림, 근거 없는 관사 교체 버림 3종, 단어를 더한
  관사 교정 유지, 기억은 교정 프롬프트에만, 속마음 프롬프트 불변, 기억 없는 추측 금지 문구, 기억 4개 400.
- `tests/test_free_talk_correction_rules.py`: 관사 교체 판별 규칙.

### 실제 OpenRouter 검증 (2026-09-19, `openai/gpt-5.4-mini`)

LAN-518과 같은 모델 가정이다. 스크립트와 원자료는 레포 밖 스크래치에만 두었다. "처음"은 첫 구현, "최종"은 이 문서의 구현이다.

| 완료 기준 | 측정 | 처음 | 최종 |
| --- | --- | --- | --- |
| 서버 검증에서 걸리는 `usedExpressions` < 5% | 대화 15개 × 2회, 주장 38건 | 0/40 | **0/38 (0%)** |
| (참고) 재사용 판정 정확도 | 같은 세트, 함정 발화 포함 | 정밀도 0.95 / 재현율 1.00 | **1.00 / 1.00** |
| 같은 기억으로 두 번 묻지 않음 | 물어본 고민 + 취미 × 3회 | 3/3 | **3/3** (코드 보장) |
| 지나간 일정이 고민보다 먼저 (`validTo` 있음) | × 3회 | 3/3 | **3/3** (코드 보장) |
| 지나간 일정이 고민보다 먼저 (`validTo` null) | × 3회 | **0/3** | **3/3** (content 날짜 규칙) |
| 다가올 일정을 지나간 일정으로 오인하지 않음 | × 3회 | 3/3 | **3/3** |
| 끊긴 얘기가 최우선 | `TIME_LIMIT_REACHED` × 3회 | 3/3 | **3/3** |
| 첫 두 턴 안에 질문 (오프닝) | 10세션 | 10/10 (다른 회차에 원문 붙여넣기 1건) | **10/10**, 한국어 혼입 0 |
| 첫 두 턴 안에 질문 (USER_FIRST 첫 턴) | 10세션, 메시지를 직접 읽어 판정 | 8/10, 거짓 `true` 2건 | **10/10** (복구 도입 직후 회차는 9/10), 거짓 `true` 0건 |
| 기억 있으면 the gym + 기억 ID | 10회 | 1/10 | **10/10**, ID 10/10 |
| 기억 없으면 a gym 유지 | 10회 | 10/10 | **10/10** |
| (회귀) LAN-518 교정 | 멀쩡 3 + 실수 3 발화 × 2회 | 12/12 기대대로 | **12/12**, p50 1.3 / p90 1.7초 |
| 후속 질문 문구의 느낌표 | 18건 | 0 | **0** |
| (참고) 하루짜리 미래 일정의 `validTo` 채움 | 추출기 8발화 | — | 하루짜리 0/7, 기간 1/1 |

### 대규모 holdout 검증 (2026-09-19, 약 750회 호출)

위 표는 항목당 3~20회였고 같은 세트로 고치고 다시 재는 일을 반복해 수치가 부풀려졌을 수 있었다. 그래서 한 번도 쓰지 않은
데이터(표현 30 + 15개, 기억 60여 개, 후속 질문 20종, 교정 대상 12종)로 다시 쟀다. "수정 전"은 위 표의 구현 그대로다.

| 항목 | 표본 | 수정 전 | 수정 후 |
| --- | --- | --- | --- |
| 재사용: 서버 원문 검증 탈락률 (기준 < 5%) | 주장 137 / 90건 | 2.2% | **3.3%** (끼어든 말 때문에 구절이 이어지지 않은 1종) |
| 재사용: 정밀도 / 재현율 | 90회, 회마다 글자 그대로 쓴 함정 문장 포함 | **0.65** / 0.97 | **1.00** / 0.97 |
| 재사용: 정밀도 / 재현율 (두 번째 새 세트) | 60회 | — | **0.85** / 1.00 |
| 후속 질문: 최우선 기억을 고름 | 무작위 시나리오 60개 × 2 | 116/120 (96.7%) | — |
| 후속 질문: 지나간 일정 우선 / 물어본 기억 재질문 / 다가올 일정 오인 | 같은 120회 | 54/54, 0, 0 | — |
| 후속 질문: 느낌표 / 존댓말 | 같은 120회 | 0, 0 | — |
| 오프닝에서 질문 | 60세션 | 60/60 | 60/60 |
| 첫 턴에서 질문 (서버 판정) | 60세션 | 59/60 | 58/59 + 502 1건 |
| 기준 언어(한국어)가 `aiMessage`에 샘 | 오프닝·첫 턴 120건 | **3건** (2건은 `true`로 나감) | **0건** |
| 작별 인사 시 종료 감지, `followUpAsked = false` | 10 | 10/10 | 10/10 |
| 기억 있음 → 교정 + 올바른 기억 ID | 12종 × 3 | 19/36 (53%), ID 19/19 | — |
| 기억 없음 / 무관한 기억 → 관사 교체 | 각 36 | 0 / 0, 무관한 기억 인용 0 | — |
| 멀쩡한 발화 오교정 / 실수 포착 + 기대 패턴 | 24 / 24 | 0/24, 24/24 | — |

holdout이 드러낸 것과 조치:

- **재사용 정밀도 0.65.** "I ate a piece of cake"를 관용구 사용으로 잡았다. 첫 검증의 1.00은 프롬프트에 예시로 넣은 바로 그
  문장들로 잰 과적합이었다. 예시를 더 넣는 대신 모델이 주장마다 `sentenceMeaning`(문장이 실제로 뜻하는 바)을 먼저 쓰고
  `sameMeaning`을 판정하게 했고, 서버는 `true`만 받는다. 두 번째 새 세트의 오탐 11건은 두 문장뿐이며 그중
  "skating on thin ice"는 글자 그대로이면서 위험하다는 뜻도 담아 사람도 애매하다. 함정 문장을 매 대화에 넣은 적대적
  세트라 실제 대화의 정밀도는 이보다 높을 것이다.
- **한국어 혼입 3/120.** 2건은 질문을 한국어로 풀어 써서 "원문 그대로 붙여넣기" 검사를 빠져나갔다. 기준 언어가 KR이고 학습
  언어가 다르면 `aiMessage`의 한글 자체를 누출로 본다. 복구 후에도 새면 오프닝·첫 턴 모두 `AI_RESPONSE_INVALID`(502)다.
- **`followUpAsked` 검증의 거짓 양성.** `true` 판정 표본 14건을 직접 읽으니 1건이 오판이었다: 사용자가 영화를 봤다고 했는데
  "How was it?"이라고 묻자 `어땠어`가 겹쳐 결혼식 질문을 한 것으로 봤다. 첫 턴의 실제 질문율은 서버 판정(59/60)보다 낮은
  90% 초반으로 본다. 반대 방향 오판(풀어 쓴 감정 질문을 `false`로 판정)도 1건 있었다. 고치지 않았고 운영에서 본다.
- **기억 근거 교정 53%**는 결함이 아니라 모델의 절제로 본다. 장소·반려동물(헬스장, 수영장, 도서관, 요가 학원, 강아지)은
  3/3인데 "I rode a bike to work"처럼 그 자체로 자연스러운 문장은 기억이 있어도 고치지 않는다. 고칠 때의 기억 ID는 항상 맞았다.
- 사용자가 그 얘기를 먼저 꺼낸 첫 턴 10건은 전부 `followUpAsked = true`로 나갔다. 명세서는 `false`를 기대하지만 백엔드
  입장에서는 "다시 묻지 않는다"는 같은 결과라 두었다. 질문이 다소 중복되게 들리는 경우가 있다.

독립 코드 리뷰(`code-reviewer`)에서 나온 지적도 반영했다: 복구 응답이 메시지를 비우면 멀쩡한 첫 응답이 502가 되던 문제,
보조 호출의 무제한 타임아웃, 대조할 단어가 없는 질문에서 복구가 매번 헛도는 문제, 프롬프트와 서버 규칙의 `some` 불일치.

중간에 고친 것: 재사용 판정이 글자 그대로의 뜻("the cat is on the fence")을 관용구로 잡던 오탐, 오프닝이 한국어 질문
원문을 `aiMessage`에 붙여 넣던 1건, "번역문에도 같은 질문을 담아라"는 문구가 번역문을 영어로 만들던 회귀(3/10 → 0/20).

남은 관찰 사항: 감정(MOOD) 질문은 "요즘 어때?"처럼 일반적인 말로 풀려 어간 검증이 `요즘` 같은 흔한 단어에 기대게 된다.
운영에서 `free_talk_follow_up_unverified` 경고 빈도를 본다. 하루짜리 일정의 `validTo`를 채우도록 추출 프롬프트를 고치는
일은 v10 추출기 회귀 검증이 필요해 별도 이슈로 둔다.
