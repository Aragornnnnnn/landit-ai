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
