# 기억의 시간 상태와 프롬프트 기준 시각을 검증하는 회귀 테스트.
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.free_talk.application.memory_context import memory_context_with_time_status
from app.main import create_app
from app.models.free_talk import MemoryContext
from tests.test_free_talk_api import (
    FakeOpenAI,
    make_client,
    make_settings,
    normal_turn_completion,
    opening_completion,
    valid_memory_context,
    valid_opening_payload,
    valid_turn_payload,
)


class MemoryContextTimeTests(unittest.TestCase):
    def test_validity_boundaries_compare_instants_in_request_timezone(self):
        now = datetime(2026, 9, 10, 15, 5, tzinfo=UTC)
        for start, end, zone, expected in (
            (None, "2026-09-11T00:05:00+09:00", "Asia/Seoul", "WITHIN_TIME_BOUNDS"),
            (None, "2026-09-11T00:04:59+09:00", "Asia/Seoul", "EXPIRED"),
            ("2026-09-11T00:05:01+09:00", None, "Asia/Seoul", "NOT_YET_VALID"),
            ("2026-09-10T15:05:00Z", None, "Asia/Seoul", "WITHIN_TIME_BOUNDS"),
            (None, "2026-09-10T23:59:59", "Asia/Seoul", "EXPIRED"),
            (None, "2026-09-10T23:59:59", "America/Los_Angeles", "WITHIN_TIME_BOUNDS"),
            ("2026-09-10T18:00:00", None, "America/Los_Angeles", "NOT_YET_VALID"),
            (None, None, "Asia/Seoul", "UNKNOWN"),
            ("2026-09-12T00:00:00Z", "2026-09-10T00:00:00Z", "Asia/Seoul", "UNKNOWN"),
        ):
            with self.subTest(start=start, end=end, zone=zone):
                memory = MemoryContext.model_validate(
                    valid_memory_context(validFrom=start, validTo=end),
                )
                context = memory_context_with_time_status(memory, zone, now)
                self.assertEqual(context["temporalStatus"], expected)

    def test_offset_is_preserved_across_daylight_saving_fold(self):
        memory = MemoryContext.model_validate(valid_memory_context(
            validFrom=None, validTo="2026-11-01T01:30:00-07:00",
        ))
        # 같은 현지 시각 01:30이라도 DST 종료 뒤 현재 시각보다 한 시간 전이다.
        now = datetime.fromisoformat("2026-11-01T01:30:00-08:00")
        result = memory_context_with_time_status(memory, "America/Los_Angeles", now)
        self.assertEqual(result["temporalStatus"], "EXPIRED")

    def test_expired_memory_is_retained_as_historical_reference(self):
        memory = valid_memory_context(
            memoryType="PROFILE",
            content="사용자는 베를린의 서점에서 일한다.",
            validFrom="2026-08-01T09:00:00+09:00",
            validTo="2026-08-31T23:59:59+09:00",
        )
        for path, payload, completion in (
            ("opening", valid_opening_payload(), opening_completion()),
            ("turn", valid_turn_payload(), normal_turn_completion()),
        ):
            with self.subTest(path=path):
                messages = self.request_messages(path, payload, completion, memory)
                context = json.loads(messages[1]["content"])["memoryContext"][0]
                self.assertEqual(context["temporalStatus"], "EXPIRED")
                self.assertEqual(context["content"], memory["content"])
                self.assertIn("current status is unknown", messages[0]["content"])
                self.assertIn("both aiMessage and translatedMessage", messages[0]["content"])

    def test_continue_repair_reuses_time_and_memory_status(self):
        fake = FakeOpenAI(contents=[
            json.dumps(normal_turn_completion(aiMessage=None, translatedMessage=None)),
            json.dumps(normal_turn_completion()),
        ])
        settings = make_settings(openrouter_api_key="test", openrouter_model="test")
        payload = valid_turn_payload(responseMode="CONTINUE_AFTER_EXIT_DECLINED")
        payload["memoryContext"] = [valid_memory_context(
            validFrom=None, validTo="2026-09-11T00:05:00+09:00",
        )]
        with patch("app.free_talk.llm.json_completion.create_openai_client", return_value=fake), patch(
            "app.free_talk.application.conversation_service.datetime",
        ) as clock:
            clock.now.side_effect = [
                datetime(2026, 9, 10, 15, 5, tzinfo=UTC),
                datetime(2026, 9, 10, 15, 5, 1, tzinfo=UTC),
            ]
            response = make_client(create_app(settings)).post(
                "/api/v1/free-talk/turn", json=payload,
            )
            clock.now.assert_called_once_with(UTC)
        self.assertEqual(response.status_code, 200)
        first, repair = [call["messages"] for call in fake.completions.calls]
        self.assertEqual(first[1]["content"], repair[1]["content"])
        for messages in (first, repair):
            self.assertIn("2026-09-11T00:05:00+09:00", messages[0]["content"])
            memory = json.loads(messages[1]["content"])["memoryContext"][0]
            self.assertEqual(memory["temporalStatus"], "WITHIN_TIME_BOUNDS")

    def request_messages(self, path, payload, completion, memory):
        fake = FakeOpenAI(contents=[json.dumps(completion)])
        settings = make_settings(openrouter_api_key="test", openrouter_model="test")
        with patch("app.free_talk.llm.json_completion.create_openai_client", return_value=fake), patch(
            "app.free_talk.application.conversation_service.datetime",
        ) as clock:
            clock.now.return_value = datetime(2026, 9, 10, 15, 5, tzinfo=UTC)
            response = make_client(create_app(settings)).post(
                f"/api/v1/free-talk/{path}",
                json=payload | {"memoryContext": [memory]},
            )
            clock.now.assert_called_once_with(UTC)
        self.assertEqual(response.status_code, 200)
        return fake.completions.calls[0]["messages"]
