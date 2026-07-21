# LAN-192 AI 로그 레벨 보존 설계

## 목표.

- `logger.warning()`과 `logger.error()`가 가진 실제 로그 레벨을 CloudWatch 원문에 보존한다.
- 메시지 본문의 `error` 문자열 때문에 경고 로그가 장애 로그로 분류되는 오탐을 제거한다.
- 기존 로그 호출부와 메시지 피드백 처리 동작은 변경하지 않는다.

## 확인된 원인.

AI 컨테이너는 Uvicorn으로 실행되며 애플리케이션 로거의 루트 핸들러가 명시적으로 구성되지 않았다. 이 상태에서는 경고 메시지가 출력되어도 레벨과 로거 이름이 CloudWatch 원문에 포함되지 않을 수 있다. Grafana가 전체 메시지에서 `error`, `exception`, `traceback` 같은 문자열을 검색하면서 `reason=... Value error`인 `WARNING` 로그도 오류 패널에 표시됐다.

BE는 Spring Boot 기본 콘솔 appender를 사용하며 기본 패턴이 실제 로그 레벨을 이미 출력한다. 따라서 BE 애플리케이션 변경은 필요하지 않다.

## 최종 설계.

- AI 루트 로거와 Uvicorn 로거를 하나의 출력 경로로 통합한다.
- 루트 레벨은 `WARNING`으로 유지하고 Uvicorn 로거만 `INFO`로 설정해 제3자 라이브러리의 요청 URL을 새로 수집하지 않는다.
- 출력 형식은 `level=%(levelname)s logger=%(name)s message=%(message)s`로 고정한다.
- 기존 `logger.warning()`, `logger.error()`, `logger.exception()` 호출은 그대로 유지한다.
- Grafana AI 오류 조회는 `logfmt`로 `level`을 파싱해 `ERROR`와 `CRITICAL`만 선택한다.
- Grafana BE 오류 조회는 Spring Boot 콘솔 행의 레벨 위치를 파싱한다.

## 검증 기준.

- 본문에 `Value error`가 포함된 경고 로그가 `level=WARNING`으로 출력된다.
- 실제 오류 로그가 `level=ERROR`로 출력된다.
- Uvicorn 오류와 access 로그도 같은 형식을 사용한다.
- `httpx` 같은 제3자 로거의 `INFO` 메시지는 활성화되지 않는다.
- 전체 unittest가 통과한다.

## 제외 범위.

- 기존 로그 호출부의 레벨을 변경하지 않는다.
- 사용자 원문이나 모델 응답을 새로 기록하지 않는다.
- BE 로깅 설정을 변경하지 않는다.
