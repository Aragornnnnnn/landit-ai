# LAN-174 설계

## 결정.

- `message-feedback`는 후보 생성이나 문구 검수에 실패해도 HTTP 오류로 끝내지 않고 `202`와 `feedbackStatus: FAILED`를 반환한다.
- `FAILED` 응답에는 캐시 가능한 메시지별 피드백을 저장하지 않는다.
- 유효한 후보가 있으면 기존처럼 `PREPARING`을 반환한다.
- 이 변경은 메시지별 피드백 처리 상태 계약만 대상으로 한다.
