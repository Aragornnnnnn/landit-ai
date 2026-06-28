# AI Server Initial Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python 3.12 기반 FastAPI AI 서버의 최소 실행 골격, 설정 관리, Sentry 초기화 지점, OpenAI SDK 클라이언트 생성 지점, unittest 검증을 만든다.

**Architecture:** 앱 진입점은 `app/main.py`의 `create_app()`에서 생성한다. 환경 설정은 `app/core/config.py`의 Pydantic Settings 객체가 담당하고, 외부 연동 초기화는 `app/core/`에 분리한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Pydantic Settings, OpenAI Python SDK, Uvicorn, Sentry SDK, unittest.

## Global Constraints

- 언어: Python 3.12.
- 프레임워크: FastAPI.
- DTO 검증과 환경변수 설정 관리는 Pydantic v2와 Pydantic Settings를 사용한다.
- LLM 호출 준비는 OpenAI Python SDK를 사용한다.
- 실행 서버는 Uvicorn을 사용한다.
- 에러 추적 초기화 지점은 Sentry SDK를 사용한다.
- 테스트는 unittest를 사용한다.
- 새 소스 파일 첫 줄에는 해당 파일의 역할을 설명하는 한 줄 한국어 주석을 둔다.

---

## File Structure

- `pyproject.toml`: Python 버전과 런타임 의존성 선언.
- `.env.example`: 필요한 환경변수 예시.
- `.gitignore`: Python 개발 산출물 제외.
- `README.md`: 설치, 테스트, 실행 명령.
- `app/main.py`: FastAPI 앱 팩토리와 Uvicorn 대상 앱.
- `app/api/health.py`: 헬스체크 라우터.
- `app/core/config.py`: Pydantic Settings 기반 환경 설정.
- `app/core/sentry.py`: Sentry 초기화 함수.
- `app/core/openai_client.py`: OpenAI SDK 클라이언트 생성 함수.
- `tests/test_app.py`: unittest 기반 설정, 라우팅, OpenAI 클라이언트 가드 검증.
- `checklist.md`: 진행 체크리스트.
- `context-notes.md`: 작업 중 결정과 이유.

### Task 1: Project Metadata And Tests

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `README.md`
- Create: `tests/test_app.py`
- Create: `checklist.md`
- Create: `context-notes.md`

**Interfaces:**
- Consumes: 없음.
- Produces: `python -m unittest discover -s tests` 검증 명령과 앱 코드가 만족해야 할 기대 동작.

- [ ] **Step 1: Write the failing test**

```python
import unittest

from app.api.health import health_check
from app.core.config import Settings
from app.core.openai_client import create_openai_client
from app.main import create_app


class SettingsTests(unittest.TestCase):
    def test_default_settings_use_local_environment(self):
        settings = Settings()

        self.assertEqual(settings.app_name, "landit-ai")
        self.assertEqual(settings.app_env, "local")
        self.assertIsNone(settings.sentry_dsn)


class AppFactoryTests(unittest.TestCase):
    def test_create_app_registers_health_endpoint(self):
        app = create_app(Settings())

        paths = app.openapi()["paths"]

        self.assertIn("/health", paths)

    def test_health_check_returns_ok_status(self):
        self.assertEqual(health_check(), {"status": "ok"})


class OpenAIClientTests(unittest.TestCase):
    def test_create_openai_client_requires_api_key(self):
        settings = Settings(openai_api_key=None)

        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            create_openai_client(settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.12 -m unittest discover -s tests`
Expected: FAIL or ERROR because `app.api.health`, `app.core.config`, `app.core.openai_client`, and `app.main` do not exist yet.

### Task 2: Minimal FastAPI Application

**Files:**
- Create: `app/__init__.py`
- Create: `app/api/__init__.py`
- Create: `app/api/health.py`
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Create: `app/core/sentry.py`
- Create: `app/core/openai_client.py`
- Create: `app/main.py`

**Interfaces:**
- Consumes: tests in `tests/test_app.py`.
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`, `health_check() -> dict[str, str]`, `create_openai_client(settings: Settings | None = None) -> OpenAI`.

- [ ] **Step 1: Write minimal implementation**

Create the package modules listed above. Keep behavior limited to settings defaults, `/health` route registration, Sentry initialization only when DSN exists, and OpenAI client creation only when `OPENAI_API_KEY` exists.

- [ ] **Step 2: Run tests**

Run: `python3.12 -m unittest discover -s tests`
Expected: PASS.

### Task 3: Final Verification

**Files:**
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Consumes: all project files.
- Produces: verified final state.

- [ ] **Step 1: Run package import smoke test**

Run: `python3.12 -m unittest discover -s tests`
Expected: PASS.

- [ ] **Step 2: Inspect git diff**

Run: `git diff --stat`
Expected: only initial setup files are changed.
