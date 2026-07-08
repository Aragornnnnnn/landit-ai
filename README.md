# Landit AI Server

Landit의 LLM 기반 생성 책임을 맡는 Python 3.12, FastAPI 기반 AI 서버입니다.

이 서버는 가능한 한 stateless로 유지합니다. 세션, 턴, DB 저장, 완료 상태는 Landit backend가 책임지고, AI 서버는 요청에 포함된 컨텍스트를 바탕으로 응답을 생성해 반환합니다.

## 현재 API

- `GET /health`
- `POST /api/v1/conversation/next-message`
- `POST /api/v1/conversation/closing-message`
- `POST /api/v1/conversation/message-feedback`

상세한 API 책임과 응답 정책은 [conversation API 문서](docs/api/conversation.md)를 확인합니다.

## 문서

- [아키텍처](docs/architecture.md)
- [개발 환경과 검증](docs/development.md)
- [conversation API](docs/api/conversation.md)

## 빠른 시작

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/uvicorn app.main:app --reload
```

## 테스트

```bash
.venv/bin/python -m unittest discover -s tests
```

기본 앱 이름은 `landit-ai`이고, OpenAPI 문서 제목에도 이 값이 사용됩니다. 로컬 실행은 `.env` 없이도 가능하지만, OpenRouter client 생성은 `OPENROUTER_API_KEY`가 있어야 합니다.
