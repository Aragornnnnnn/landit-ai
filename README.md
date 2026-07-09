# Landit AI Server

Landit의 LLM 기반 생성 책임을 맡는 Python 3.12, FastAPI 기반 AI 서버입니다.

이 서버는 가능한 한 stateless로 유지합니다. 세션, 턴, DB 저장, 완료 상태는 Landit backend가 책임지고, AI 서버는 요청에 포함된 컨텍스트를 바탕으로 응답을 생성해 반환합니다.

## 역할

- Landit의 `next-message`, `turn-feedback`, `session-feedback`, `guide` 같은 LLM 기반 생성 기능을 담당합니다.
- HTTP 요청/응답 경계, 입력 DTO 검증, 상태 코드는 FastAPI API 계층에서 처리합니다.
- 대화 흐름의 use case는 `conversation/application` 계층으로 확장합니다.
- 피드백 규칙, 점수 계산, 안전 규칙처럼 외부 I/O가 없는 로직은 domain rules로 분리합니다.
- 외부 모델 호출은 llm 계층의 단일 진입점에서 처리합니다.
- prompts, postprocess, scoring, JSON 파싱은 섞지 않고 분리합니다.

현재 구현된 public API는 `GET /health`와 `POST /api/v1/conversation/next-message`입니다. 나머지 생성 API들은 앞으로 이 서버가 맡을 책임 방향이며, 아직 구현된 엔드포인트가 아닙니다.

## 아키텍처 방향

Landit AI Server는 stateless FastAPI 서버, 모듈러 모놀리스, 가벼운 헥사고날 구조를 기준으로 확장합니다.

- `api`는 HTTP 요청/응답과 상태 코드만 다룹니다.
- `conversation/application`은 하나의 사용 사례를 실행합니다.
- `domain`은 외부 I/O 없는 규칙과 계산을 담습니다.
- `llm`은 OpenAI 호환 LLM 호출의 단일 진입점입니다. 현재 provider는 OpenRouter입니다.
- `prompts`, `postprocess`, `scoring`, JSON 파싱은 각각 독립된 모듈로 둡니다.

처음부터 과한 Clean Architecture, LangChain, Redis, Celery, AI 서버 전용 DB, 불필요한 interface/port/repository 추상화를 기본값으로 두지 않습니다. 필요성이 코드와 운영 요구로 확인될 때만 추가합니다.

## 디렉터리 구조

```text
app/
  main.py              FastAPI 앱 생성과 라우터 등록
  api/
    conversation.py    POST /api/v1/conversation/next-message 라우터
    health.py          GET /health 라우터
  conversation/
    application/
      next_message_service.py  다음 AI 메시지 생성 use case
  models/
    conversation.py    대화 생성 API DTO
  core/
    config.py          Pydantic Settings 기반 환경변수 설정
    openai_client.py   OpenAI SDK 클라이언트 생성
    sentry.py          Sentry 초기화
tests/
  test_app.py          설정, 앱 생성, 헬스체크, OpenAI client 검증
  test_conversation_api.py  다음 AI 메시지 생성 API 검증
```

아직 `domain`, `llm`, `prompts`, `postprocess`, `scoring` 패키지는 없습니다. 생성 API를 확장할 때 위 아키텍처 방향에 맞춰 필요한 패키지만 추가합니다.

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
```

환경변수 예시는 `.env.example`을 기준으로 설정합니다. `OPENROUTER_API_KEY` 같은 secret 값은 저장소에 커밋하지 않습니다.

## Test

```bash
.venv/bin/python -m unittest discover -s tests
```

문서만 변경한 경우에도 변경 파일을 다시 읽고 `git diff`로 실제 diff를 확인합니다.

## Run

```bash
.venv/bin/uvicorn app.main:app --reload
```

기본 앱 이름은 `landit-ai`이고, OpenAPI 문서 제목에도 이 값이 사용됩니다. 로컬 실행은 `.env` 없이도 가능하지만, OpenRouter client 생성은 `OPENROUTER_API_KEY`가 있어야 합니다.

## API 책임

- `GET /health`는 서버 프로세스가 살아 있고 FastAPI 라우터가 등록되었는지 확인합니다.
- `POST /api/v1/conversation/next-message`는 시나리오 컨텍스트, 대화 히스토리, backend가 지정한 다음 고정 질문을 사용해 다음 AI 메시지, 번역, 상대 역할의 속마음, 목표 달성 상태를 생성합니다.
- 생성 API는 Landit backend가 전달한 입력만 사용해 결과를 반환해야 합니다.
- 생성 API 성공 응답은 `{"success": true, "data": ..., "error": null}` 형태로 반환합니다.
- 생성 API 실패 응답은 `{"success": false, "data": null, "error": {"code": "...", "message": "..."}}` 형태로 반환합니다.
- AI 응답 필드가 누락되거나 형식이 맞지 않으면 `AI_RESPONSE_INVALID` 502를 반환합니다.
- AI 호출 자체가 실패하면 `AI_GENERATION_FAILED` 503을 반환합니다.
- AI 서버는 세션 상태, 턴 저장, 완료 여부, 사용자별 장기 상태를 직접 저장하지 않습니다.
- 저장과 상태 전환은 Landit backend 책임으로 둡니다.

## 운영 원칙

- 런타임 설정은 Pydantic Settings와 환경변수로 주입합니다.
- OpenRouter 호출은 OpenAI Python SDK client를 통해 수행합니다.
- `SENTRY_DSN`이 없으면 Sentry를 초기화하지 않습니다.
- secret 값은 로그, 테스트 출력, 문서, 커밋 메시지에 남기지 않습니다.
- Docker 이미지는 `Dockerfile`로 빌드하고, GitHub Actions workflow는 수동 `workflow_dispatch` 배포를 기준으로 합니다.
- 배포 workflow는 이미지를 ECR에 push한 뒤 ECS service를 `force-new-deployment`로 갱신합니다.
