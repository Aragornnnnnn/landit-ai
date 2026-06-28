# OpenRouter Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Landit AI 서버가 OpenRouter 기반 LLM 설정을 환경변수에서 읽고, API key 값을 저장소와 로그에 남기지 않도록 준비한다.

**Architecture:** 현재 저장소에는 SSM 직접 조회 패턴이 없으므로 애플리케이션은 Pydantic Settings로 env var만 읽는다. SSM Parameter Store의 `/landit/{environment}/...` 값을 런타임 env로 주입하는 일은 배포/IaC 단계의 책임으로 남긴다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Pydantic Settings, OpenAI Python SDK, unittest.

## Global Constraints

- AWS profile: `landit`.
- AWS region: `ap-northeast-2`.
- develop path: `/landit/develop`.
- production path: `/landit/prod`.
- AI에서 사용할 SSM parameter는 `/landit/{environment}/OPENROUTER_API_KEY`, `/landit/{environment}/LLM_PROVIDER`, `/landit/{environment}/OPENROUTER_BASE_URL`, `/landit/{environment}/OPENROUTER_MODEL`이다.
- API key 값은 repo, 로그, 테스트 출력, 문서에 절대 남기지 않는다.
- SSM 값을 직접 출력하지 않는다.
- 기존에 SSM을 직접 읽는 패턴이 없으면 애플리케이션은 env var를 읽도록 구성하고 SSM -> env 주입은 배포/IaC 단계에서 처리한다.
- provider는 OpenRouter 기준으로 설정하되, 모델명과 base URL은 env var로 바꿀 수 있게 둔다.
- local/develop/prod 설정을 구분하되, 아키텍처나 배포 방식은 임의로 확정하지 않는다.

---

## File Structure

- `app/core/config.py`: `LLM_PROVIDER`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL` 설정 필드 추가.
- `app/core/openai_client.py`: OpenAI SDK 클라이언트를 OpenRouter base URL과 API key로 생성.
- `tests/test_app.py`: 설정 기본값, env var 로딩, API key 누락 가드 검증.
- `.env.example`: secret 없는 OpenRouter placeholder 추가.
- `context-notes.md`: SSM 직접 조회를 넣지 않는 결정 기록.
- `checklist.md`: 작업 진행 상태 기록.

### Task 1: Settings Contract

**Files:**
- Modify: `tests/test_app.py`
- Modify: `app/core/config.py`

**Interfaces:**
- Consumes: Pydantic Settings env var loading.
- Produces: `Settings.llm_provider`, `Settings.openrouter_api_key`, `Settings.openrouter_base_url`, `Settings.openrouter_model`.

- [ ] **Step 1: Write the failing tests**

```python
class SettingsTests(unittest.TestCase):
    def test_default_settings_use_local_environment(self):
        settings = Settings()

        self.assertEqual(settings.app_name, "landit-ai")
        self.assertEqual(settings.app_env, "local")
        self.assertEqual(settings.llm_provider, "openrouter")
        self.assertEqual(settings.openrouter_base_url, "https://openrouter.ai/api/v1")
        self.assertIsNone(settings.openrouter_api_key)
        self.assertIsNone(settings.openrouter_model)
        self.assertIsNone(settings.sentry_dsn)

    def test_settings_read_openrouter_environment_variables(self):
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-openrouter-key",
                "OPENROUTER_BASE_URL": "https://openrouter.example/v1",
                "OPENROUTER_MODEL": "openrouter-test-model",
            },
        ):
            settings = Settings()

        self.assertEqual(settings.llm_provider, "openrouter")
        self.assertEqual(settings.openrouter_api_key.get_secret_value(), "test-openrouter-key")
        self.assertEqual(settings.openrouter_base_url, "https://openrouter.example/v1")
        self.assertEqual(settings.openrouter_model, "openrouter-test-model")
```

- [ ] **Step 2: Run test to verify RED**

Run: `.venv/bin/python -m unittest tests.test_app.SettingsTests -v`
Expected: FAIL because `Settings` does not expose OpenRouter fields yet.

- [ ] **Step 3: Implement settings fields**

Add the four OpenRouter fields to `Settings`. Use `SecretStr | None` for the key and keep the default provider as `openrouter`.

- [ ] **Step 4: Run test to verify GREEN**

Run: `.venv/bin/python -m unittest tests.test_app.SettingsTests -v`
Expected: PASS.

### Task 2: OpenRouter Client Guard

**Files:**
- Modify: `tests/test_app.py`
- Modify: `app/core/openai_client.py`

**Interfaces:**
- Consumes: `Settings.openrouter_api_key`, `Settings.openrouter_base_url`, `Settings.llm_provider`.
- Produces: `create_openai_client(settings: Settings | None = None) -> OpenAI`.

- [ ] **Step 1: Write the failing tests**

```python
class OpenAIClientTests(unittest.TestCase):
    def test_create_openai_client_requires_openrouter_api_key(self):
        settings = Settings(openrouter_api_key=None)

        with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
            create_openai_client(settings)

    def test_create_openai_client_rejects_blank_openrouter_api_key(self):
        settings = Settings(openrouter_api_key="")

        with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
            create_openai_client(settings)

    def test_create_openai_client_requires_openrouter_provider(self):
        settings = Settings(
            llm_provider="other",
            openrouter_api_key="test-openrouter-key",
        )

        with self.assertRaisesRegex(RuntimeError, "LLM_PROVIDER"):
            create_openai_client(settings)

    def test_create_openai_client_uses_openrouter_base_url(self):
        settings = Settings(
            openrouter_api_key="test-openrouter-key",
            openrouter_base_url="https://openrouter.example/v1",
        )

        client = create_openai_client(settings)

        self.assertEqual(str(client.base_url), "https://openrouter.example/v1/")
```

- [ ] **Step 2: Run test to verify RED**

Run: `.venv/bin/python -m unittest tests.test_app.OpenAIClientTests -v`
Expected: FAIL because the client still expects `OPENAI_API_KEY` and does not use OpenRouter base URL.

- [ ] **Step 3: Implement client changes**

Use `OPENROUTER_API_KEY`, reject blank keys, enforce `LLM_PROVIDER=openrouter`, and pass `base_url=settings.openrouter_base_url` into `OpenAI`.

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: PASS.

### Task 3: Env Example And Documentation Notes

**Files:**
- Modify: `.env.example`
- Modify: `context-notes.md`
- Modify: `checklist.md`

**Interfaces:**
- Consumes: settings contract from Tasks 1 and 2.
- Produces: secret-free local environment example.

- [ ] **Step 1: Update `.env.example`**

Use placeholder values only. Do not include a real API key or SSM value.

- [ ] **Step 2: Run all tests**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: PASS.

- [ ] **Step 3: Inspect diff**

Run: `git diff --stat`
Expected: only config, tests, env example, plan, checklist, and context notes are changed.
