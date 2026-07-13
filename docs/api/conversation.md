# Conversation API

Conversation API는 Landit backend가 전달한 시나리오와 대화 컨텍스트를 바탕으로 LLM 기반 생성 결과를 반환합니다.

## 공통 정책

- 생성 API는 Landit backend가 전달한 입력만 사용해 결과를 반환합니다.
- 생성 API 성공 응답은 `{"success": true, "data": ..., "error": null}` 형태로 반환합니다.
- 생성 API 실패 응답은 `{"success": false, "data": null, "error": {"code": "...", "message": "..."}}` 형태로 반환합니다.
- AI 응답 필드가 누락되거나 형식이 맞지 않으면 `AI_RESPONSE_INVALID` 502를 반환합니다.
- AI 호출 자체가 실패하면 `AI_GENERATION_FAILED` 503을 반환합니다.
- 캐시된 메시지별 피드백이 아직 준비되지 않았으면 `MESSAGE_FEEDBACK_NOT_READY` 409를 반환합니다.
- AI 서버는 세션 상태, 턴 저장, 완료 여부, 사용자별 장기 상태를 직접 저장하지 않습니다.
- 저장과 상태 전환은 Landit backend 책임으로 둡니다.

## `POST /api/v1/conversation/next-message`

시나리오 컨텍스트, 대화 히스토리, backend가 지정한 다음 고정 질문을 사용해 다음 AI 메시지를 생성합니다.

응답에는 다음 필드를 포함합니다.

- `aiMessage`
- `translatedMessage`
- `innerThought`
- `innerThoughtType`
- `goalCompletionStatus`

다음 메시지는 backend가 지정한 고정 질문을 포함해야 합니다. 모델은 이전 사용자 발화에 대한 짧은 맞장구를 붙일 수 있지만, 고정 질문의 영어와 한국어 번역이 응답에서 누락되면 응답 형식 오류로 처리합니다.

## `POST /api/v1/conversation/closing-message`

시나리오 종료 사유, 목표 달성 상태, 대화 히스토리를 사용해 마지막 AI 메시지를 생성합니다.

응답에는 다음 필드를 포함합니다.

- `aiMessage`
- `translatedMessage`
- `innerThought`
- `innerThoughtType`

마지막 메시지는 새 꼬리 질문이 되면 안 됩니다. `aiMessage`와 `translatedMessage`가 물음표로 끝나거나 새 질문처럼 작성되면 응답 정책 위반으로 처리합니다.

## `POST /api/v1/conversation/message-feedback`

사용자 메시지 1개의 피드백을 생성하고 TTL 있는 in-memory cache에 저장한 뒤 202 `PREPARING`을 반환합니다. 직전 AI 메시지에 대한 답변과 USER First 시나리오의 첫 사용자 발화를 모두 처리합니다.

요청은 평가 기준이 되는 `evaluationContext`와 평가 대상인 `userMessage`를 분리해 전달합니다. 기존 `messageContext`는 사용하지 않습니다.

`evaluationContext.type`은 다음 값을 지원합니다.

- `AI_MESSAGE`: 직전 AI 메시지에 대한 답변을 평가합니다.
- `SCENARIO_OPENING_INSTRUCTION`: 시나리오 시작 안내에 따른 USER First 첫 발화를 평가합니다.

`evaluationContext`에는 `content`와 선택 필드인 `translatedContent`를 포함합니다. `SCENARIO_OPENING_INSTRUCTION`은 `turnNumber`가 1이어야 하며, 안내 문구 자체가 기준 locale이므로 `translatedContent`는 `null`이어야 합니다.

`messageSequence`는 세션 전체 메시지 순번입니다. AI 서버는 양수 여부만 검증하며, 평가 컨텍스트 type 판별이나 type별 고정 순번 검증에는 사용하지 않습니다.

평가 기준은 type에 따라 다음과 같이 달라집니다.

- `AI_MESSAGE`는 직전 AI 메시지의 이해와 답변 관련성을 평가합니다.
- `SCENARIO_OPENING_INSTRUCTION`은 시작 안내 수행 여부, 시작 표현의 자연스러움, 상황 적절성, 상대 역할에 맞는 공손함을 평가합니다. AI 질문에 대한 답변 관련성은 평가하지 않습니다.
- 두 type 모두 문법, 어휘, 자연스러움, 의미 전달력, 상대 역할에 맞는 뉘앙스를 평가합니다.

응답에는 다음 필드를 포함합니다.

- `sessionId`
- `messageId`
- `feedbackStatus`: `PREPARING`, `COMPLETED`, `FAILED`

저장되는 피드백은 `GOOD`, `NEEDS_IMPROVEMENT` 조건부 필드 정책을 지켜야 합니다.

- `GOOD`이면 `feedbackDetail`을 채우고 개선 필드는 `null`로 둡니다.
- `NEEDS_IMPROVEMENT`이면 개선 표현과 이유를 채우고 `feedbackDetail`은 `null`로 둡니다.
- 한 메시지에서 개선 표현은 최대 1개만 생성합니다.
- 이 API에서는 속마음을 반환하지 않습니다.

메시지별 피드백 cache는 추후 최종 피드백 생성을 위한 단기 in-memory cache이며, 장기 저장소가 아닙니다. 여러 서버 인스턴스가 같은 cache 결과를 공유해야 하거나 SQS 기반 비동기 처리가 들어오면 외부 저장소로 옮깁니다.

## `POST /api/v1/conversation/session-feedback`

AI 서버 캐시에 저장된 메시지별 피드백을 `expectedMessageIds` 기준으로 조회하고, 세션 최종 피드백을 반환합니다.

응답에는 다음 필드를 포함합니다.

- `sessionId`
- `nativeScore`
- `starRating`
- `highlightMessage`
- `summaryMessage`
- `messageFeedbacks`

`highlightMessage`와 `summaryMessage`는 LLM이 생성합니다. `nativeScore`와 `starRating`은 LLM이 생성하지 않고 AI 서버가 deterministic하게 계산합니다.

메시지별 피드백 준비 여부와 캐시 정책은 다음과 같습니다.

- `expectedMessageIds`는 빈 목록, 0 이하 값, 중복 값을 허용하지 않습니다.
- `messageFeedbacks`는 `expectedMessageIds` 순서대로 반환합니다.
- `expectedMessageIds` 중 캐시에 없는 메시지가 하나라도 있으면 409를 반환합니다.
- 409 응답에는 누락된 메시지 ID를 외부 필드로 포함하지 않습니다.
- 세션 최종 피드백 생성 성공 시 해당 세션의 메시지별 피드백 캐시를 삭제합니다.
- 피드백 미준비, LLM 응답 오류, LLM 호출 실패 시 재시도를 위해 캐시를 보존합니다.

`nativeScore`는 0에서 100 사이 정수입니다. 메시지별 피드백의 GOOD 개수로 기본 점수 밴드를 잡고, 사용자 발화 길이, 표현 시도, NEEDS_IMPROVEMENT 비율 등을 밴드 안에서 보정합니다.

`starRating`은 JSON number로 반환하며 다음 매핑을 사용합니다.

| nativeScore | starRating |
| --- | --- |
| 0~54 | 1.0 |
| 55~64 | 1.5 |
| 65~74 | 2.0 |
| 75~89 | 2.5 |
| 90~100 | 3.0 |
