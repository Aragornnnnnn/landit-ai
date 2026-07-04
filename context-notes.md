# Context Notes

## 2026-06-28

- 저장소는 `LICENSE`만 있는 초기 상태였다.
- 패키징은 별도 도구 강제 없이 표준 `pyproject.toml` 기반으로 시작한다.
- 테스트는 요청 스펙에 맞춰 `unittest`만 사용한다. FastAPI `TestClient`는 추가 의존성인 `httpx`가 필요할 수 있어 초기 설정 범위에서 제외했다.
- OpenAI SDK는 실제 네트워크 호출 없이 클라이언트 생성 지점만 둔다. API 키가 없으면 명시적으로 실패시켜 설정 누락을 빨리 드러낸다.
- Sentry는 `SENTRY_DSN`이 있을 때만 초기화한다. 로컬 기본 실행에서 외부 전송을 만들지 않기 위함이다.
- 이 환경은 `python` 명령이 없고 `python3.12` 명령만 확인되었다. 검증 명령은 `python3.12 -m unittest discover -s tests`로 맞춘다.
- FastAPI 0.138.1에서는 `app.routes`에 `path` 속성이 없는 내부 라우터 객체가 포함된다. 라우트 등록 검증은 공개 스키마인 `app.openapi()["paths"]` 기준으로 한다.
- `.venv/bin/python -m unittest discover -s tests` 기준으로 설정 기본값, `/health` 등록, 헬스체크 반환값, OpenAI API 키 누락 가드를 검증한다.
- BE AGENTS.md를 AI 저장소에 맞게 옮길 때는 `Project Context`와 `Backend Code Convention`의 내용만 AI 서버 기준으로 바꾸고, 나머지 공통 개발 규칙은 원문 그대로 유지한다.
- 이번 작업은 사용자 지시로 Notion 이슈 번호 없이 진행한다. 대신 `origin/develop` 기준 `feat/llm-config` 브랜치에서 작업한다.
- 현재 저장소는 SSM 직접 조회 패턴이 없고, Pydantic Settings가 환경변수와 `.env`를 읽는 구조다. OpenRouter 관련 SSM 값을 애플리케이션이 직접 읽지 않고 배포/IaC 단계에서 env var로 주입하는 전제로 둔다.
- OpenRouter 설정은 `LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`을 읽는다. API key는 `SecretStr`로 받고 테스트에는 fake placeholder만 사용한다.
- `.env.example`의 빈 `OPENROUTER_API_KEY`가 유효한 키처럼 통과하지 않도록 클라이언트 생성 시 빈 문자열과 공백 문자열을 누락으로 처리한다.
- 남은 결정 사항은 배포/IaC 단계에서 `/landit/develop`과 `/landit/prod` SSM 값을 어떤 런타임 env 주입 방식으로 연결할지, 실제 `OPENROUTER_MODEL` 값을 환경별로 무엇으로 둘지다.
- LAN-43 dev Worker 배포 workflow는 새 배포 프레임워크 없이 GitHub Actions, Dockerfile, ECR push, ECS `update-service --force-new-deployment`만 둔다. task definition 재등록과 Terraform 실행은 하지 않는다.
- 로컬 환경에는 Docker CLI가 없어 Docker build 검증은 실행하지 못했다. `.venv/bin/python -m unittest discover -s tests`는 통과했다.
