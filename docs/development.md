# 개발 환경과 검증

이 문서는 로컬 개발과 검증에 필요한 명령만 다룹니다. 에이전트 작업 규칙과 커밋 규칙은 `AGENTS.md`를 확인합니다.

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
```

환경변수 예시는 `.env.example`을 기준으로 설정합니다. `OPENROUTER_API_KEY` 같은 secret 값은 저장소에 커밋하지 않습니다.

## Run

```bash
.venv/bin/uvicorn app.main:app --reload
```

로컬 실행은 `.env` 없이도 가능하지만, OpenRouter client 생성은 `OPENROUTER_API_KEY`가 있어야 합니다.

## Metrics

OpenTelemetry 메트릭은 기본적으로 비활성화되어 로컬 실행과 테스트에서 외부 전송을 만들지 않습니다. 배포 환경에서는 아래 값을 ECS 환경변수와 secret으로 주입합니다.

```text
OTEL_METRICS_ENABLED=true
OTEL_SERVICE_NAME=landit-ai
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=<Grafana Cloud OTLP base URL>
OTEL_EXPORTER_OTLP_HEADERS=<Grafana Cloud authorization header>
```

`OTEL_EXPORTER_OTLP_HEADERS`는 secret으로 관리하고 `.env`, 문서, 로그, Git에 값을 남기지 않습니다. 서비스 이름은 `OTEL_SERVICE_NAME`, namespace는 `landit`, 환경은 `APP_ENV` 값을 사용합니다.

HTTP 메트릭은 `/health`를 제외한 FastAPI route template, method, status만 수집합니다. route 미매칭 요청은 `http.route` label을 남기지 않습니다. query string, request/response body, header, 사용자·세션·메시지 ID는 수집하지 않습니다. Python runtime 메트릭은 process CPU·메모리·thread와 CPython GC 통계만 수집합니다.

## Test

```bash
.venv/bin/python -m unittest discover -s tests
```

코드를 변경했다면 위 테스트를 실행합니다. public API를 변경했다면 FastAPI OpenAPI 스키마 변경 여부도 함께 확인합니다.

문서만 변경한 경우에는 변경 파일을 다시 읽고 `git diff`로 실제 diff를 확인합니다.
