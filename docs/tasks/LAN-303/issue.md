# LAN-303 프리톡 표현 학습 — 대화 임베딩 API (DB 검색 알고리즘, 코사인 유사도)

Notion: [프리톡 표현 학습 - DB 검색 알고리즘 (코사인 유사도)](https://app.notion.com/p/DB-3abb272a32d8806093d8d85ff0d83756?pvs=21)

## 요구사항

BE가 프리톡 종료 후 벡터 유사도 검색에 사용할 쿼리 벡터를 얻기 위해 호출한다.
기존 `expression-recommendations`와 마찬가지로 완료된 세션당 1회 호출된다.

## 엔드포인트 (BE → AI)

```
POST /api/v1/free-talk/conversation-embeddings
```

### 요청

```json
{
  "sessionId": 123,
  "targetLocale": "EN",
  "baseLocale": "KR",
  "conversationHistory": [
    {
      "messageId": 1,
      "turnNumber": 1,
      "role": "AI",
      "content": "Do you like cooking?",
      "translatedContent": "요리하는 거 좋아해?"
    },
    {
      "messageId": 2,
      "turnNumber": 1,
      "role": "USER",
      "content": "That's easy for me. I cook every day.",
      "translatedContent": null
    }
  ]
}
```

- `conversationHistory` 구조는 기존 `expression-recommendations` 요청과 동일하다.

## AI 서버가 할 일

1. **추출**: 대화에서 학습 가치가 있는 사용자 발화 핵심 문장을 1~4개 추출한다.
   - 추출 대상은 USER 발화뿐이다. ASSISTANT 발화는 짧은 응답("Yeah, totally" 등)의
     의미를 해석하기 위한 맥락으로만 사용한다.
   - 짧은 맞장구는 직전 AI 발화의 문맥을 반영해 의미가 드러나는 형태로 정리해도 된다
     (예: "Yeah, totally" → "I totally agree that the exam was hard").
   - 추출한 excerpt는 대화의 학습 언어(targetLocale) 그대로 작성한다 (기반 언어로 요약 금지).
2. **임베딩**: 추출한 각 문장을 OpenRouter `openai/text-embedding-3-small`로 임베딩한다.
   - 모델 고정: 표현 측 임베딩(V52, LAN-291)과 같은 모델이어야 코사인 유사도가 성립한다.
   - 차원은 1,536이다.

### 응답

```json
{
  "success": true,
  "data": {
    "excerpts": [
      {
        "excerptText": "That's easy for me.",
        "embedding": [0.0123, -0.0456, ...]
      }
    ]
  },
  "error": null
}
```

- 공통 응답 래퍼(`success`/`data`/`error`)는 기존 계약과 동일하다.

## BE 측 검증 (위반 시 AI_RESPONSE_INVALID 처리)

- `excerpts`는 1~4건이어야 한다 (0건 불가 — 완료된 프리톡에는 사용자 발화가 항상 존재한다).
- 각 `excerptText`는 비어 있으면 안 된다.
- 각 `embedding`은 정확히 1,536개의 숫자여야 하며 null 성분이 없어야 한다.

## 오류

- AI 응답 계약 위반 시 502 + `AI_RESPONSE_INVALID` 코드 규약을 따른다.
- 제공자 호출 또는 생성 실패 시 503 + `AI_GENERATION_FAILED` 코드 규약을 따른다.
