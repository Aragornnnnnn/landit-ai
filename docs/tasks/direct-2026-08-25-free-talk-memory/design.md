# FreeTalk 장기기억 V1 안전 코어 설계

## 1. 결정

이 문서는 LAN-347-1의 AI 서버 계약을 정의한다. V1은 완료된 FreeTalk 세션에서
기억 후보를 추출하고, 후보와 기존 비교 기억의 상태를 `ADD`, `SUPERSEDE`,
`IGNORE`로 판정한다. 검색용 query embedding 계약은 LAN-347-4로 이관한다.

AI 서버는 stateless로 유지한다. 세션·메시지·기억을 저장하지 않고, DB·queue·새
dependency·단일 구현용 abstraction을 추가하지 않는다. 저장과 트랜잭션 적용은
Landit backend의 책임이다.

V1은 일반적인 장기기억만 다룬다. 민감도 분류 필드는 계약에 넣지 않으며, 민감한
기억 정책은 V2에서 별도 합의한다.

## 2. 범위와 책임

| 책임 | V1 AI 서버 | Landit backend |
| --- | --- | --- |
| 완료 세션 문맥 전달 | 요청 DTO 검증 | 세션·메시지 조회 |
| 후보 추출 | LLM 호출·구조 검증 | 저장 여부 결정 |
| 후보 embedding | `text-embedding-3-small` 호출·검증 | 저장·검색 |
| 상태 판정 | 비교 후보를 받은 뒤 LLM 호출·구조 검증 | 결과의 권한·트랜잭션 적용 |
| 기억 원문·상태·source 저장 | 하지 않음 | 수행 |

V1에서는 매 사용자 턴마다 별도 memory planner를 호출하거나 AI가 기억을 검색해
대화 prompt에 주입하지 않는다. 이 API들은 완료 세션 후 write pipeline과 backend의
명시적 검색 흐름에서만 호출한다.

## 3. API 계약

### 3.1 후보 추출

`POST /api/v1/free-talk/memory-candidates`

요청은 다음 필드를 가진다.

```json
{
  "sessionId": 300,
  "characterId": "chloe",
  "targetLocale": "EN",
  "baseLocale": "KR",
  "timezone": "Asia/Seoul",
  "conversationHistory": [
    {
      "messageId": 3002,
      "turnNumber": 1,
      "role": "USER",
      "content": "I have an interview next Friday.",
      "translatedContent": null,
      "occurredAt": "2026-08-25T20:10:00+09:00"
    }
  ]
}
```

응답은 `extractorVersion`과 0~5개의 후보를 반환한다.

```json
{
  "extractorVersion": "memory-candidate-v4",
  "candidates": [
    {
      "candidateIndex": 0,
      "memoryType": "EVENT",
      "content": "사용자는 2026년 8월 28일에 면접이 있다.",
      "contentLocale": "KR",
      "sourceMessageIds": [3002],
      "confidence": 0.94,
      "validFrom": "2026-08-25T20:10:00+09:00",
      "validTo": null,
      "embeddingModel": "openai/text-embedding-3-small",
      "embedding": [0.01]
    }
  ]
}
```

실제 embedding은 응답에서 정확히 1536개의 finite number여야 한다. 위 예시의
배열은 계약 설명을 위한 축약 표현이며 실제 응답에는 1536개가 들어간다.

LLM prompt는 USER 발화에서 장기적으로 유용한 `PROFILE`, `EVENT`, `EPISODE`만
추출하도록 한다. 안정적인 사용자 사실과 반복 습관은 `PROFILE`, 시간 의미가 있는
사건은 `EVENT`, 사용자와 현재 캐릭터가 함께 겪은 상호작용은 `EPISODE`로 분류한다.
후보 하나에는 독립적으로 갱신·무효화할 수 있는 사실 하나만 담는다. 같은 발화에
서로 독립적인 사실이 있으면 후보를 분리하되, 반복 습관에 함께한 참여자는 보존한다.
같은 선호의 원인·결과나 행동적 재진술은 별도 후보로 중복 생성하지 않는다.
상대 시간은 발화 시각과 timezone으로 해석하되, 명확하지 않으면 날짜를 추측하지
않는다. 인사, 단순 동의, 일회성 요청,
학습 예문, 비밀·자격 증명·금융 식별자와 근거 없는 진단·성격·관계·의도 추론은
제외한다. 시간 값은 timezone offset을 포함한 RFC 3339 형식으로 반환하며, 사실이
아니라고 명시된 인용·가정·역할극·학습 예문은 기억 후보로 만들지 않는다.

AI 응답 검증 후에는 명백한 오기억만 결정적으로 제거한다. 모호한 상대 요일을 근거로
만든 `EVENT`, 단순 재요청을 저장한 후보, 명시적으로 부정한 학습 예문, 상대
시간이 그대로 남은 후보가 대상이다. 제거 후 남은 후보는 0부터 다시 인덱싱하며,
누락된 후보를 규칙으로 새로 만들지는 않는다.

### 3.2 상태 판정

`POST /api/v1/free-talk/memory-resolution`

요청은 각 후보의 `candidateIndex`, `content`, `memoryType`,
`sourceMessageIds`, timezone-aware `observedAt`, 그리고 같은 사용자·scope·type의
비교 기억 최대 3개를 전달한다. 비교 기억은 `memoryId`, `content`, `validFrom`,
`validTo`, `observedAt`을 가진다.

```json
{
  "candidates": [
    {
      "candidateIndex": 0,
      "content": "사용자는 면접에 합격했다.",
      "memoryType": "EVENT",
      "sourceMessageIds": [3002],
      "observedAt": "2026-08-29T19:20:00+09:00",
      "comparableMemories": [
        {
          "memoryId": 77,
          "content": "사용자는 다음 주에 면접이 있다.",
          "validFrom": "2026-08-25T20:10:00+09:00",
          "validTo": null,
          "observedAt": "2026-08-25T20:10:00+09:00"
        }
      ]
    }
  ]
}
```

응답은 요청의 모든 후보를 정확히 한 번씩 포함한다.

```json
{
  "resolutions": [
    {
      "candidateIndex": 0,
      "operation": "SUPERSEDE",
      "supersededMemoryIds": [77]
    }
  ]
}
```

`ADD`는 독립된 사실, `SUPERSEDE`는 같은 사실을 더 구체적으로 갱신해 기존의
포괄적 기억이 중복되는 경우, `IGNORE`는 동등한 중복·일시적 발화·근거 부족에
사용한다. 같은 대상을 언급해도 별도로 변경될 수 있는 사실은 `ADD`로 유지한다.
`SUPERSEDE`만 비어 있지 않은
`supersededMemoryIds`를 가질 수 있다.

## 4. V1 안전 조건

### 요청·후보

- conversation history에는 USER 메시지가 하나 이상 있어야 한다.
- 후보는 0부터 시작하는 연속된 `candidateIndex`를 사용하고 최대 5개다.
- `sourceMessageIds`는 비어 있지 않고 양수이며 중복되지 않아야 한다.
- 모든 source ID는 요청 history에 존재하는 USER 메시지여야 한다. AI 메시지나 없는
  ID를 source로 허용하지 않는다.
- `contentLocale`은 요청의 `baseLocale`과 정확히 일치해야 한다.
- `timezone`은 지원되는 IANA timezone이어야 한다.
- 모든 `occurredAt`, `validFrom`, `validTo`, `observedAt`은 timezone offset을
  포함해야 한다.
- `validTo`가 있으면 `validFrom`보다 빠를 수 없다.
- `embeddingModel`은 `openai/text-embedding-3-small`로 고정하고, embedding은
  1536차원·finite number인지 검증한다.

### 상태 판정

- 요청 후보는 1~5개이며 후보 index는 요청 문맥 안에서 유일해야 한다.
- resolution은 요청 후보 index를 정확히 한 번씩 포함해야 한다.
- `SUPERSEDE` 대상 memory ID는 해당 후보의 `comparableMemories`에 있어야 한다.
- `ADD`와 `IGNORE`는 supersede ID를 가질 수 없다.
- 한 기존 memory ID를 여러 후보가 동시에 supersede할 수 없다.
- AI가 요청에 없던 후보 index나 memory ID를 반환하면 전체 결과를 거절한다.

검증 실패는 부분 결과를 저장하지 않도록 즉시 실패한다. DTO 검증 실패는 400,
LLM JSON 또는 후처리 계약 실패는 502 `AI_RESPONSE_INVALID`, provider·embedding
호출 실패는 503 `AI_GENERATION_FAILED`로 매핑한다.

## 5. LLM 호출과 실패 경계

후보 추출과 상태 판정은 각각 한 번의 JSON completion만 호출한다. JSON이 아니거나
필수 필드·타입·안전 조건을 만족하지 않으면 두 번째 LLM 호출 없이
`AiResponseInvalidError`로 fail closed 한다. V1은 잘못된 응답을 자동 repair하지
않으며, 해당 요청의 embedding도 진행하지 않는다.

## 6. 테스트와 관측

`tests/test_free_talk_api.py`는 두 API의 대표 성공·실패 경계를 검증한다.

- 후보 성공, 빈 후보, USER source·locale·시간·index·개수·embedding 경계.
- resolution 성공, 누락 resolution, 알 수 없는 memory, 잘못된 operation과
  cross-candidate supersede.
- malformed/missing JSON이 추가 completion 없이 502가 되는 fail-closed 경계.
- OpenAPI에 두 장기기억 route가 있고 후보 schema에 V1에 없는 민감도 필드가 없음을 확인한다.

실제 사용자 메시지, 후보 원문, prompt 전문, embedding과 secret은 로그나 Sentry에
남기지 않는다. 필요한 관측값은 endpoint, provider/model, 후보·비교·resolution
개수, 오류 코드 같은 비민감 메타데이터로 제한한다.

## 7. V2 경계

다음 항목은 V1 안전 코어를 검증한 뒤 별도 설계와 계약 변경으로 추가한다.

- query embedding endpoint·DTO·service는 LAN-347-4 AI 기억 컨텍스트 계약으로 이관한다.
- 민감한 기억의 분류·저장·검색 정책.
- 매 턴 memory retrieval, direct-topic gate, prompt 주입과 사용 trajectory.
- 잘못된 LLM JSON을 두 번째 호출로 자동 repair하는 자기 복구.
- feedback 기반 정책 학습, 품질 점수, memory use policy version.
- backend DB schema, source/history 보존, temporal invalidation과 transaction
  dispatcher.

V2가 추가되더라도 AI 서버의 stateless 경계와 fail-closed 기본값을 유지한다.
