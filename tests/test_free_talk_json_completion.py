# 기억 전용 추론 옵션이 일반 프리톡 호출에 적용되지 않는지 검사한다.
import unittest
from unittest.mock import patch

from app.free_talk.llm.json_completion import request_json_completion
from tests.test_free_talk_api import FakeOpenAI, make_settings


class JsonCompletionReasoningTests(unittest.TestCase):
    def test_reasoning_is_opt_in_and_output_is_bounded(self):
        for effort in (None, "medium"):
            with self.subTest(effort=effort):
                fake = FakeOpenAI(contents=['{"ok": true}'])
                with patch("app.core.openai_client.OpenAI", return_value=fake):
                    result = request_json_completion(
                        settings=make_settings(openrouter_api_key="test", openrouter_model="test"),
                        system_prompt="Return JSON.", user_prompt="Check.",
                        reasoning_effort=effort,
                    )
                self.assertEqual(result, {"ok": True})
                call = fake.completions.calls[0]
                if effort is None:
                    self.assertNotIn("extra_body", call)
                    self.assertNotIn("max_completion_tokens", call)
                else:
                    self.assertEqual(call["extra_body"],
                                     {"reasoning": {"effort": "medium", "exclude": True}})
                    self.assertEqual(call["max_completion_tokens"], 4096)
