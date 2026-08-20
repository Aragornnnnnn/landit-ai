# LAN-334 프리톡 종료 제목 생성 설계

## 목표

사용자 선시작 프리톡의 제목을 첫 사용자 턴이 아니라 대화 종료 시 전체 대화를 기준으로 생성한다. 제목 생성 실패는 마무리 메시지와 세션 종료를 실패시키지 않는다.

## 계약

- 일반 `/api/v1/free-talk/turn`은 제목을 생성하거나 검증하지 않고 `inferredTitle`을 항상 `null`로 반환한다.
- `/api/v1/free-talk/closing` 요청은 `titleGenerationRequired`를 선택적으로 받으며 기본값은 `false`다.
- BE는 `startMode == USER_FIRST && title == null`인 종료 요청에만 `titleGenerationRequired=true`를 보낸다.
- `/api/v1/free-talk/closing` 응답은 `inferredTitle`을 선택적으로 반환한다.
- 제목은 trim 후 1~30자이고 한글 또는 영문자를 최소 한 자 포함한다. 허용 문자는 한글, 영문, 숫자, 공백, `·`, `-`다.
- 최초 제목이 유효하지 않으면 유효한 마무리 메시지는 유지하고 제목만 한 번 다시 생성한다.
- 제목 repair 호출 또는 결과가 실패하면 AI는 `inferredTitle=null`을 반환한다.
- BE는 제목 생성 대상인데 응답 제목이 없으면 `{캐릭터 표시명}와의 대화`를 저장한다.
- 추천 주제 세션은 기존 제목을 유지하고 제목 생성 및 fallback 대상에서 제외한다.

## 데이터 흐름

1. BE가 사용자 발화를 예약하며 세션의 시작 방식과 제목 유무로 제목 생성 필요 여부를 계산한다.
2. 일반 턴에서는 제목 플래그를 보내지 않고 기존 `isFirstUserTurn` 호환 필드는 `false`로 보낸다.
3. 시간 제한 또는 사용자 종료 확정 시 BE가 closing 요청에 `titleGenerationRequired`를 포함한다.
4. AI는 한 번의 closing 호출에서 마무리 메시지와 선택적 제목을 생성한다.
5. 마무리 메시지가 유효하지 않으면 기존처럼 `AI_RESPONSE_INVALID`를 반환한다.
6. 제목만 유효하지 않으면 제목 전용 repair를 한 번 호출한다. repair 실패는 `null` 제목으로 축소한다.
7. BE는 생성 제목 또는 캐릭터 기반 fallback을 세션 완료 트랜잭션에서 저장한다.

## 호환성과 배포

- 새 AI는 `titleGenerationRequired`의 기본값을 `false`로 두므로 구버전 BE 요청을 수용한다.
- 새 BE 요청의 필드는 구버전 AI의 `extra=forbid` 계약에 거부되므로 AI를 먼저 배포한다.
- 새 BE는 closing 응답에 `inferredTitle`이 없더라도 fallback을 저장하므로 배포 중 응답 누락을 허용한다.

## 검증

- AI unittest로 일반 턴 제목 미생성, 한글·영문 제목 허용, 추천 주제 미생성, 제목 1회 repair, repair 실패 시 `null`, 마무리 메시지 오류 유지, OpenAPI 계약을 검증한다.
- BE 단위·통합 테스트로 요청 플래그, 생성 제목 저장, fallback 저장, 추천 주제 제목 보존, 시간 제한과 사용자 종료 경로를 검증한다.
- AI 전체 unittest와 BE Gradle 전체 테스트를 실행한다.
