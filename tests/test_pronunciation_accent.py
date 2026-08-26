# 억양 양자택일 판정을 검증하는 unittest 모듈
import json
import unittest
from types import SimpleNamespace

from app.core.config import Settings
from app.pronunciation.llm.accent_check import (
    AccentContrast,
    check_accent,
)


class FakeCompletions:
    def __init__(self, *, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, *, content):
        self.completions = FakeCompletions(content=content)
        self.chat = SimpleNamespace(completions=self.completions)


def make_settings():
    return Settings(_env_file=None)


# order가 홀수면 기대 발음이 A, 짝수면 B에 배치된다 (선택지 순서 편향 방지)
ODD_CONTRAST = AccentContrast(
    order=1,
    word="water",
    expected_option="a clear t (WAW-tuh)",
    other_option="a d-like flap (WAH-der)",
)
EVEN_CONTRAST = AccentContrast(
    order=2,
    word="water",
    expected_option="a clear t (WAW-tuh)",
    other_option="a d-like flap (WAH-der)",
)


def run(client, contrast=ODD_CONTRAST):
    return check_accent(client, make_settings(), b"user-audio", contrast)


def prompt_of(client):
    return client.completions.calls[0]["messages"][0]["content"][0]["text"]


class AccentCheckTests(unittest.TestCase):
    def test_expected_pronunciation_passes(self):
        client = FakeClient(content='{"answer": "A", "heard": "waw-tuh"}')

        verdict = run(client)

        self.assertTrue(verdict.matches_expected)
        self.assertEqual(verdict.word, "water")
        self.assertEqual(verdict.user_heard, "waw-tuh")

    def test_other_pronunciation_fails(self):
        client = FakeClient(content='{"answer": "B", "heard": "wah-der"}')

        verdict = run(client)

        self.assertFalse(verdict.matches_expected)
        self.assertEqual(verdict.user_heard, "wah-der")

    def test_option_order_flips_with_word_order(self):
        # 짝수 order에서는 기대 발음이 B에 놓이므로 같은 "B" 응답이 정답이 된다
        client = FakeClient(content='{"answer": "B", "heard": "waw-tuh"}')

        verdict = run(client, EVEN_CONTRAST)

        self.assertTrue(verdict.matches_expected)

    def test_word_and_options_are_rendered_into_prompt(self):
        client = FakeClient(content='{"answer": "A"}')

        run(client)

        rendered = prompt_of(client)
        self.assertIn('"water"', rendered)
        self.assertIn("a clear t (WAW-tuh)", rendered)
        self.assertIn("a d-like flap (WAH-der)", rendered)
        self.assertNotIn("{word}", rendered)
        self.assertNotIn("{option_a}", rendered)

    def test_json_example_braces_survive_rendering(self):
        client = FakeClient(content='{"answer": "A"}')

        run(client)

        self.assertIn('{"answer": "A", "heard":', prompt_of(client))

    def test_only_the_user_audio_is_sent(self):
        # 억양 확인은 참조 오디오 없이 유저 발화만 듣고 판별한다
        client = FakeClient(content='{"answer": "A"}')

        run(client)

        content = client.completions.calls[0]["messages"][0]["content"]
        audio_parts = [part for part in content if part["type"] == "input_audio"]
        self.assertEqual(len(audio_parts), 1)

    def test_unclear_answer_yields_no_verdict(self):
        client = FakeClient(content='{"answer": "UNCLEAR"}')

        self.assertIsNone(run(client))

    def test_unparsable_response_yields_no_verdict(self):
        client = FakeClient(content="sorry, I cannot tell")

        self.assertIsNone(run(client))

    def test_missing_heard_field_is_tolerated(self):
        client = FakeClient(content=json.dumps({"answer": "B"}))

        verdict = run(client)

        self.assertFalse(verdict.matches_expected)
        self.assertIsNone(verdict.user_heard)


if __name__ == "__main__":
    unittest.main()
