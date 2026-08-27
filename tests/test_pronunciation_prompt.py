# 발음 판정 프롬프트 렌더링과 응답 파싱을 검증하는 unittest 모듈
#
# 프롬프트 본문에 JSON 예시의 중괄호가 있어 렌더링이 깨지기 쉬우므로
# 실제로 만들어지는 프롬프트 문자열을 직접 확인한다.
import json
import unittest
from types import SimpleNamespace

from app.core.config import Settings
from app.pronunciation.llm.compare import (
    ACCENT_NAMES,
    PronunciationJudgmentInvalidError,
    judge_pronunciation,
)


class FakeCompletions:
    def __init__(self, *, contents):
        self.contents = list(contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.contents.pop(0))
                )
            ]
        )


class FakeClient:
    def __init__(self, *, contents):
        self.completions = FakeCompletions(contents=contents)
        self.chat = SimpleNamespace(completions=self.completions)


def make_settings():
    return Settings(_env_file=None)


def judge(client, accent_locale="EN_US", extended=True):
    return judge_pronunciation(
        client,
        make_settings(),
        reference_wav=b"reference",
        user_wav=b"user",
        accent_locale=accent_locale,
        extended=extended,
    )


def prompt_of(client):
    return client.completions.calls[0]["messages"][0]["content"][0]["text"]


class PromptRenderingTests(unittest.TestCase):
    def test_accent_name_is_substituted_for_every_locale(self):
        for locale, accent_name in ACCENT_NAMES.items():
            client = FakeClient(contents=['{"differences": []}'])

            judge(client, accent_locale=locale)

            rendered = prompt_of(client)
            self.assertIn(accent_name, rendered)
            self.assertNotIn("{accent_name}", rendered)

    def test_json_example_braces_survive_rendering(self):
        client = FakeClient(contents=['{"differences": []}'])

        judge(client)

        rendered = prompt_of(client)
        self.assertIn('{"differences": []}', rendered)

    def test_base_prompt_also_renders(self):
        client = FakeClient(contents=['{"differences": []}'])

        judge(client, accent_locale="EN_GB", extended=False)

        rendered = prompt_of(client)
        self.assertIn("British English", rendered)
        self.assertNotIn("{accent_name}", rendered)

    def test_both_audio_clips_are_attached(self):
        client = FakeClient(contents=['{"differences": []}'])

        judge(client)

        content = client.completions.calls[0]["messages"][0]["content"]
        audio_parts = [part for part in content if part["type"] == "input_audio"]
        self.assertEqual(len(audio_parts), 2)
        self.assertEqual(audio_parts[0]["input_audio"]["format"], "wav")

    def test_poc_confirmed_settings_are_used(self):
        client = FakeClient(contents=['{"differences": []}'])

        judge(client)

        call = client.completions.calls[0]
        self.assertEqual(call["temperature"], 0.0)
        self.assertEqual(call["extra_body"], {"reasoning": {"effort": "low"}})
        self.assertEqual(call["model"], "google/gemini-3.5-flash")


class ResponseParsingTests(unittest.TestCase):
    def test_extended_fields_are_parsed(self):
        payload = json.dumps(
            {
                "differences": [
                    {
                        "word": "nothing",
                        "type": "SOUND",
                        "userHeard": "nuh·ssing",
                        "targetSpan": "th",
                        "userSpan": "ss",
                    },
                    {
                        "word": "hiking",
                        "type": "STRESS",
                        "userHeard": "hik·ing",
                        "stressIndex": 1,
                    },
                ]
            }
        )
        client = FakeClient(contents=[payload])

        differences = judge(client)

        self.assertEqual(differences[0].user_heard, "nuh·ssing")
        self.assertEqual(differences[0].target_span, "th")
        self.assertEqual(differences[1].stress_index, 1)

    def test_markdown_fences_are_stripped(self):
        client = FakeClient(contents=['```json\n{"differences": []}\n```'])

        self.assertEqual(judge(client), [])

    def test_schema_violation_is_retried_then_raises(self):
        # 스파이크 실측에서 36회 중 1회 나온 실패 유형이다
        client = FakeClient(contents=['{"wrong": 1}', '{"wrong": 2}'])

        with self.assertRaises(PronunciationJudgmentInvalidError):
            judge(client)
        self.assertEqual(len(client.completions.calls), 2)

    def test_schema_violation_recovers_on_retry(self):
        client = FakeClient(contents=["not json at all", '{"differences": []}'])

        self.assertEqual(judge(client), [])
        self.assertEqual(len(client.completions.calls), 2)

    def test_non_object_json_recovers_on_retry(self):
        # JSON은 유효하지만 객체가 아닌 응답(배열 등)도 스키마 위반으로 처리한다
        client = FakeClient(contents=["[1, 2]", '{"differences": []}'])

        self.assertEqual(judge(client), [])
        self.assertEqual(len(client.completions.calls), 2)

    def test_non_object_json_raises_schema_error_not_500(self):
        client = FakeClient(contents=['"just a string"', "[]"])

        with self.assertRaises(PronunciationJudgmentInvalidError):
            judge(client)
        self.assertEqual(len(client.completions.calls), 2)


if __name__ == "__main__":
    unittest.main()
