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
- `goalCompletionStatus`

다음 메시지는 backend가 지정한 고정 질문을 포함해야 합니다. 모델은 이전 사용자 발화에 대한 짧은 맞장구를 붙일 수 있지만, 고정 질문의 영어와 한국어 번역이 응답에서 누락되면 응답 형식 오류로 처리합니다.

## `POST /api/v1/conversation/inner-thought`

시나리오와 전체 대화 히스토리를 맥락으로 참고하되, 마지막 사용자 발화에 대한 상대 역할의 사적인 반응만 생성합니다. `nextQuestion`은 받지 않습니다.

요청에는 `sessionId`, `submittedMessageId`, `submittedTurnNumber`, `scenario`, `conversationHistory`를 포함합니다.

- `conversationHistory`는 최소 1개이며 마지막 메시지는 요청 식별자와 일치하는 `USER` 메시지여야 합니다.
- OpenRouter는 `innerThought`, `innerThoughtType`만 생성합니다.
- 응답의 `sessionId`는 요청의 `sessionId`, `messageId`는 요청의 `submittedMessageId`입니다.
- 속마음은 한국어로 생성하며 `innerThoughtType`은 `GOOD`, `NORMAL`, `BAD` 중 하나입니다.
- 문법 평가, 학습 피드백, 다음 질문, 이후 행동 계획을 속마음에 포함하지 않습니다.
- 같은 요청을 부수 효과 없이 재호출할 수 있지만 동일한 문구를 보장하지 않습니다.
- 상태 저장, 중복 호출 방지, 최초 성공 결과 확정, polling은 Landit backend 책임입니다.
- 종료 턴은 기존 `closing-message`를 사용하며 이 API를 별도로 호출하지 않습니다.

## `POST /api/v1/conversation/closing-message`

시나리오 종료 사유, 목표 달성 상태, 대화 히스토리를 사용해 마지막 AI 메시지를 생성합니다. 마지막 사용자 발화와 상대 역할, 직전 상황 안에서 끝내며, 대화 종료 자체를 선언하는 메타 문구는 응답 형식 오류로 처리합니다.

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
- 의미가 명확하고 평가 컨텍스트에 맞는 구어체는 더 부드럽거나 격식 있는 대안이 있다는 이유만으로 개선 대상으로 분류하지 않습니다.

응답에는 다음 필드를 포함합니다.

- `sessionId`
- `messageId`
- `feedbackStatus`: `PREPARING`, `COMPLETED`, `FAILED`

저장되는 피드백은 `GOOD`, `NEEDS_IMPROVEMENT` 조건부 필드 정책을 지켜야 합니다.

- `GOOD`이면 `feedbackDetail`을 채우고 개선 필드는 `null`로 둡니다.
- `NEEDS_IMPROVEMENT`이면 개선 표현과 이유를 채우고 `feedbackDetail`은 `null`로 둡니다.
- 한 메시지에서 개선 표현은 최대 1개만 생성합니다.
- 이 API에서는 속마음을 반환하지 않습니다.

`benchmarkMessage`는 GOOD 피드백의 짧은 학습 성취 문구입니다. LLM이 `detectedPatterns`로 반환한 내부 근거가 catalog 항목, `status=correct`, `gamifiable=true`, 실제 사용자 발화의 `evidence` 조건을 모두 만족하면 catalog의 `feedback_copy`를 문장형으로 바꾼 문구로 대체합니다. catalog는 SayNow의 `error_patterns.json` 원본을 그대로 사용합니다. catalog 근거가 없으면 LLM 문구를 유지하되, 퍼센트·비율·횟수 통계·출처 주장은 기본 비정량 문구로 대체합니다. `NEEDS_IMPROVEMENT`의 `benchmarkMessage`는 항상 `null`입니다.

`detectedPatterns`는 AI 서버 내부의 benchmark 검증에만 사용하며, message-feedback과 session-feedback 응답 및 OpenAPI 스키마에는 노출하지 않습니다. 현재 catalog에는 SayNow 원본 12개 패턴이 있으며, 출처 표기는 원본 값을 그대로 유지합니다.

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

`nativeScore`는 0에서 100 사이 정수입니다. 메시지별 내부 평가 근거를 다음 기준으로 점수화한 뒤 평균을 반올림합니다.

- `contextFit`: 평가 맥락 충족도이며 0~2점, 전체 점수의 40%입니다.
- `clarity`: 의미 명확성이며 0~2점, 전체 점수의 30%입니다.
- `languageAccuracy`: 문법, 어휘, 뉘앙스, 공손함의 정확성이며 0~2점, 전체 점수의 30%입니다.
- 메시지 점수는 `contextFit * 20 + clarity * 15 + languageAccuracy * 15`로 계산하고 최솟값을 50점으로 제한합니다.
- 세 항목이 모두 2점이면 `GOOD`, 하나라도 2점보다 낮으면 `NEEDS_IMPROVEMENT`입니다.
- 발화 길이, 문장 복잡도, 고급 어휘 자체는 점수를 높이지 않습니다. 상황에 가장 적합한 답변이라면 짧은 발화도 100점을 받을 수 있습니다.

평가 근거는 AI 서버의 단기 cache에만 저장합니다. `message-feedback`, `session-feedback` 응답과 OpenAPI 스키마에는 노출하지 않으므로 backend DTO와 DB schema 변경은 필요하지 않습니다.

`starRating`은 JSON number로 반환하며 다음 매핑을 사용합니다.

| nativeScore | starRating |
| --- | --- |
| 0~54 | 1.0 |
| 55~64 | 1.5 |
| 65~74 | 2.0 |
| 75~89 | 2.5 |
| 90~100 | 3.0 |

세션에 발화가 3개 이상이고 `GOOD` 비율이 1/3 이하이면, 모든 발화가 개선 필요인데 높은 별점이 표시되지 않도록 `starRating`을 최대 2.0으로 제한합니다. 이 제한은 `nativeScore`를 바꾸지 않으며, 발화가 1개 또는 2개인 세션에는 적용하지 않습니다.
