# LAN-531 스몰톡 컨텍스트 및 LLM 비용 최적화 설계

작성일: 2026-09-20. 이 문서는 AI·BE 구현의 단일 기준이다. 이전 임시 실행 계획보다 이 문서의 계약과 실패 처리를 우선한다. 수치들은 검증을 시작할 기본값과 목표이며 운영에서 검증된 성과가 아니다.

## 1. 목표와 범위

스몰톡의 매 요청에 전체 세션 이력을 넣는 방식을 길이가 제한된 세션 요약과 최근 원문으로 바꾼다. 대화·속마음·종료 응답에 적용하고, 요약 호출까지 합친 비용과 맥락 유지 품질을 평가한다.

- BE는 원문·요약·처리 상태를 소유한다. AI는 요청에 받은 정보로 생성하고 상태를 저장하지 않는다.
- DB의 원문·번역문, 첫 턴 판정, 제목·종료 상태, 멱등성, 표현 추천과 장기기억의 원문 근거는 보존한다.
- 최초 버전은 대화와 속마음 모두 같은 요약·최근 8왕복 정책을 사용한다. 속마음 3왕복은 평가 후보이며 기본 구현·출시 조건이 아니다.
- 장기기억 V2, 동적 검색, 모델 교체, durable queue, Redis, LangChain, AI 전용 DB, A/B 배정 시스템, 비용 DB·대시보드는 추가하지 않는다.
- 실제 LLM 평가에는 합성 대화를 사용한다. 운영 원문 재전송이나 평가 데이터로의 반출을 이 설계로 승인한 것으로 해석하지 않는다.

## 2. 확인한 코드와 보존할 경계

AI 기준은 `origin/develop`의 `f247bfe6ebbe7690e5dab17aeb4dcecc4208fce9`다. BE 구조는 로컬 `feat/LAN-488`의 `cb69c949b`에서 확인했다. BE는 모듈 재배치 중이므로 구현 시작 때 최신 develop·진행 중 PR을 확인하고 아래 클래스의 실제 위치를 다시 찾는다. 설계만을 위해 BE 전체를 LAN-488로 재배치하거나 해당 브랜치를 임의 병합하지 않는다.

| 코드 | 확인한 동작 / 구현 시 제약 |
|---|---|
| BE `FreeTalkSubmittedMessageService` | 원본 이력과 현재 발화를 예약 값으로 반환한다. 이 값을 모델용 윈도우로 덮어쓰지 않는다. |
| BE `FreeTalkMessageService` | 원본 이력으로 첫 사용자 턴·검색 쿼리를 계산하고 대화·속마음을 각각 호출한다. 모델용 컨텍스트는 그 이후에 만든다. |
| BE `FreeTalkMessageSessionService` | 기존 세션의 `updated_at`으로 진행 중 요청 만료를 판단한다. 요약 저장이 이 시각을 갱신하지 않게 별도 테이블을 사용한다. |
| [AI 대화 생성](../../../app/free_talk/application/conversation_service.py) | turn·inner-thought·closing 및 제목 repair에서 payload를 직렬화한다. 모든 해당 경로를 같은 컨텍스트 정책으로 맞춘다. |
| [AI 요청 DTO](../../../app/models/free_talk.py) | 마지막 USER의 ID·턴 번호가 submitted 필드와 같아야 한다. 잘린 이력도 이를 만족해야 한다. |
| [공통 속마음 정책](../../../app/common/inner_thought_prompt.py) | 반복 거절과 관계 분위기를 누적 맥락으로 판단한다. 프리톡 최적화가 시나리오 정책을 바꾸면 안 된다. |
| [LLM 호출](../../../app/free_talk/llm/json_completion.py), [클라이언트 생성](../../../app/core/openai_client.py) | SDK 생성과 요청은 분리돼 있다. 요약 전용 deadline·재시도 정책을 기존 일반 호출에 전역 적용하지 않는다. |

BE 현재 경로는 `feature/learning/freetalk/{message,innerthought,client,domain,repository}`와 `feature/learning/conversation/history`다. 신규 요약 로직은 freetalk의 `context` 업무에 둔다. 공통 대화 이력은 해당 업무의 공개 Service와 값 객체로 읽고 Entity·Repository를 직접 가져오지 않는다.

## 3. 입력 정책과 불변 조건

왕복은 완료된 USER 발화와 대응 AI 응답이다. 세션 첫 AI 인사는 원문에 보존하되 완료 왕복 수에는 넣지 않는다. `messageSequence` 정렬·역할·처리 상태로 구간을 만든다. 리스트 길이의 절반이나 `turnNumber * 2`로 계산하지 않는다. 종료 확인 대기·처리 중인 USER를 요약 완료 범위에 포함하지 않는다.

| 설정 | 최초 값 |
|---|---:|
| `context.enabled` | false |
| `context.allowed-user-ids` | 빈 목록. 활성화 초기에는 내부 계정만 명시. |
| `context.allow-all-users` | false |
| `context.recent-rounds` | 8 |
| `context.summary-trigger-rounds` | 미요약 완료 왕복 12개 이상 |
| `context.summary-trigger-bytes` | 미요약 원문 JSON의 UTF-8 12,000바이트 이상. 사전 신호이며 토큰 수가 아님. |
| `context.summary-source-max-bytes` | 첫 시도 원문 구간 UTF-8 6,000바이트. 최종 토큰 검사는 AI가 수행. |
| `FREE_TALK_CONTEXT_INPUT_BUDGET_TOKENS` | 일반 생성의 축소 목표 8,000 추정 토큰. 최소 원문은 초과 허용. |
| `FREE_TALK_SUMMARY_MAX_TOKENS` | 요약 JSON 전체 800 추정 토큰 |
| 요약 LLM 입력 예산 / 출력 상한 | 8,000 추정 토큰 / completion 800토큰 |
| AI 요약 deadline / BE HTTP timeout | 8초 / 10초 |
| 요약 실행 선점 유효기간 / 실패 후 최소 간격 | 30초 / 30초 |
| 요약 전용 BE 실행기 | 인스턴스당 동시 2개·대기 8개, 포화 시 거부. 부하 검증 후 조정. |

BE 설정의 전체 prefix는 `landit.free-talk.context`다. AI 환경변수와의 매핑은 배포 단계에서 추가한다.

`recent-rounds=8`은 정상 요약 후 남길 목표다. 요약 경계 뒤의 미요약 대화가 9~12왕복이면 이를 모두 전달한다. 최신 8왕복만 기계적으로 잘라 요약과 원문 사이를 누락하지 않는다. 현재 USER는 완료 왕복 수와 별도로 끝에 붙인다.

필수 불변 조건은 다음과 같다.

1. 현재 사용자 발화와 직전 AI 질문은 완전한 원문으로 보존한다. 문자열 중간을 몰래 잘라 넣지 않는다.
2. 정상 컨텍스트는 저장된 요약이 다룬 구간 + 그 이후의 원문 전체로 구성한다. 순서를 바꾸거나 실제 메시지 ID를 다시 만들지 않는다.
3. 요약 확정 경계는 BE가 고른 마지막 완료 AI 메시지의 sequence다. 모델이 반환한 번호로 경계를 진행시키지 않는다.
4. 새 USER 원문의 명시적 정정을 요약·장기기억보다 우선한다. 요약의 추측을 원문 근거로 간주하지 않는다.
5. 신규 정책 적용 여부는 세션 시작 때 결정한다. 기능을 나중에 켰다는 이유로 기존 세션을 중간 전환하지 않는다. 끄기는 진행 중 세션에도 다음 요청부터 적용한다.

### 토큰 예산 검사

모델별 로컬 토크나이저는 AI에만 둔다. 기존 의존성에 없으므로 `tiktoken` 추가를 기본안으로 하되, 구현 시 지원 버전·배포 모델의 인코딩 매핑을 검증하고 고정한다. 미지원 모델을 임의 인코딩으로 처리하지 않는다. 설정 단계에서 발견하고 해당 정책의 운영 활성화를 보류한다.

검사 대상은 system 지침 + 요약 + 원문 + 장기기억 + JSON 직렬화 + response schema다. 메시지 포맷 등 제공자 오버헤드의 추정 오차를 위해 최소 512토큰을 예산에 예약한다. 실제 `usage.prompt_tokens`와 대조해 여유분을 보정한다. 이것은 모델 문맥 한도의 정확한 계수나 과금액을 보장하는 값이 아니다.

AI가 예산을 초과하면 오래된 완료 원문 구간부터 제외하고 다시 계산한다. 제외한 구간이 요약되지 않은 범위라면 해당 요청은 `historyIncomplete=true`이며 기존 요약 전체를 사용하지 않는다. 빠진 구간에 정정이 있을 수 있기 때문이다. 직전 AI·현재 USER만으로도 예산을 넘으면 해당 원문을 자르지 않고 LLM에 전달해 생성을 계속한다.

2026-09-22 사용자 결정으로 일반 대화·속마음·종료의 예산 초과 즉시 실패를 제거한다. `FREE_TALK_CONTEXT_TOO_LARGE`(HTTP 400)는 AI에서 더 이상 반환하지 않는다. 예산은 입력 축소 목표이며 제공자의 실제 입력 한도를 보장하지 않는다. 제공자 오류·timeout은 기존 실패 처리와 종료 응답의 안전한 fallback을 유지한다. 요약 전용 입력 제한과 시나리오 정책은 변경하지 않는다.

## 4. 세션 요약 데이터

요약 본문 `SessionSummaryContent`는 다음 네 필드로 제한한다. 자유로운 JSON 키, 사용자가 지정한 system 지침, 원문 전체 복사는 허용하지 않는다.

| 필드 | 형식 / 의미 |
|---|---|
| `topic` | 짧은 문자열. 대화 주제와 진행 상황. |
| `userStatements` | 최대 8개 `{text, sourceMessageIds}`. 사용자 직접 진술·정정·부정·계획을 구분해서 표현. |
| `openThreads` | 최대 4개 `{text, sourceMessageIds}`. 미응답 질문·미완료 논의. AI의 질문이라는 주체를 보존. |
| `interactionContext` | 최대 4개 `{text, sourceMessageIds}`. 반복 거절 등 관측된 상호작용. 성격·의도 추정 금지. |

각 항목의 sourceMessageIds는 중복 없는 양수 최대 4개다. 새 요약이 참조할 수 있는 ID는 기존 요약의 참조 ID와 새 sourceMessages의 ID 합집합이다. 새 userStatements의 근거는 USER 원문이어야 하고, 기존 요약에서 넘어온 근거는 previousSummary.userStatements에 이미 있던 ID만 허용한다. 이전 openThreads나 interactionContext의 ID를 역할 정보 없이 사용자 사실의 근거로 승격시키지 않는다. Pydantic의 extra 금지·빈 문자열·배열 길이·토큰 예산을 검사한다. 이 검사는 문장의 사실성을 증명하지 못하므로 실제 모델 회귀 평가도 필요하다.

과거 사건을 현재 사실로 바꾸거나 계획을 완료 사건으로 바꾸지 않는다. 상대 날짜는 offset이 있는 발화 시각과 요청 timezone을 기준으로만 해석한다. 근거가 부족하면 확정 날짜를 만들어내지 않는다. 숫자·고유명사·부정·정정은 우선 보존하고, 공간이 부족하면 중요도가 낮은 전체 항목을 제외한다. 반복 요약으로 세부 정보가 손실될 수 있다는 한계는 유지한다.

요약은 세션용 파생 데이터다. 장기기억 추출·resolution·표현 추천·발화 평가의 sourceMessages로 넘기지 않는다. 요약만 사용한 응답에 `usedMemoryIds`를 새로 부여하거나 복구하지 않는다.

## 5. AI·BE 계약

### 기존 생성 API의 선택 필드

`POST /api/v1/free-talk/turn`, `/inner-thought`, `/closing`에 아래 필드만 추가한다. 별도 명시가 없는 기존 필드는 그대로 유지한다. opening과 장기기억 API에는 추가하지 않는다.

```json
{
  "contextPolicyVersion": "v1",
  "sessionSummary": {
    "revision": 2,
    "coveredThroughSequence": 17,
    "content": {
      "topic": "주말 여행 계획",
      "userStatements": [
        {"text": "사용자는 토요일에 여행할 계획이라고 말했다.", "sourceMessageIds": [3016]}
      ],
      "openThreads": [],
      "interactionContext": []
    }
  },
  "historyIncomplete": false
}
```

- 예시는 기존 요청에 추가되는 부분이며 완전한 turn 요청이 아니다.
- 기본값은 `contextPolicyVersion=null`, `sessionSummary=null`, `historyIncomplete=false`다. 필드가 없으면 기존 전체 이력 경로를 따른다. `v1` 외의 알려지지 않은 버전은 검증 오류다.
- `historyIncomplete=true`이면 sessionSummary는 null이어야 한다. AI 내부 예산 검사로 불완전해진 경우에도 같은 규칙을 적용한다.
- conversationHistory의 기존 메시지 형식과 마지막 USER 검증은 유지한다. messageSequence는 BE의 원문 snapshot에서 관리하며 공통 시나리오 메시지 DTO에 전역 추가하지 않는다.
- 활성화되지 않은 요청에는 신규 필드를 null/default로 직렬화하지 말고 생략한다. 구버전 AI의 extra 금지와 충돌하지 않아야 한다.
- turn·inner-thought·closing의 성공 응답과 FE 정상 응답 필드는 변경하지 않는다. 예산 검사 결과와 요약 사용 상태는 서버 내부 로그로 관측한다.

### 요약 생성 API

`POST /api/v1/free-talk/context-summary`를 기존 인증·응답 봉투 안에 추가한다. AI 모델이 요약만 생성하며 이 API가 DB를 조회하지 않는다.

| 요청 필드 | 계약 |
|---|---|
| `sessionId` | FreeTalkSession ID. LearningSession ID와 혼용하지 않음. |
| `policyVersion`, `baseRevision` | `v1`, 0 이상 정수. 기존 요약이 없으면 revision 0. |
| `previousSummary` | SessionSummaryContent 또는 null. |
| `coveredThroughSequence` | 이전 확정 경계 P. 최초 0. |
| `targetThroughSequence` | BE가 선택한 새 경계 S. S > P. |
| `timezone` | 유효한 IANA timezone. |
| `sourceMessages` | P < sequence <= S인 원문 전체를 순서대로 전달. 각 항목은 sequence·messageId·turnNumber·role·content·occurredAt을 포함. occurredAt은 offset 필수. |

BE는 기존 원문 timestamp의 저장 시간대에 맞춰 occurredAt을 offset 포함 instant로 변환한다. 현재 KST로 저장하는 컬럼을 UTC로 간주하지 않으며 장기기억 요청의 검증된 변환 방식과 맞춘다.

응답 data는 `policyVersion`, `baseRevision`, `coveredThroughSequence`(요청의 S), `summary`를 포함한다. 버전·revision·경계는 AI 서비스 코드가 요청에서 복사하고 모델에 생성시키지 않는다. 모델에 필요한 발화·참조 ID 외의 작업 선점 토큰이나 DB 운영 정보는 프롬프트에 넣지 않는다.

입력 구간은 BE가 DB에서 정한 범위와 대조한다. sequence와 ID의 증가·중복 없음, 현재 sourceMessages의 참조 ID와 역할을 AI에서도 검사한다. 번호가 정수상 연속적이어야 하는 것은 아니다. 실제 저장된 메시지가 해당 범위에서 빠지지 않는 것이 기준이다.

- 요청 자체가 잘못됐으면 기존 422 검증 오류, 요약 출력이 잘못됐으면 502 `AI_RESPONSE_INVALID`다.
- 요약 입력 토큰 초과는 내부 전용 400 `FREE_TALK_SUMMARY_INPUT_TOO_LARGE`로 구분한다. 경계는 진행시키지 않는다.
- 제공자 장애·deadline 초과는 503 `AI_GENERATION_FAILED`다. BE에서는 모두 요약 작업 실패로 처리하며 일반 대화 오류로 전달하지 않는다.

### Deadline과 숨은 재시도

요약 endpoint만 async로 작성하고 기존 OpenAI SDK의 AsyncOpenAI와 `asyncio.timeout`으로 전체 8초 deadline을 적용한다. client 생성은 llm/core 경계에 두고 기존 credential 검증을 재사용한다. 이 문서의 선택은 일반 sync endpoint를 모두 바꾸라는 의미가 아니다.

SDK `max_retries=0`, 요청 timeout은 남은 deadline 이하, 포맷 repair·즉시 재요약 0회로 시작한다. schema를 지원하지 않는 설정은 평가에서 발견해 수정하며 요약 호출을 몰래 여러 번 늘리지 않는다. BE는 요약 endpoint에만 10초를 적용하고 일반 requestTimeout은 유지한다. HTTP 취소가 이미 시작된 제공자 생성·과금까지 취소한다는 보장은 없다. 애플리케이션 종료 시간과 관측 가능한 추가 호출 여부를 검증하고, 실패 후 과금도 비용에 포함한다.

## 6. BE 저장 모델과 동시성

freetalk 업무가 `free_talk_context_summary`를 소유한다. 세션당 1행이며 별도 이력 테이블은 만들지 않는다. 새 적용 대상 세션 시작 트랜잭션에서 비어 있는 행을 생성한다. 행이 없는 기존 세션에는 런타임 backfill을 하지 않는다.

| 컬럼 | 의미 |
|---|---|
| `free_talk_session_id` | PK, 세션 FK. 물리 삭제 시 cascade. |
| `policy_version` | 세션 시작 시 선택한 v1. 적용 대상 여부의 snapshot. |
| `summary_content` | nullable JSON. JPA/테스트 DB 호환 검증 후 PostgreSQL jsonb로 매핑. |
| `covered_through_sequence`, `revision` | 최초 0. 성공 저장 때만 증가. |
| `lease_token`, `lease_until` | 실행 선점 식별자·만료. 없으면 실행 중이 아님. |
| `next_attempt_at` | 실패/포화 후 재시도 가능 시각. |
| `source_byte_limit` | 최초 6,000. 입력 초과 시 다음 작업의 더 작은 구간 선택에 사용. |
| `suspended_reason` | 최소 완료 구간도 요약 입력에 들어가지 않을 때 `OVERSIZED_UNIT`. 이 세션의 자동 재시도 중지. |
| `created_at`, `updated_at` | 요약 전용 시각. 기존 free_talk_session.updated_at과 분리. |

작업 시각은 timezone을 포함한 instant로 저장하고 선점·만료 비교에는 DB 시각을 사용한다. 본문이 null이면 coveredThroughSequence=0이어야 한다. lease token·만료는 둘 다 존재하거나 둘 다 없어야 한다. Flyway 번호는 구현 시 최신 원격·진행 중 PR·대상 DB 이력을 확인해 배정하며 문서에서 미리 예약하지 않는다.

선점과 저장은 짧은 트랜잭션으로 분리한다.

1. executor 작업이 실행될 때 해당 세션의 유효성·정책·nextAttempt를 확인한다. 큐 대기 중에는 lease를 잡지 않는다.
2. lease가 없거나 만료됐을 때 조건부 선점한다. 세션당 성공한 작업 하나만 snapshot을 가져간다. 이전 revision과 P, target S, lease token을 작업 값에 고정한다.
3. sourceMessages는 해당 시점에 커밋된 원문으로 읽는다. S는 snapshot 시점의 최근 8왕복을 제외한 가장 뒤의 완료 AI 메시지다. 더 큰 구간은 source_byte_limit 안에서 완료 왕복 단위로 줄인다.
4. DB 잠금·트랜잭션을 끝내고 외부 AI를 호출한다.
5. 결과 저장은 `sessionId + policyVersion + revision + coveredThroughSequence + leaseToken` 일치를 모두 요구한다. lease 만료·세션 삭제·비활성 사용자·유효하지 않은 대상 상태도 확인한다. 한 행만 갱신되면 summary 교체, 경계 S, revision+1, lease 해제, 다음 source_byte_limit의 설정 기본값 복원을 같은 트랜잭션에서 처리한다.
6. 늦은 작업이 revision이나 lease 조건을 만족하지 못하면 결과를 버린다. 실패 처리도 자신의 lease token이 맞을 때만 수행한다. 후속 작업의 lease를 해제하지 않는다.

일반 대화·사용자 상태와 함께 잠글 필요가 있는 경우 기존 사용자 → 학습 세션 → 프리톡 세션 순서를 유지하고 요약 행은 마지막에 잠근다. 요약 선점은 가능하면 요약 행의 조건부 갱신만 사용한다. 서로 반대 순서로 잠금을 획득하지 않는지 PostgreSQL 경합 테스트로 확인한다.

세션 물리 삭제 FK와 별개로 탈퇴·소프트 삭제 경로를 확인해 요약도 같은 보존 정책을 따른다. 완료 후 도착한 요약은 초기 버전에서 저장하지 않는다. 비활성 세션을 결과 저장 코드가 upsert로 다시 만들지 않는다.

## 7. 요청·갱신 흐름과 복구

1. 기존 방식으로 세션 소유권·상태·재전송을 검증하고 USER 발화를 예약한다. 재전송으로 완성된 응답을 반환할 때 새 LLM 호출을 만들지 않는다.
2. 원본 예약 이력으로 첫 턴·검색·제목 여부를 확정한다. 컨텍스트 조립기는 그 값을 바꾸지 않고 요약 snapshot과 미요약 원문을 만든다.
3. 대화와 속마음에 같은 summary revision과 원문 snapshot을 전달한다. prompt 지침은 각각 유지한다. 요약 작업 완료를 기다리지 않는다.
4. 일반 CONTINUE 응답의 DB 저장 커밋 후 임계치를 검사하고 비동기 작업을 등록한다. EXIT_CONFIRMATION_REQUIRED·종료 완료·실패 보상 중에는 새 요약을 시작하지 않는다.
5. 작업 등록 실패는 대화 응답을 실패시키지 않는다. executor는 CallerRunsPolicy를 사용하지 않으며, 포화 시 조건부로 nextAttempt를 미루고 집계한다. 등록 경로에서 이미 선점된 다른 작업을 덮어쓰지 않는다.
6. 실행 도중 재시작되면 다음 사용자 활동에서 만료 lease를 선점해 다시 계산한다. 상시 재처리 스캐너나 durable queue는 없다. 활동이 없으면 요약을 복구할 필요도 없다.

| 상황 | 일반 대화 / 요약 상태 |
|---|---|
| 이력이 짧고 요약 없음 | 전체 원문. 요약 호출 없음. |
| 정상 요약 존재 | 요약 + P 이후 원문 전체. 다음 USER도 끝에 포함. |
| 요약 지연·실패, 예산 이내 | 같은 정상 요약 + 미요약 원문 전체. 기존 summary·P는 유지. |
| 미요약 구간을 예산 때문에 제외 | 해당 요청의 요약을 비활성화하고 최근 원문만 사용. historyIncomplete=true. 누락된 과거 사실을 추측하지 않도록 지시. |
| 새 요약의 형식·길이·참조 검증 실패 | 저장하지 않고 30초 이후 사용자 활동에서 재시도. |
| 요약 입력 초과 | source_byte_limit를 줄이고 다음 작업에서 더 적은 완료 구간으로 재시도. 같은 요청 안의 반복 LLM 호출 없음. |
| 최소 완료 구간 1개도 초과 | suspendedReason 저장, 요약 자동 재시도 중지. 대화는 예산 제한 경로로 계속 진행하며 해당 상태를 집계. |
| USER와 직전 AI만으로 예산 초과 | 최소 원문 전체를 보존해 LLM 생성 진행. 최적화 예산 초과만으로 요청을 거절하지 않음. |
| 기능 OFF | 다음 요청부터 신규 필드를 생략하고 DB 원문으로 기존 요청 생성. 요약 작업 등록 중지. |

입력 초과를 확인할 때 이미 정상 AI 응답이 완료된 대화 구간까지 삭제하거나 요약 경계를 건너뛰지 않는다. 요약 API의 크기 초과 응답은 선검사 결과이므로 유료 LLM 요청을 만들지 않아야 한다. source_byte_limit 하한에서 진행 불가능한 작업을 매 턴 재등록하는 무한 루프를 막는다.

## 8. 프롬프트·사용 기록·호환성

- 요약은 system 지침으로 삽입하지 않고 원문과 함께 참조 데이터 영역에 둔다. 현재 원문 > 과거 요약이라는 우선순위를 명시한다.
- 이력의 번역문과 ID는 최초 구현에서 유지한다. 불필요한 필드 제거를 별도 비용 절감 변경으로 섞지 않는다.
- 역사적 기억의 validFrom·validTo, 현재 시간·timezone 정책은 유지한다. 요약도 질문·예정·완료·불확실성을 구분한다.
- usedMemoryIds는 해당 요청에 실제 제공한 memoryContext ID의 부분집합만 허용한다. 요약의 sourceMessageIds와 섞지 않는다. 모델 자기보고라는 기존 해석도 유지한다.
- 종료 응답과 제목 repair에 같은 컨텍스트를 사용하고, 요약을 추가했다고 종료 질문이나 제목 생성 조건을 바꾸지 않는다.
- 속마음의 반복 거절 판정을 위해 interactionContext를 제공한다. 빈약한 요약만으로 HOSTILE을 단정하지 않는다. 시나리오 공유 정책은 변경하지 않고 프리톡 전용 입력 설명을 보강한다.
- 구버전 BE → 신버전 AI를 지원한다. 신버전 BE의 context.enabled=false는 구버전 AI에 신규 필드를 보내지 않는다. 새 BE 활성화는 호환 AI 배포 이후에만 가능하다.

BE의 컨텍스트 활성화는 master flag와 세션의 policy 행이 모두 있을 때만 유효하다. 내부 계정 허용 목록은 신규 세션 등록 시 평가한다. 정상 사용자 전체 확대는 allowAllUsers를 명시적으로 켜야 하며, 빈 허용 목록을 전체 허용으로 해석하지 않는다. 신규 요약 결과 저장 직전에도 master flag와 대상의 유효성을 확인한다.

## 9. 구현 순서와 인수인계

구현자는 두 저장소의 최신 AGENTS.md·브랜치·dirty 상태부터 확인한다. AI 문서 브랜치는 feat/LAN-531이며 BE 구현 브랜치는 아직 만들지 않았다. 다른 이슈 브랜치나 사용자의 untracked 파일을 정리하지 않는다. 별도 plan.md·checklist.md·context-notes.md를 중복 작성하지 않고 구현 중 확정한 값과 검증 결과는 이 문서에 갱신한다.

| 단계 | 작업과 산출물 |
|---|---|
| 1 | 기존 요청 캡처·재현 fixture, 원본 예약 값과 모델용 컨텍스트 조립 분리. 기존 동작의 회귀 테스트. |
| 2 | AI 선택 필드·요약 DTO/API, 요약 서비스, token budget, 요약 전용 async deadline. OpenAPI 계약 테스트. |
| 3 | BE 추가형 migration·요약 저장·구간 읽기·조건부 선점/저장·전용 executor·timeout. 플래그 OFF. |
| 4 | turn·inner-thought·closing·제목 repair 연결, 신규 입력 길이 오류 매핑, 실패 복구·상태 전이·삭제 처리. |
| 5 | 전체 테스트와 실제 모델 품질·과금 비교. 정책 수치 확정과 제한 적용 준비. |

각 단계는 재현 테스트 → 최소 구현 → 회귀 테스트 순서다. 메서드는 작고 역할이 분명하게 나누며 실제 중복이 없는 추상화는 만들지 않는다. 새 source 역할 주석·JavaDoc·Lombok 등 각 저장소 규칙을 적용한다. 논리 단위 커밋과 리뷰 가능한 PR로 나누되 가능한 500줄 기준 때문에 연결되지 않는 변경을 억지로 분할하지 않는다.

## 10. 검증과 출시 기준

### 자동 검증

- 정상/경계: AI 선시작, 11/12/13왕복, 요약 전후의 원문 전체 연결, 현재 USER와 직전 AI 보존, duplicate·out-of-order·sequence gap·revision 역행.
- 상태: 첫 턴 장기기억 검색, 종료 확인·계속하기·시간 제한·정상 종료, 제목 repair, 같은 clientMessageId 재전송, 생성 실패 보상.
- 원문: 번역만 반복한 응답의 memory use 오탐 방지, 요약이 장기기억·표현 추천의 근거에 섞이지 않음, 원문 DB 불변.
- 장애: 요약 JSON/schema/참조/길이 오류, 입력 초과, timeout, SDK 재시도 0회, executor 포화, lease 만료·재시작·역순 완료·삭제 경합.
- 예산: 한·영 혼합, 긴 한 문장·한 번의 긴 입력, 수백~1,000턴 누적, schema·고정 prompt 변경, 모르는 model encoding, 최소 구간 초과의 재시도 중지.
- 로컬 지연 HTTP 서버로 BE 요약 timeout과 일반 requestTimeout의 분리, AI provider deadline과 추가 요청 수, 정상 대화가 요약을 기다리지 않는지 검증.
- 로컬 PostgreSQL로 CAS·잠금 순서·FK·migration을 검증한다. H2 테스트 통과를 PostgreSQL 동시성 검증으로 보고하지 않는다.
- AI 관련 unittest 및 전체 `.venv/bin/python -m unittest discover -s tests`, BE 관련 테스트 및 `./gradlew check`, 기존/신규 JSON과 OpenAPI 호환 검사. 기존 변경 때문에 생긴 실패는 분리한다.

### 실제 LLM 평가

같은 합성 세션을 전체 이력 방식과 요약+8왕복 방식으로 재생한다. 5·12·30·100왕복 길이, 동일한 모델·정책·입력 시나리오, 최소 3회 반복을 시작 조건으로 한다. 다른 날짜·provider·캐시 상태가 결과를 왜곡하지 않도록 실행 순서를 섞고 실제 model/provider를 기록한다. 연속 요약 결과를 다음 턴에 사용해 누적 오류까지 평가한다. 단일 턴의 이상적인 수제 요약만 비교하지 않는다.

필수 품질 사례는 사실 정정·부정·고유명사·숫자·날짜 경계·과거 사건 재질문·계획/완료 구분·미응답 질문·반복 거절·인용된 욕설·요약 경계 직후의 정정이다. 정상 경로와 historyIncomplete·요약 중지 경로를 별도로 채점한다. 문장 일치율만 사용하지 말고 사실 보존과 질문의 적절성을 사람이 검수한다.

비용은 turn + inner-thought + summary + closing/title repair + 재시도·관측된 실패 후 과금을 합산한다. OpenRouter의 request별 prompt/completion/cached tokens·cost·generation ID를 평가 도구에서 기록한다. cost가 없거나 조회되지 않은 요청은 누락으로 표시하고 추정액과 구분한다. 단가표를 새로운 DB에 저장하지 않는다. pronunciation 키·STT·TTS는 이번 LLM 비교에서 제외한다.

서버 관측 필드는 workflow·context policy·summary revision·전달 메시지 수·토큰 추정·usage·elapsedMs·fallback reason·작업 상태로 제한한다. prompt·원문·번역·요약 본문·API key는 로그나 Sentry에 남기지 않는다. request별 provider usage와 workflow 연결이 필요하면 공통 LLM 진입점에 비민감 집계 이벤트만 추가하고 새 대시보드·과금 테이블은 만들지 않는다.

출시 전 확인할 목표는 다음과 같다.

- 30왕복 이상 세션에서 대화·속마음 입력 토큰 합계 50% 이상, 요약을 포함한 총 실제 비용 20% 이상 절감. 미달하면 수치를 달성했다고 쓰지 않고 주기·윈도우를 재검토한다.
- 짧고 예산 이내인 세션에 요약 호출 0회. 요약 때문에 일반 응답 경로가 추가 대기하지 않음.
- 정의한 핵심 품질 회귀 세트에서 정정·부정·시제·종료 판단의 신규 치명적 오류 0건. 전체 운영 무오류 보장으로 확대 해석하지 않음.
- 같은 조건에서 응답 지연·실패율이 유의미하게 악화되지 않음. 작은 표본으로 p95 개선을 단정하지 않음.
- mock 테스트, 실제 LLM 결과, 로컬 통합, CI, 운영 배포, 실제 사용자 결과를 각각 구분해 보고.

## 11. 배포·되돌리기와 남은 확인 항목

develop 통합 검증 → 운영 AI 호환 버전 → BE 추가 스키마·기능 OFF → 내부 계정의 새 세션만 활성화 → 비용·품질 확인 후 확대 순서다. 실제 push·PR·머지·배포·운영 설정 변경은 이 설계 문서 작성에 포함하지 않는다.

문제 발생 시 BE master flag를 끄고 다음 요청부터 전체 원문 경로로 돌아간다. 원문·요약 테이블을 삭제하거나 역마이그레이션하지 않는다. AI 버전까지 되돌려야 한다면 먼저 BE 신규 필드 전송과 요약 등록을 중지하고 진행 중 새 계약 요청이 끝난 것을 확인한다. 오래된 AI가 새 필드를 무시할 것이라고 가정하지 않는다.

구현 시작 때 코드로 확정할 항목은 tokenizer 버전·인코딩, BE 기준 브랜치의 실제 파일 위치, migration 번호, 탈퇴/소프트 삭제 연결 지점이다. 출시 전에 실험으로 확정할 항목은 8/12왕복·800/8,000토큰·요약 deadline·동시 실행 한도와 FE 입력 길이 오류 처리다. 이 선택들이 바뀌면 이유와 검증 결과를 이 문서에 기록한다.

남는 한계는 반복 요약의 정보 손실, 제한된 맥락에서의 과거 회상 품질, provider 취소 이후 과금 가능성, 비동기 작업의 best-effort 실행이다. 장기기억 원문 검수와 별개로 세션 요약도 실제 모델 품질 검증이 필요하다.

## 12. 리뷰 보완과 검증 결과

2026-09-20, `feat/LAN-531`에서 리뷰의 8개 결함을 보완했다. 아래가 현재 구현 동작이며, 실제 모델 실측을 요구하는 출시 기준은 여전히 별도다.

- 정책이 없는 AI 요청은 기존 전체 이력 경로를 유지한다. `v1` 요청만 system·user·응답 schema의 JSON과 512토큰 여유분을 계산한다. 초과하면 오래된 완료 구간부터 제외하고 요약 전체를 버리며 `historyIncomplete=true`로 표시한다. 2026-09-22 변경 후에는 직전 AI·현재 USER 원문도 들어가지 않으면 최소 원문으로 생성을 계속한다. 일반 대화·속마음·종료 및 repair 계약을 검사하며 원본 요청 객체는 변경하지 않는다.
- BE는 실제 `messageSequence`를 내부 값으로 보존하고 AI JSON에는 보내지 않는다. 한 예약에서 조회한 요약 snapshot을 대화·속마음·종료에 함께 사용한다. 요약 조회도 예약 보상 범위에 포함하며 두 입력 초과 오류를 400으로 매핑한다.
- 요약은 미요약 완료 왕복 12개 또는 해당 구간의 JSON 12,000바이트를 기준으로 시작하고 최근 8왕복을 보존한다. 첫 인사·종료 확인 대기 USER는 완료 왕복으로 세지 않는다. 6,000바이트는 원문 구간 선택의 초기 목표다. 최소 왕복 하나가 이를 넘으면 그 왕복 전체를 한 번 보내 AI가 판정한다. AI가 입력 초과를 반환하면 실제 전송 구간을 기준으로 다음 시도를 줄이고, 최소 왕복도 실패하면 `OVERSIZED_UNIT`으로 자동 요약을 중지한다. 일반 대화는 AI의 원문 보존 축소 경로로 계속할 수 있다.
- 적용 여부는 새 세션 생성 트랜잭션에서 고정한다. worker는 기존 세션의 요약 행을 뒤늦게 생성하지 않는다. 저장 시 활성 사용자·프리톡·학습 세션을 잠그고 policy·revision·경계·선점 토큰·만료를 다시 검사한다. 선점 시각은 `Instant`와 PostgreSQL `clock_timestamp()`를 사용해 트랜잭션 시작 시각 및 서버 시간대의 영향을 피한다.
- 요약 실행기는 동시 2개·대기 8개로 분리했다. 포화 시 작업을 거부하며 호출자에서 실행하지 않는다. Executor 타입의 bean을 추가하지 않아 기존 `applicationTaskExecutor` 자동 구성이 유지된다. 일반 AI timeout과 요약 전용 timeout은 분리된 상태다.
- 세션의 물리 삭제는 FK cascade로 요약을 함께 제거한다. 탈퇴·중단·완료 후에는 새 요약을 저장하지 않는다. 탈퇴 시 원문 세션을 보존하는 기존 흐름을 이번 작업에서 변경하지 않는다.

검증은 합성 입력과 mock provider로 수행한다. AI 전체 unittest와 선택 필드의 OpenAPI 호환성을 확인했다. BE의 회귀 테스트·Spotless·Checkstyle 및 전체 `check`를 수행했다. 로컬 HTTP 서버에서 요약 timeout, 일반 대화 대기 시간, 400 오류 전달을 확인했다. 전용 로컬 PostgreSQL에서 요약 migration 적용·Instant 왕복·트랜잭션 중 전진하는 DB 시각·동시 행 잠금·FK cascade를 검증했다.

PostgreSQL 검증은 임시 클러스터의 `127.0.0.1:55431/postgres`, 사용자 `landit_test`, 스키마 `lan531`만 사용한다. 클러스터를 준비한 뒤 `LAN531_TEST_POSTGRES=true ./gradlew test --tests '*FreeTalkContextPostgresTests'`로 실행한다. 플래그가 없으면 해당 테스트는 스킵된다. 운영 연결 설정이나 사용자 원문을 읽지 않는다.

입력 토큰 수는 `tiktoken==0.12.0`의 `o200k_base`로 system·user·schema를 직렬화해 계산하고 512토큰 여유분을 더한다. 실제 `usage.prompt_tokens` 대조, 반복 요약의 실제 LLM 품질 및 총 비용 비교는 수행하지 않았다. 따라서 테스트 통과를 운영 품질이나 비용 절감의 입증으로 사용하지 않는다. 기능의 운영 활성화·push·PR·배포는 이번 리뷰 보완에 포함하지 않는다.

## 기준 브랜치와 migration 번호 확인 (2026-09-20)

- 원격 조회 기준 AI는 `origin/develop`의 `f247bfe`, BE는 `5346aae7f`에서 시작했다. 양쪽 모두 최신 develop 커밋을 포함한다.
- BE의 열린 PR 전체(#202, #203, #204, #205)의 변경 파일을 확인했다. #202와 #203에는 migration 변경이 없다. [#204](https://github.com/Aragornnnnnn/landit-be/pull/204)가 V112를, 그 위에 쌓인 [#205](https://github.com/Aragornnnnnn/landit-be/pull/205)가 V113을 추가한다. 현재 develop의 마지막 버전은 V111이다.
- LAN-531의 미배포 migration을 `V114__add_free_talk_context_summary.sql`로 옮기고 PostgreSQL 테스트 참조를 함께 변경했다. SQL 내용은 그대로다. 공용+PostgreSQL, 공용+H2 각각에 열린 PR의 추가 파일을 합쳐 버전 중복이 없음을 확인했다.
- #204의 V112 → #205의 V113 → LAN-531의 V114 순으로 병합·적용한다. 병합 직전에 develop과 열린 PR 전체의 버전 점유를 다시 확인한다. 이번 확인에서는 운영 DB migration 이력을 조회하거나 변경하지 않았다.
- V114 기준 `LAN531_TEST_POSTGRES=true ./gradlew --offline clean check --console=plain`을 통과했다. 전체 1,378개, 실패·오류 0개, 환경 조건 skip 9개이며 PostgreSQL 검증 3개가 포함된다. 최초 PostgreSQL 테스트의 연결 실패는 임시 서버를 테스트 포트(55431)로 재시작한 뒤 해소했다.

## PR 리뷰 반영 (2026-09-21)

- `FREE_TALK_SUMMARY_TIMEOUT_SECONDS`는 양의 유한값만 허용한다. `inf`·`-inf`·`nan`·0·음수는 설정 검증에서 거부한다.
- 요약 원문의 마지막 sequence는 `targetThroughSequence`와 같아야 한다. 이전 요약이 없으면 revision과 covered 경계가 모두 0이어야 하고, 이전 요약이 있으면 둘 다 양수여야 한다.
- 토크나이저 매핑은 `openai/gpt-5.4-mini`와 `openai/gpt-5.4-mini-20260317`의 `o200k_base`로 한정한다. [공식 tiktoken 매핑](https://github.com/openai/tiktoken/blob/0.12.0/tiktoken/model.py)에 따른 GPT-5 인코딩이다. 임의 모델에는 같은 인코딩을 추정 적용하지 않는다.
- 미지원 또는 미설정 모델에서는 `v1` 대화·속마음·종료 및 요약 요청이 외부 호출 전에 `AI_GENERATION_FAILED`로 거부된다. 정책 필드가 없는 기존 대화 요청은 영향을 받지 않는다. 이미 BE에서 축소한 원문을 AI가 복원할 수 없으므로 입력 예산 검사를 조용히 생략하지 않는다. 모델 변경 전에 매핑을 검증하고 추가해야 한다.
- 인코딩 데이터는 Docker 빌드 및 CI 테스트 준비 단계에서 받는다. 로컬 테스트도 의존성 설치 후 `python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'`로 준비한다. 사용자 원문·요약 캐시가 아닌 고정 토크나이저 데이터다.
- 로컬 토큰 계산은 provider의 내부 framing·schema 변환까지 정확히 재현한 청구량이 아니다. 실제 usage 비교와 LLM 품질·비용 평가는 여전히 출시 전 별도 검증이다.

검증: AI 전체 unittest 557개(실패 0, skip 7), OpenAPI 생성과 요약 경로 확인, 네트워크 다운로드를 차단한 별도 프로세스에서 인코딩 로딩 성공. BE 전체 `./gradlew --offline check`는 1,378개(실패 0, skip 12)와 Spotless·Checkstyle 통과. BE의 변경된 13개 파일은 주석·공백을 제외한 Java 코드가 동일함을 확인했다. 이번에는 PostgreSQL 전용 3개 테스트를 실행하지 않았으며 앞선 검증과 구분한다. 로컬 Docker 실행 도구가 없어 이미지 빌드는 CI에서 확인한다.
