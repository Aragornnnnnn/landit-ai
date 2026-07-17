# 아키텍처

Landit AI Server는 stateless FastAPI 서버, 모듈러 모놀리스, 가벼운 헥사고날 구조를 기준으로 확장합니다.

## 역할

- Landit의 `next-message`, `closing-message`, `turn-feedback`, `session-feedback`, `guide` 같은 LLM 기반 생성 기능을 담당합니다.
- HTTP 요청/응답 경계, 입력 DTO 검증, 상태 코드는 FastAPI API 계층에서 처리합니다.
- 대화 흐름의 use case는 `conversation/application` 계층으로 확장합니다.
- 피드백 규칙, 점수 계산, 안전 규칙처럼 외부 I/O가 없는 로직은 domain rules로 분리합니다.
- 외부 모델 호출은 llm 계층의 단일 진입점에서 처리합니다.
- prompts, postprocess, scoring, JSON 파싱은 섞지 않고 분리합니다.

나머지 생성 API들은 앞으로 이 서버가 맡을 책임 방향이며, 구현되기 전까지는 public API로 보지 않습니다.

## 계층 책임

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
    conversation.py    대화 생성 API 라우터
    health.py          GET /health 라우터
  conversation/
    application/
      next_message_service.py  다음 AI 메시지, 종료 메시지, 메시지별 피드백 생성 use case
  models/
    conversation.py    대화 생성 API DTO
  core/
    config.py          Pydantic Settings 기반 환경변수 설정
    openai_client.py   OpenAI SDK 클라이언트 생성
    sentry.py          Sentry 초기화
tests/
  test_app.py          설정, 앱 생성, 헬스체크, OpenAI client 검증
  test_conversation_api.py  대화 생성 API 검증
```

아직 `domain`, `llm`, `prompts`, `postprocess`, `scoring` 패키지는 없습니다. 생성 API를 확장할 때 위 아키텍처 방향에 맞춰 필요한 패키지만 추가합니다.

## 운영 원칙

- 런타임 설정은 Pydantic Settings와 환경변수로 주입합니다.
- OpenRouter 호출은 OpenAI Python SDK client를 통해 수행합니다.
- `SENTRY_DSN`이 없으면 Sentry를 초기화하지 않습니다.
- secret 값은 로그, 테스트 출력, 문서, 커밋 메시지에 남기지 않습니다.
- Docker 이미지는 `Dockerfile`로 빌드하고, GitHub Actions workflow는 수동 `workflow_dispatch` 배포를 기준으로 합니다.
- 프로덕션 배포 workflow는 `MAJOR.MINOR.PATCH` 버전을 입력받아 이미지를 ECR에 push하고 ECS service를 `force-new-deployment`로 갱신합니다.
- ECS service가 안정화된 뒤 workflow는 배포 커밋에 `ai-v{버전}` annotated tag와 GitHub Release를 생성합니다.
