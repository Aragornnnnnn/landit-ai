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
  "extractorVersion": "memory-candidate-v1",
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
추출하도록 한다. 인사, 단순 동의, 일회성 요청, 학습 예문, 비밀·자격 증명·금융
식별자와 근거 없는 진단·성격·관계·의도 추론은 제외한다. 후보 문장은 base locale로
작성하고 미래 계획의 날짜와 발화 시각을 보존한다.

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

`ADD`는 독립된 사실, `SUPERSEDE`는 기존 사실을 교체하는 경우, `IGNORE`는 중복·
일시적 발화·근거 부족에 사용한다. `SUPERSEDE`만 비어 있지 않은
`supersededMemoryIds`를 가질 수 있다.
