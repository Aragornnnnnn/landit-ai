# 발음 LLM 프로바이더 고정 라우팅을 검증하는 unittest 모듈 (LAN-389)
import unittest
from types import SimpleNamespace

from app.core.config import Settings
from app.pronunciation.llm.routing import llm_extra_body, served_by_fallback


def make_settings(**overrides):
    return Settings(_env_file=None, **overrides)


class LlmExtraBodyTests(unittest.TestCase):
    def test_default_pins_google_ai_studio_with_fallbacks(self):
        extra = llm_extra_body(make_settings())

        self.assertEqual(
            extra["provider"],
            {"order": ["google-ai-studio"], "allow_fallbacks": True},
        )
        self.assertEqual(extra["reasoning"], {"effort": "low"})

    def test_empty_order_disables_provider_pinning(self):
        extra = llm_extra_body(make_settings(pronunciation_provider_order=""))

        self.assertNotIn("provider", extra)

    def test_order_accepts_comma_separated_priorities(self):
        settings = make_settings(
            pronunciation_provider_order="google-ai-studio, google-vertex"
        )

        extra = llm_extra_body(settings)

        self.assertEqual(
            extra["provider"]["order"], ["google-ai-studio", "google-vertex"]
        )


class ServedByFallbackTests(unittest.TestCase):
    def _response(self, provider):
        return SimpleNamespace(model_extra={"provider": provider})

    def test_preferred_provider_is_not_reported(self):
        self.assertIsNone(
            served_by_fallback(make_settings(), self._response("Google AI Studio"))
        )

    def test_fallback_provider_is_reported(self):
        # Vertex 서빙(표시명 "Google")은 STRESS 검출이 죽는 조용한 저하라 잡아야 한다
        self.assertEqual(
            served_by_fallback(make_settings(), self._response("Google")), "Google"
        )

    def test_response_without_provider_field_is_ignored(self):
        self.assertIsNone(served_by_fallback(make_settings(), SimpleNamespace()))

    def test_disabled_pinning_reports_nothing(self):
        settings = make_settings(pronunciation_provider_order="")

        self.assertIsNone(served_by_fallback(settings, self._response("Google")))


class AuxiliaryFallbackWarningTests(unittest.TestCase):
    """보조 호출 경로(억양 확인·묘사)도 폴백 서빙을 warning으로 관측한다.

    판정(compare)만 관측하면 보조 판정의 조용한 품질 저하를 놓친다 (코드래빗 지적).
    """

    def _client(self, content):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model_extra={"provider": "Google"},
        )
        completions = SimpleNamespace(create=lambda **kwargs: response)
        return SimpleNamespace(chat=SimpleNamespace(completions=completions))

    def test_accent_check_logs_fallback_serving(self):
        from app.pronunciation.llm import accent_check

        contrast = accent_check.AccentContrast(
            order=1, word="water", expected_option="a clear t", other_option="a flap"
        )
        with self.assertLogs(accent_check.logger.name, level="WARNING") as logs:
            accent_check.check_accent(
                self._client('{"answer": "A", "heard": "waw-tuh"}'),
                make_settings(),
                b"user-wav",
                contrast,
            )

        self.assertIn("Google", logs.output[0])

    def test_describe_logs_fallback_serving(self):
        from app.pronunciation.llm import describe

        with self.assertLogs(describe.logger.name, level="WARNING") as logs:
            describe.describe_error(
                self._client('{"userHeard": "hik·ing"}'),
                make_settings(),
                reference_wav=b"reference",
                user_wav=b"user",
                word="hiking",
                error_type="SOUND",
            )

        self.assertIn("Google", logs.output[0])


if __name__ == "__main__":
    unittest.main()
