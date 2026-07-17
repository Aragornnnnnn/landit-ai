# AGENTS.md

Landit AI Server에서 Codex와 다른 코딩 에이전트가 지켜야 할 저장소 규칙입니다. 전역 지침과 함께 적용하되, 이 파일의 프로젝트 규칙을 우선 확인합니다.

## Project Context

- 이 저장소는 Python 3.12, FastAPI 기반 AI 서버입니다.
- 서비스 이름은 Landit입니다. 패키지와 앱 이름의 `landit-ai` 외에 문서와 설명에서 기존 서비스명이나 임시 이름을 새로 쓰지 않습니다.
- 패키지와 의존성 관리는 `pyproject.toml`을 기준으로 합니다.
- DTO 검증과 환경변수 설정 관리는 Pydantic v2와 Pydantic Settings를 사용합니다.
- LLM 호출은 OpenAI Python SDK를 사용하고, 현재 provider는 OpenRouter입니다.
- 실행 서버는 Uvicorn을 사용합니다.
- 에러 추적은 Sentry SDK를 사용합니다.
- 테스트는 Python 표준 `unittest`를 사용합니다.
- API 문서화는 FastAPI의 OpenAPI 스키마를 기준으로 합니다.
- 현재 public API는 `GET /health`뿐입니다.

## Workflow

- 사람용 협업 규칙은 `CONTRIBUTING.md`를 따릅니다.
- 작업을 시작할 때는 반드시 Notion 이슈 번호가 필요합니다.
- 브랜치 생성 전 Notion 이슈 번호를 확인합니다.
- 개발자가 위 작업을 시작할 때 이슈 번호가 없거나 현재 브랜치가 작업 브랜치가 아니라면, 에이전트는 개발자에게 이슈 번호를 먼저 요청합니다.
- 이슈 번호가 확인되기 전에는 기능 구현, 리팩터링, API 변경, DB 변경, 배포 작업을 시작하지 않습니다.
- 작업 문서가 필요하면 `docs/tasks/{ISSUE_NUMBER}/` 아래에 둡니다.
- 요구사항이 모호하거나 설계 결정이 필요한 작업은 `design.md`에 승인된 설계를 기록합니다.
- 구현이 여러 단계이거나 인수인계용 계획이 필요한 작업은 `plan.md`에 구현 순서, 발견 사항, 설계 변경, 검증 결과를 기록합니다.
- 승인된 `design.md` 또는 `plan.md`를 단일 기준 문서로 사용하고 같은 내용을 별도 작업 문서에 중복하지 않습니다.
- 단순하거나 범위가 명확한 작업은 별도 작업 문서를 만들지 않습니다.
- 기존 `checklist.md`와 `context-notes.md`는 과거 기록으로만 유지하고 새 작업에는 만들지 않습니다.
- 병렬 브랜치 충돌을 줄이기 위해 하나의 작업은 자기 이슈 디렉터리 안의 파일만 갱신합니다.
- 사용자가 이슈 번호 없이 `origin/develop` 직접 작업을 명시하면 이슈 번호 규칙의 예외로 처리합니다. 작업 문서가 필요하면 `docs/tasks/direct-{YYYY-MM-DD}-{short-slug}/`를 사용합니다.
- 문서 작업도 실제 파일과 현재 코드 구조를 확인한 뒤 진행합니다.

## Branch Rules

- 모든 개발 브랜치는 `feat/{이슈 번호}` 형식을 사용합니다.
- 예시: `feat/LAN-10`.
- 일반 버그 수정은 `fix/{이슈 번호}`를 사용합니다.
- `release/v{MAJOR}.{MINOR}.{PATCH}`는 `develop`에서 생성하고 검증 후 `main`으로 병합합니다.
- 긴급 수정만 `hotfix/{이슈 번호}`를 사용합니다.
- `hotfix/{이슈 번호}`는 `main`에서 생성하고 배포 후 `develop`과 진행 중인 `release/*`에 반영합니다.
- 배포가 끝난 `release/*` 브랜치는 재사용하지 않습니다.
- 현재 브랜치가 없거나 `feat/{이슈 번호}`, `fix/{이슈 번호}`, `release/v{버전}`, `hotfix/{이슈 번호}` 형식이 아니라면 작업을 시작하기 전에 사용자에게 이슈 번호를 요청합니다.
- 기본 작업 흐름은 `feat/*`에서 작업 후 `develop`으로 병합하는 것입니다.

## Release Automation

- 프로덕션 배포는 `main`에서 수동 workflow에 `MAJOR.MINOR.PATCH` 버전을 입력해 실행합니다.
- 릴리즈 브랜치를 생성하기 전, 배포 예정 `MAJOR.MINOR.PATCH` 버전이 명시되지 않았다면 사용자에게 먼저 확인합니다.
- 릴리즈 브랜치는 확인된 버전으로 `release/v{MAJOR}.{MINOR}.{PATCH}` 형식을 사용합니다.
- 정식 릴리즈의 프로덕션 배포 workflow에는 해당 릴리즈 브랜치와 같은 버전을 입력합니다.
- hotfix는 마지막 배포 태그를 기준으로 다음 PATCH 버전을 에이전트가 제안하고, 프로덕션 배포 실행 시 그 버전을 입력합니다.
- 배포가 성공하면 workflow가 `ai-v{버전}` annotated tag와 GitHub Release를 생성합니다.
- workflow 실행은 태그와 GitHub Release 생성까지 포함한 승인입니다.
- 이미 존재하는 태그, 태그 삭제나 이동, 롤백, MAJOR 또는 MINOR 버전 결정은 사람에게 확인합니다.

## AI Server Code Convention

- Python 코드는 PEP 8을 기준으로 합니다.
- 와일드카드 import를 사용하지 않습니다.
- 새 소스 파일의 첫 줄은 파일 역할을 설명하는 한국어 한 줄 주석으로 시작합니다.
- 함수와 클래스 설명이 필요할 때는 Python docstring을 사용합니다.
- 함수 내부의 짧은 보조 설명은 `#`를 사용합니다.
- 이름은 길어져도 역할이 분명하게 작성합니다.
- 하나의 함수는 하나의 책임만 갖도록 작성합니다.
- 함수가 20줄을 넘거나 파라미터가 4개를 넘으면 분리 가능성을 먼저 검토합니다.
- DTO 검증은 Pydantic v2 모델을 우선 사용합니다.
- 환경변수 설정은 Pydantic Settings를 우선 사용합니다.
- LLM 호출 코드는 OpenAI SDK 클라이언트 생성과 실제 요청 로직을 분리합니다.
- public API 변경은 테스트와 FastAPI OpenAPI 스키마 변경 여부를 함께 확인합니다.
- 시크릿 값은 로그, 테스트 출력, 문서, 커밋 메시지에 노출하지 않습니다.

## Architecture Direction

- Landit AI Server는 stateless FastAPI 서버, 모듈러 모놀리스, 가벼운 헥사고날 구조를 기준으로 확장합니다.
- Landit backend가 세션, 턴, DB 저장, 완료 상태를 책임집니다.
- AI 서버는 `next-question`, `turn-feedback`, `session-feedback`, `guide` 같은 LLM 기반 생성 책임만 맡습니다.
- `api` 계층은 HTTP 요청/응답, DTO 검증, 상태 코드만 처리합니다.
- `conversation/application` 계층은 use case 실행을 담당합니다.
- `domain` rules는 피드백 규칙, 점수 계산, 안전 규칙처럼 외부 I/O가 없는 로직만 담습니다.
- `llm` 계층은 외부 모델 호출의 단일 진입점입니다.
- prompts, postprocess, scoring, JSON 파싱은 한 함수에 섞지 말고 필요한 만큼만 분리합니다.

## Dependency Direction

- 이미 설치된 FastAPI, Pydantic, Pydantic Settings, OpenAI SDK, Sentry SDK, Uvicorn을 우선 사용합니다.
- 새 의존성은 표준 라이브러리나 기존 의존성으로 해결할 수 없고, 실제 코드가 바로 필요할 때만 추가합니다.
- LangChain, Redis, Celery, AI 서버 전용 DB는 기본 선택지가 아닙니다.
- interface, port, repository 추상화는 구현체가 하나뿐이면 만들지 않습니다.
- 공통화는 중복이 실제로 생긴 뒤에 합니다.

## Stateless And Boundary Rules

- 요청 처리 중 필요한 컨텍스트는 요청 DTO로 받습니다.
- 사용자 세션, 대화 턴, 완료 상태, 장기 저장 데이터는 AI 서버 메모리나 파일에 저장하지 않습니다.
- 상태 저장이나 조회가 필요하면 Landit backend API 계약을 먼저 정합니다.
- 전역 mutable 상태, in-memory session store, 로컬 파일 캐시는 기본으로 추가하지 않습니다.
- 헬스체크처럼 상태가 필요 없는 API는 단순한 함수로 유지합니다.

## LLM Call Rules

- OpenAI SDK client 생성과 실제 LLM 요청 로직을 분리합니다.
- 외부 모델 호출은 llm 계층의 단일 진입점을 통해 호출합니다.
- prompt 작성, 모델 응답 JSON 파싱, 후처리, 점수 계산을 한 함수에 몰아넣지 않습니다.
- 모델명, base URL, API key는 Pydantic Settings로 읽습니다.
- API key가 없거나 비어 있으면 호출 직전에 명확히 실패시킵니다.
- 테스트에서 실제 LLM 네트워크 호출을 만들지 않습니다.

## Testing And Verification

- 코드 변경 후 최소 검증 명령은 `.venv/bin/python -m unittest discover -s tests`입니다.
- 테스트를 실행하지 못했다면 이유를 최종 응답에 명확히 적습니다.
- 테스트 실패 시 실제 에러와 스택트레이스를 읽고 원인을 확인한 뒤 수정합니다.
- 시크릿이 필요한 테스트는 실제 값을 출력하지 말고 설정 여부나 guarded equality만 검증합니다.
- 문서만 변경한 경우에는 테스트 대신 변경 파일과 Git diff를 검토합니다.
- public API 변경은 unittest와 FastAPI OpenAPI 스키마 변경 여부를 함께 확인합니다.
- LLM 호출 코드는 성공 경로보다 설정 누락, 잘못된 provider, blank secret 같은 경계 조건을 먼저 검증합니다.

## Security And Logging

- secret 값은 로그, 예외 메시지, 테스트 출력, 문서, 커밋 메시지에 남기지 않습니다.
- Sentry에는 secret, raw prompt 전문, 사용자 민감정보를 보내지 않습니다.
- 에러 로그는 원인 추적에 필요한 request id, endpoint, provider, model 같은 비민감 메타데이터 중심으로 남깁니다.
- `.env`는 로컬 설정 파일로만 쓰고 저장소에 커밋하지 않습니다.

## Do Not Add By Default

- LangChain orchestration.
- Redis, Celery, queue worker.
- AI 서버가 직접 소유하는 DB schema.
- 구현체가 하나뿐인 interface, port, repository.
- 요청되지 않은 admin API, dashboard, background job.
- Landit backend가 이미 책임지는 세션, 턴, 완료 상태 저장 로직.

## Commit Convention

- 커밋 메시지는 `{type}: 커밋 메시지` 형식을 사용합니다.
- 메시지는 한국어로 "무엇을" 바꿨는지와 "왜/어떻게" 바꿨는지를 드러냅니다.
- 단순한 `버그 수정`, `기능 추가`, `초기 설정`처럼 의미가 약한 메시지는 피합니다.
- 커밋 1개는 하나의 논리 변경만 담습니다.
- 가능하면 커밋 1개는 30줄 내외로 유지합니다.
- 논리 단위로 작게 커밋하고, PR은 리뷰 가능한 크기로 유지합니다.
- 타입이 애매하면 커밋하기 전에 사용자에게 확인합니다.

사용 가능한 type은 다음과 같습니다.

- `feat`: 새로운 기능 추가
- `fix`: 버그 수정
- `refactor`: 동작은 그대로, 코드 구조나 가독성 개선
- `docs`: 문서 수정
- `comment`: 주석 추가 및 변경
- `chore`: 빌드, 패키지 매니저, 환경 설정, 의존성 추가
- `deploy`: 빌드 및 배포 작업
- `test`: 테스트 코드 추가 및 수정
- `rename`: 파일 또는 폴더명 변경
- `remove`: 파일 삭제만 한 경우

좋은 예시는 다음과 같습니다.

```text
feat: 사용자 프로필 조회 API 추가
fix: 만료된 토큰 요청이 500 대신 401을 반환하도록 수정
test: 회원가입 요청 DTO 검증 테스트 추가
chore: PostgreSQL 드라이버와 Flyway 의존성 추가
```

## PR Rules

- PR 제목은 연결된 이슈 제목을 그대로 사용합니다.
- PR은 5~10분 안에 리뷰 가능한 크기로 유지합니다.
- 코드 추가 변경은 가능하면 500줄 이하로 유지합니다.
- 변경이 커지면 기능 단위로 PR을 분리합니다.
- 리뷰어가 바로 이해할 수 있도록 변경 이유, 주요 구현, 검증 결과를 PR 본문에 적습니다.
- 설명이 필요한 코드 흐름은 작성자가 PR에 먼저 코멘트를 남깁니다.

## Review Comment Style

- 코멘트 표현은 `바꿔주세요`, `고려해주세요`처럼 행동이 분명한 문장으로 씁니다.
