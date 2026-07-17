# LAN-174 설계

## 결정.

- `message-feedback`는 후보 생성이나 문구 검수에 실패해도 HTTP 오류로 끝내지 않고 `202`와 `feedbackStatus: FAILED`를 반환한다.
- `FAILED` 응답에는 캐시 가능한 메시지별 피드백을 저장하지 않는다.
- 유효한 후보가 있으면 기존처럼 `PREPARING`을 반환한다.

## LAN-169 포함 결정.

- 비어 있지 않은 JSON 응답의 누락 필드, 알 수 없는 열거값, 추가 필드, 마무리 문구 정책 위반은 API별 안전한 기본값으로 복구한다.
- `next-message`는 고정 질문과 `PARTIAL` 상태를 보완한다.
- `inner-thought`는 유효한 문구와 LLM이 준 `innerThoughtType`을 우선 사용하고, 없거나 잘못되면 `NORMAL`과 중립 문구를 사용한다.
- `closing-message`는 두 언어 문구가 모두 없거나 정책을 위반하면 `Okay.`와 `알겠어.`로 교체한다.
- `session-feedback`는 요청의 세션 ID와 안전한 요약 문구를 사용한다.
- `message-feedback`의 `baseLocaleAnalogy`는 인용·한국어 문구 형식을 강제하지 않고 비어 있지 않은 값만 허용한다.
- JSON 자체가 없거나 비어 있으면 재시도하지 않는다. `next-message`, `inner-thought`, `closing-message`, `session-feedback`은 `503`을 반환하고 캐시를 유지한다. `message-feedback`은 `202 FAILED`를 반환한다.
