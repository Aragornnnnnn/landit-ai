# 발음 분석 API의 HTTP 계약을 검증하는 unittest 모듈
import base64
import json
import unittest
import warnings
from unittest.mock import patch

from app.core.config import Settings
from app.core.sentry import scrub_sensitive_request_data
from app.main import create_app
from app.models.pronunciation import PronunciationAnalyzeRequest
from app.pronunciation.alignment.forced_align import AlignmentError, WordSpan
from app.pronunciation.audio import AudioDecodeError, DecodedAudio
from app.pronunciation.llm.accent_check import AccentVerdict
from app.pronunciation.llm.compare import (
    JudgedDifference,
    PronunciationJudgmentError,
    PronunciationJudgmentInvalidError,
)


USER_AUDIO_BASE64 = base64.b64encode(b"fake-audio-bytes").decode("ascii")

REQUEST_BODY = {
    "userAudio": USER_AUDIO_BASE64,
    "userAudioFormat": "m4a",
    "sentenceText": "There's nothing like.",
    "referenceAudioUrl": (
        "https://d19azau1un4t7r.cloudfront.net/tts/1/EN_US/sentence.mp3"
    ),
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
    judgment_wav=b"judgment", alignment_wav=b"alignment", duration_seconds=2.0
)


def make_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def make_client():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated.*",
        )
        from fastapi.testclient import TestClient

        return TestClient(create_app(make_settings()))


def patch_pipeline(
    differences=None,
    spans=SPANS,
    decode_error=None,
    judge_error=None,
    align_error=None,
    accent_verdicts=None,
):
    service = "app.pronunciation.application.analysis_service"

    def fake_decode(data, audio_format, *args, **kwargs):
        if decode_error is not None:
            raise decode_error
        return DECODED

    def fake_judge(url, wav, accent_locale, settings, *args, **kwargs):
        if judge_error is not None:
            raise judge_error
        return list(differences or []), b"reference-wav"

    def fake_align(wav, words):
        if align_error is not None:
            raise align_error
        return spans

    verdicts = dict(accent_verdicts or {})

    def fake_check_accent(wav, contrast, settings):
        return verdicts.get(contrast.word)

    return (
        patch(f"{service}.decode_user_audio", side_effect=fake_decode),
        patch(f"{service}._judge", side_effect=fake_judge),
        patch(f"{service}.align_words", side_effect=fake_align),
        patch(f"{service}._check_accent", side_effect=fake_check_accent),
        # 묘사 호출은 판정 결과를 바꾸지 않으므로 계약 테스트에서는 비운다
        patch(f"{service}.describe_error", return_value=None),
        patch(f"{service}.create_openai_client", return_value=None),
    )


class PronunciationAnalyzeApiTests(unittest.TestCase):
    def post(self, body=REQUEST_BODY, **pipeline_kwargs):
        patches = patch_pipeline(**pipeline_kwargs)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            return make_client().post("/api/v1/pronunciation/analyze", json=body)

    def test_all_correct_words(self):
        response = self.post()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        words = payload["data"]["words"]
        self.assertEqual([w["order"] for w in words], [1, 2, 3])
        self.assertEqual({w["status"] for w in words}, {"CORRECT"})
        self.assertEqual(words[0]["startMs"], 90)
        self.assertEqual(words[0]["endMs"], 470)
        self.assertIsNone(words[0]["userDisplay"])

    def test_phoneme_and_stress_errors_are_merged(self):
        differences = [
            JudgedDifference(
                word="nothing",
                type="SOUND",
                user_heard="nuh·ssing",
                target_span="th",
                user_span="ss",
            ),
            JudgedDifference(word="like", type="STRESS", stress_index=1),
        ]
        response = self.post(differences=differences)

        words = response.json()["data"]["words"]
        self.assertEqual(words[1]["status"], "PHONEME_ERROR")
        self.assertEqual(words[1]["userDisplay"], "nuh·ssing")
        self.assertEqual(words[1]["errorTargetSpan"], "th")
        self.assertEqual(words[1]["errorUserSpan"], "ss")
        self.assertIsNone(words[1]["userStressIndex"])
        self.assertEqual(words[2]["status"], "STRESS_ERROR")
        self.assertEqual(words[2]["userStressIndex"], 1)
        self.assertIsNone(words[2]["errorTargetSpan"])

    def test_unknown_detected_word_is_ignored(self):
        differences = [JudgedDifference(word="banana", type="SOUND")]
        response = self.post(differences=differences)

        words = response.json()["data"]["words"]
        self.assertEqual({w["status"] for w in words}, {"CORRECT"})

    def test_invalid_audio_returns_400(self):
        response = self.post(decode_error=AudioDecodeError("boom"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_AUDIO")

    def test_judgment_invalid_returns_502(self):
        response = self.post(
            judge_error=PronunciationJudgmentInvalidError("bad json")
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "AI_RESPONSE_INVALID")

    def test_judgment_failure_returns_503(self):
        response = self.post(judge_error=PronunciationJudgmentError("down"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")

    def test_alignment_failure_returns_503(self):
        response = self.post(align_error=AlignmentError("no path"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "AI_GENERATION_FAILED")

    def test_invalid_base64_returns_400_without_echoing_audio(self):
        body = {**REQUEST_BODY, "userAudio": "not-base64!!!"}
        response = self.post(body=body)

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("not-base64!!!", response.text)

    def test_words_mismatching_sentence_return_400(self):
        body = {**REQUEST_BODY, "sentenceText": "There's nothing like hiking."}
        response = self.post(body=body)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_numeric_word_is_accepted_and_aligned_as_spelled_word(self):
        captured = {}
        body = {
            **REQUEST_BODY,
            "sentenceText": "The flight takes off at 9.",
            "words": [
                {"order": 1, "word": "The"},
                {"order": 2, "word": "flight"},
                {"order": 3, "word": "takes"},
                {"order": 4, "word": "off"},
                {"order": 5, "word": "at"},
                {"order": 6, "word": "9"},
            ],
        }
        spans = [
            WordSpan(word=w, start_ms=i * 100, end_ms=i * 100 + 90)
            for i, w in enumerate(["The", "flight", "takes", "off", "at", "nine"])
        ]

        patches = patch_pipeline(spans=spans)

        def capture_align(wav, words):
            captured["words"] = words
            return spans

        with patches[0], patches[1], patches[3], patches[4], patches[5], patch(
            "app.pronunciation.application.analysis_service.align_words",
            side_effect=capture_align,
        ):
            response = make_client().post(
                "/api/v1/pronunciation/analyze", json=body
            )

        self.assertEqual(response.status_code, 200)
        # 정렬에는 발화 철자가 전달된다
        self.assertEqual(captured["words"][-1], "nine")
        words = response.json()["data"]["words"]
        self.assertEqual(words[-1]["word"], "9")
        self.assertEqual(words[-1]["status"], "CORRECT")

    def test_numeric_word_above_99_returns_400(self):
        body = {
            **REQUEST_BODY,
            "sentenceText": "Room 101 is ready.",
            "words": [
                {"order": 1, "word": "Room"},
                {"order": 2, "word": "101"},
                {"order": 3, "word": "is"},
                {"order": 4, "word": "ready"},
            ],
        }
        response = self.post(body=body)

        self.assertEqual(response.status_code, 400)

    def test_duplicate_word_orders_return_400(self):
        body = {
            **REQUEST_BODY,
            "words": [{"order": 1, "word": "a"}, {"order": 1, "word": "b"}],
        }
        response = self.post(body=body)

        self.assertEqual(response.status_code, 400)


GB_BODY = {
    **REQUEST_BODY,
    "accentLocale": "EN_GB",
    "words": [
        {"order": 1, "word": "There's"},
        {"order": 2, "word": "nothing"},
        {
            "order": 3,
            "word": "like",
            "accentContrast": {
                "expected": "a clear t (WAW-tuh)",
                "other": "a d-like flap (WAH-der)",
            },
        },
    ],
}


class AccentContrastApiTests(unittest.TestCase):
    def post(self, body=GB_BODY, **pipeline_kwargs):
        patches = patch_pipeline(**pipeline_kwargs)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            return make_client().post("/api/v1/pronunciation/analyze", json=body)

    def test_expected_accent_keeps_word_correct(self):
        verdict = AccentVerdict(
            order=3, word="like", matches_expected=True, user_heard="waw-tuh"
        )
        response = self.post(accent_verdicts={"like": verdict})

        words = response.json()["data"]["words"]
        self.assertEqual(words[2]["status"], "CORRECT")

    def test_wrong_accent_marks_phoneme_error(self):
        verdict = AccentVerdict(
            order=3, word="like", matches_expected=False, user_heard="wah-der"
        )
        response = self.post(accent_verdicts={"like": verdict})

        words = response.json()["data"]["words"]
        self.assertEqual(words[2]["status"], "PHONEME_ERROR")
        self.assertEqual(words[2]["userDisplay"], "wah-der")

    def test_stress_contrast_marks_stress_error(self):
        body = json.loads(json.dumps(GB_BODY))
        body["words"][2]["accentContrast"]["errorType"] = "STRESS"
        verdict = AccentVerdict(
            order=3, word="like", matches_expected=False, user_heard="li·KE"
        )
        response = self.post(body=body, accent_verdicts={"like": verdict})

        words = response.json()["data"]["words"]
        self.assertEqual(words[2]["status"], "STRESS_ERROR")

    def test_main_judgment_wins_over_accent_verdict(self):
        # 본 판정이 이미 오류로 본 단어는 억양 판정이 덮어쓰지 않는다
        differences = [
            JudgedDifference(word="like", type="SOUND", user_heard="lick")
        ]
        verdict = AccentVerdict(
            order=3, word="like", matches_expected=False, user_heard="wah-der"
        )
        response = self.post(
            differences=differences, accent_verdicts={"like": verdict}
        )

        words = response.json()["data"]["words"]
        self.assertEqual(words[2]["status"], "PHONEME_ERROR")
        self.assertEqual(words[2]["userDisplay"], "lick")

    def test_accent_check_failure_does_not_break_response(self):
        response = self.post(accent_verdicts={})

        self.assertEqual(response.status_code, 200)
        words = response.json()["data"]["words"]
        self.assertEqual(words[2]["status"], "CORRECT")

    def test_words_without_contrast_are_not_checked(self):
        response = self.post(body=REQUEST_BODY)

        self.assertEqual(response.status_code, 200)


class UserAudioPrivacyTests(unittest.TestCase):
    def test_request_repr_hides_user_audio(self):
        request = PronunciationAnalyzeRequest(**REQUEST_BODY)

        self.assertNotIn(USER_AUDIO_BASE64, repr(request))
        self.assertNotIn(USER_AUDIO_BASE64, str(request))

    def test_validation_error_does_not_echo_user_audio(self):
        body = {**REQUEST_BODY, "sentenceText": "   "}
        patches = patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = make_client().post(
                "/api/v1/pronunciation/analyze", json=body
            )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(USER_AUDIO_BASE64, response.text)

    def test_sentry_scrubber_filters_user_audio(self):
        event = {
            "request": {
                "data": {"userAudio": USER_AUDIO_BASE64, "accentLocale": "EN_US"}
            }
        }

        scrubbed = scrub_sensitive_request_data(event, {})

        self.assertEqual(scrubbed["request"]["data"]["userAudio"], "[Filtered]")
        self.assertEqual(scrubbed["request"]["data"]["accentLocale"], "EN_US")


if __name__ == "__main__":
    unittest.main()
