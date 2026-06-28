# AI 서버 초기 앱 동작을 검증하는 unittest 모듈
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
