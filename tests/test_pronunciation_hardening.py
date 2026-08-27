# LAN-373 적대적 리뷰 반영 사항을 고정하는 unittest 모듈
#
# 다섯 항목: 전체 wall-clock 예산, 참조 URL SSRF 차단, Sentry 유출 차단,
# accentContrast null 처리, 묘사 stressIndex 범위 검증.
import base64
import time
import unittest
import warnings
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import Settings
from app.core.sentry import init_sentry
from app.main import create_app
from app.models.pronunciation import (
    PronunciationAccentContrast,
    PronunciationAccentErrorType,
    PronunciationWordInput,
)
from app.pronunciation.alignment.forced_align import WordSpan
from app.pronunciation.application.analysis_service import (
    ReferenceAudioUnavailableError,
    _download_reference,
)
from app.pronunciation.audio import DecodedAudio
from app.pronunciation.llm.compare import (
    JudgedDifference,
    PronunciationJudgmentError,
    PronunciationJudgmentInvalidError,
    judge_pronunciation,
)
from app.pronunciation.llm.describe import ErrorDescription, describe_error

ALLOWED_ORIGIN = "https://d19azau1un4t7r.cloudfront.net"
USER_AUDIO_BASE64 = base64.b64encode(b"fake-audio-bytes").decode("ascii")

REQUEST_BODY = {
    "userAudio": USER_AUDIO_BASE64,
    "userAudioFormat": "m4a",
    "sentenceText": "There's nothing like.",
    "referenceAudioUrl": f"{ALLOWED_ORIGIN}/tts/1/EN_US/sentence.mp3",
    "accentLocale": "EN_US",
    "words": [
        {"order": 1, "word": "There's"},
        {"order": 2, "word": "nothing"},
        {"order": 3, "word": "like"},
    ],
}

SPANS = [
    WordSpan(word="There's", start_ms=90, end_ms=470),
    WordSpan(word="nothing", start_ms=480, end_ms=930),
    WordSpan(word="like", start_ms=940, end_ms=1200),
]

DECODED = DecodedAudio(
    judgment_wav=b"SECRET-JUDGMENT-BYTES",
    alignment_wav=b"SECRET-ALIGNMENT-BYTES",
    duration_seconds=2.0,
)


def make_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def make_client(settings=None):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated.*",
        )
        from fastapi.testclient import TestClient

        return TestClient(create_app(settings or make_settings()))


@contextmanager
def pipeline(
    judge_delay=0.0,
    differences=(),
    describe_result=None,
    describe_calls=None,
):
    service = "app.pronunciation.application.analysis_service"

    def fake_decode(data, audio_format, *args, **kwargs):
        return DECODED

    def fake_judge(url, wav, accent_locale, settings, *args, **kwargs):
        time.sleep(judge_delay)
        return list(differences), b"reference-wav"

    def fake_describe(*args, **kwargs):
        if describe_calls is not None:
            describe_calls.append(kwargs.get("word") or "called")
        return describe_result

    with (
        patch(f"{service}.decode_user_audio", side_effect=fake_decode),
        patch(f"{service}._judge", side_effect=fake_judge),
        patch(f"{service}.align_words", return_value=SPANS),
        patch(f"{service}.describe_error", side_effect=fake_describe),
        patch(f"{service}.create_openai_client", return_value=None),
    ):
        yield


class WallClockBudgetTests(unittest.TestCase):
    """심각 1 — 전체 예산: 어떤 조합에서도 BE 타임아웃(20초) 전에 응답한다."""

    def test_slow_judgment_fails_within_budget_as_503(self):
        settings = make_settings(pronunciation_total_budget_seconds=0.3)
        with pipeline(judge_delay=1.5):
            client = make_client(settings)
            started = time.monotonic()
            response = client.post("/api/v1/pronunciation/analyze", json=REQUEST_BODY)
            elapsed = time.monotonic() - started

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")
        self.assertLess(elapsed, 1.2)

    def test_describe_is_skipped_when_budget_is_nearly_exhausted(self):
        settings = make_settings(pronunciation_total_budget_seconds=0.8)
        calls = []
        differences = [JudgedDifference(word="nothing", type="SOUND")]
        with pipeline(differences=differences, describe_calls=calls):
            response = make_client(settings).post(
                "/api/v1/pronunciation/analyze", json=REQUEST_BODY
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [])
        words = response.json()["data"]["words"]
        self.assertEqual(words[1]["status"], "PHONEME_ERROR")
        self.assertIsNone(words[1]["userDisplay"])

    def test_describe_runs_when_budget_is_ample(self):
        calls = []
        differences = [JudgedDifference(word="nothing", type="SOUND")]
        description = ErrorDescription(
            user_heard="nuh·ssing", target_span="th", user_span="ss", stress_index=None
        )
        with pipeline(
            differences=differences,
            describe_result=description,
            describe_calls=calls,
        ):
            response = make_client().post(
                "/api/v1/pronunciation/analyze", json=REQUEST_BODY
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 1)
        words = response.json()["data"]["words"]
        self.assertEqual(words[1]["userDisplay"], "nuh·ssing")


class ReferenceUrlAllowlistTests(unittest.TestCase):
    """심각 2 — SSRF: 참조 URL은 허용된 origin만 통과한다."""

    def post(self, url, settings=None):
        body = {**REQUEST_BODY, "referenceAudioUrl": url}
        with pipeline():
            return make_client(settings).post(
                "/api/v1/pronunciation/analyze", json=body
            )

    def test_allowed_origin_passes(self):
        response = self.post(f"{ALLOWED_ORIGIN}/tts/1/EN_US/sentence.mp3")

        self.assertEqual(response.status_code, 200)

    def test_http_scheme_is_rejected(self):
        response = self.post("http://d19azau1un4t7r.cloudfront.net/a.mp3")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_unknown_host_is_rejected(self):
        response = self.post("https://169.254.169.254/latest/meta-data")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_url_with_credentials_is_rejected(self):
        response = self.post(
            "https://d19azau1un4t7r.cloudfront.net@evil.example.com/a.mp3"
        )

        self.assertEqual(response.status_code, 400)

    def test_non_http_scheme_is_rejected(self):
        response = self.post("file:///etc/passwd")

        self.assertEqual(response.status_code, 400)

    def test_allowlist_is_extensible_via_settings(self):
        settings = make_settings(
            pronunciation_reference_allowed_origins=(
                f"{ALLOWED_ORIGIN},https://cdn.example.com"
            )
        )
        response = self.post("https://cdn.example.com/a.mp3", settings=settings)

        self.assertEqual(response.status_code, 200)


class FakeStreamResponse:
    def __init__(self, status_code=200, chunks=(b"audio",)):
        self.status_code = status_code
        self._chunks = chunks

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def iter_bytes(self):
        yield from self._chunks


@contextmanager
def fake_stream_factory(response, captured):
    def fake_stream(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})

        @contextmanager
        def ctx():
            yield response

        return ctx()

    with patch(
        "app.pronunciation.application.analysis_service.httpx.stream",
        side_effect=fake_stream,
    ) as mocked:
        yield mocked


class ReferenceDownloadTests(unittest.TestCase):
    """심각 2 — 다운로드: 리다이렉트 금지·크기 상한·서비스 단 재검증."""

    def setUp(self):
        self.settings = make_settings()
        self.url = f"{ALLOWED_ORIGIN}/tts/1/EN_US/sentence.wav"

    def test_download_does_not_follow_redirects(self):
        captured = {}
        with fake_stream_factory(FakeStreamResponse(status_code=302), captured):
            with self.assertRaises(ReferenceAudioUnavailableError):
                _download_reference(self.url, self.settings)

        self.assertIs(captured["follow_redirects"], False)

    def test_download_rejects_oversized_body(self):
        chunks = [b"x" * 2_000_000] * 6  # 12MB > 10MB 상한
        captured = {}
        with fake_stream_factory(FakeStreamResponse(chunks=chunks), captured):
            with self.assertRaises(ReferenceAudioUnavailableError):
                _download_reference(self.url, self.settings)

    def test_download_rechecks_allowlist_as_defense_in_depth(self):
        captured = {}
        with fake_stream_factory(FakeStreamResponse(), captured) as mocked:
            with self.assertRaises(ReferenceAudioUnavailableError):
                _download_reference("https://evil.example.com/a.wav", self.settings)

        mocked.assert_not_called()

    def test_download_returns_wav_body_untouched(self):
        captured = {}
        with fake_stream_factory(
            FakeStreamResponse(chunks=(b"RIFF", b"data")), captured
        ):
            body = _download_reference(self.url, self.settings)

        self.assertEqual(body, b"RIFFdata")


class SentryLeakTests(unittest.TestCase):
    """심각 3 — 유저 음성이 Sentry·repr로 새지 않는다."""

    def test_decoded_audio_repr_hides_wav_bytes(self):
        rendered = repr(DECODED)

        self.assertNotIn("SECRET-JUDGMENT-BYTES", rendered)
        self.assertNotIn("SECRET-ALIGNMENT-BYTES", rendered)
        self.assertIn("duration_seconds", rendered)

    def test_sentry_init_disables_local_variables_and_pii(self):
        settings = make_settings(sentry_dsn="https://key@sentry.example.com/1")
        with patch("app.core.sentry.sentry_sdk.init") as mocked:
            init_sentry(settings)

        kwargs = mocked.call_args.kwargs
        self.assertIs(kwargs["include_local_variables"], False)
        self.assertEqual(kwargs["max_request_body_size"], "never")
        self.assertIs(kwargs["send_default_pii"], False)


class AccentContrastNullHandlingTests(unittest.TestCase):
    """중간 A — BE 직렬화의 명시적 null은 생략과 동일하게 처리한다."""

    def test_null_error_type_defaults_to_phoneme(self):
        contrast = PronunciationAccentContrast.model_validate(
            {"expected": "a clear t", "other": "a flap", "errorType": None}
        )

        self.assertIs(contrast.errorType, PronunciationAccentErrorType.PHONEME)

    def test_null_options_drop_the_contrast_with_a_warning(self):
        # 자산 데이터 품질 문제를 관측할 수 있게 경고를 남긴다.
        # 로그에는 order만 싣는다 (오디오 파생 텍스트 금지).
        with self.assertLogs("app.models.pronunciation", level="WARNING") as logs:
            word = PronunciationWordInput.model_validate(
                {
                    "order": 7,
                    "word": "water",
                    "accentContrast": {
                        "expected": None,
                        "other": None,
                        "errorType": None,
                    },
                }
            )

        self.assertIsNone(word.accentContrast)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("order=7", logs.output[0])
        self.assertNotIn("water", logs.output[0])

    def test_http_request_with_null_error_type_is_accepted(self):
        body = {
            **REQUEST_BODY,
            "words": [
                {"order": 1, "word": "There's"},
                {"order": 2, "word": "nothing"},
                {
                    "order": 3,
                    "word": "like",
                    "accentContrast": {
                        "expected": "a clear t",
                        "other": "a flap",
                        "errorType": None,
                    },
                },
            ],
        }
        with pipeline():
            response = make_client().post(
                "/api/v1/pronunciation/analyze", json=body
            )

        self.assertEqual(response.status_code, 200)


class SlowFakeCompletions:
    def __init__(self, *, contents, delay=0.0):
        self.contents = list(contents)
        self.delay = delay
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self.contents.pop(0)))
            ]
        )


class FakeClient:
    def __init__(self, *, contents, delay=0.0):
        self.completions = SlowFakeCompletions(contents=contents, delay=delay)
        self.chat = SimpleNamespace(completions=self.completions)


class JudgmentBudgetTests(unittest.TestCase):
    """심각 1 — 판정 재시도는 남은 예산이 있을 때만 수행한다."""

    def test_exhausted_deadline_fails_without_calling_llm(self):
        client = FakeClient(contents=['{"differences": []}'])

        with self.assertRaises(PronunciationJudgmentError):
            judge_pronunciation(
                client,
                make_settings(),
                reference_wav=b"reference",
                user_wav=b"user",
                deadline=time.monotonic() - 1.0,
            )
        self.assertEqual(len(client.completions.calls), 0)

    def test_retry_is_skipped_when_deadline_passes_mid_call(self):
        client = FakeClient(contents=["not json", '{"differences": []}'], delay=0.15)

        with self.assertRaises(PronunciationJudgmentInvalidError):
            judge_pronunciation(
                client,
                make_settings(),
                reference_wav=b"reference",
                user_wav=b"user",
                deadline=time.monotonic() + 0.05,
            )
        self.assertEqual(len(client.completions.calls), 1)


class DescribeHardeningTests(unittest.TestCase):
    """중간 B — stressIndex는 respelling 음절 범위 안일 때만 채운다. + 예산 준수."""

    def describe(self, content, error_type="STRESS", deadline=None):
        client = FakeClient(contents=[content])
        result = describe_error(
            client,
            make_settings(),
            reference_wav=b"reference",
            user_wav=b"user",
            word="hiking",
            error_type=error_type,
            **({"deadline": deadline} if deadline is not None else {}),
        )
        return result, client

    def test_stress_index_within_syllables_is_kept(self):
        result, _ = self.describe('{"userHeard": "hik·ing", "stressIndex": 1}')

        self.assertEqual(result.stress_index, 1)

    def test_stress_index_beyond_syllables_falls_back_to_none(self):
        result, _ = self.describe('{"userHeard": "hik·ing", "stressIndex": 99}')

        self.assertIsNone(result.stress_index)

    def test_negative_stress_index_falls_back_to_none(self):
        result, _ = self.describe('{"userHeard": "hik·ing", "stressIndex": -1}')

        self.assertIsNone(result.stress_index)

    def test_boolean_stress_index_falls_back_to_none(self):
        result, _ = self.describe('{"userHeard": "hik·ing", "stressIndex": true}')

        self.assertIsNone(result.stress_index)

    def test_stress_index_without_user_heard_falls_back_to_none(self):
        result, _ = self.describe('{"stressIndex": 1}')

        self.assertIsNone(result.stress_index)

    def test_exhausted_deadline_skips_the_call(self):
        result, client = self.describe(
            '{"userHeard": "hik·ing", "stressIndex": 1}',
            deadline=time.monotonic() - 1.0,
        )

        self.assertIsNone(result)
        self.assertEqual(len(client.completions.calls), 0)


if __name__ == "__main__":
    unittest.main()
