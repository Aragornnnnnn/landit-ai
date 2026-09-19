# 장기기억 후보 응답에 얹는 다음 스몰톡 후속 질문의 규칙과 HTTP 계약을 검증하는 unittest 모듈
import json
import unittest
from datetime import date
from unittest.mock import patch

from app.free_talk.application.follow_up_service import (
    DEFAULT_INVITE,
    DEFAULT_QUESTION,
    FALLBACK_WORKFLOW,
    FOLLOW_UP_POLICY_HEADING,
)
from app.free_talk.domain.follow_up_rules import (
    AskableMemory,
    FollowUpOption,
    memories_for_prompt,
    scheduled_date_status,
    select_follow_up,
)
from app.free_talk.llm.json_completion import AiGenerationFailedError
from app.main import create_app
from app.models.free_talk import FollowUpTriggerType, MemoryType
from tests.test_free_talk_api import (
    FakeOpenAI,
    make_client,
    make_settings,
    valid_memory_candidate_completion,
    valid_memory_candidates_payload,
)

MEMORY_CANDIDATES_PATH = "/api/v1/free-talk/memory-candidates"
FOLLOW_UP_LOGGER = "app.free_talk.application.follow_up_service"
NONE_QUESTION = {
    "memoryId": None,
    "candidateIndex": None,
    "triggerType": "NONE",
    "question": DEFAULT_QUESTION,
    "invite": DEFAULT_INVITE,
}
# 테스트가 실행 시각에 기대지 않도록 확실히 지난 날짜와 확실히 먼 날짜를 쓴다
PAST = "2020-09-14T23:59:59+09:00"
FUTURE = "2099-09-23T23:59:59+09:00"


def memory(memory_id, memory_type, content, valid_to=None):
    return {
        "memoryId": memory_id,
        "memoryType": memory_type,
        "content": content,
        "validFrom": "2020-09-01T21:00:00+09:00",
        "validTo": valid_to,
        "observedAt": "2020-09-01T21:00:00+09:00",
    }


JEJU_TRIP = memory(8990, "EVENT", "2020년 9월 12일에 제주도 여행을 간다", PAST)
JOB_WORRY = memory(9012, "EPISODE", "이직할지 고민 중이다")
GUITAR = memory(8801, "PROFILE", "기타를 배운다")


def option(trigger_type, question="저번에 말한 거, 어떻게 됐어?", **source):
    return {
        "memoryId": source.get("memoryId"),
        "candidateIndex": source.get("candidateIndex"),
        "triggerType": trigger_type,
        "question": question,
        "invite": "다음엔 그 얘기 하자. 궁금해.",
    }


def options(*items):
    return json.dumps({"options": list(items)})


class FollowUpQuestionApiTests(unittest.TestCase):
    def _post(self, payload, fake_openai):
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
            )
        )
        with (
            patch("app.core.openai_client.OpenAI", return_value=fake_openai),
            patch(
                "app.free_talk.application.memory_service.review_memory_candidates",
                side_effect=lambda drafts, *_: drafts,
            ),
        ):
            return make_client(app).post(MEMORY_CANDIDATES_PATH, json=payload)

    def _fake(self, *follow_up_contents, candidates=True):
        completion = valid_memory_candidate_completion() if candidates else {"candidates": []}
        return FakeOpenAI(
            contents=[json.dumps(completion)],
            follow_up_contents=list(follow_up_contents) or None,
        )

    def _follow_up_prompt(self, fake):
        return json.loads(fake.completions.follow_up_calls[0]["messages"][1]["content"])

    def test_past_event_is_chosen_before_concern_even_when_listed_later(self):
        fake = self._fake(
            options(
                option("CONCERN", memoryId=9012),
                option("PAST_EVENT", "저번에 제주도 간다고 했지? 어땠어?", memoryId=8990),
            )
        )
        # 서버가 날짜를 읽을 수 없어 게이팅이 걸리지 않아도 정렬만으로 보장되는지 본다
        undated_trip = JEJU_TRIP | {"validTo": None, "content": "추석 연휴에 제주도 여행을 간다"}
        payload = valid_memory_candidates_payload(existingMemories=[JOB_WORRY, undated_trip])

        response = self._post(payload, fake)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["followUpQuestion"],
            {
                "memoryId": 8990,
                "candidateIndex": None,
                "triggerType": "PAST_EVENT",
                "question": "저번에 제주도 간다고 했지? 어땠어?",
                "invite": "다음엔 그 얘기 하자. 궁금해.",
            },
        )

    def test_expired_event_hides_other_memories_from_the_model(self):
        fake = self._fake(options(option("CONCERN", memoryId=9012)))
        payload = valid_memory_candidates_payload(existingMemories=[JOB_WORRY, JEJU_TRIP])

        with self.assertLogs(FOLLOW_UP_LOGGER, level="WARNING") as logs:
            response = self._post(payload, fake)

        prompt_memories = self._follow_up_prompt(fake)["existingMemories"]
        self.assertEqual([item["memoryId"] for item in prompt_memories], [8990])
        self.assertEqual(prompt_memories[0]["temporalStatus"], "EXPIRED")
        # 숨긴 기억으로 만든 질문은 받아들이지 않는다
        self.assertEqual(response.json()["data"]["followUpQuestion"], NONE_QUESTION)
        self.assertIn("reason=no_valid_option", logs.output[-1])

    def test_scheduled_date_in_content_gates_when_valid_to_is_missing(self):
        fake = self._fake(options(option("PAST_EVENT", memoryId=8990)))
        payload = valid_memory_candidates_payload(
            existingMemories=[JOB_WORRY, JEJU_TRIP | {"validTo": None}],
        )

        response = self._post(payload, fake)

        prompt_memories = self._follow_up_prompt(fake)["existingMemories"]
        self.assertEqual([item["memoryId"] for item in prompt_memories], [8990])
        self.assertTrue(prompt_memories[0]["scheduledEventPassed"])
        self.assertEqual(response.json()["data"]["followUpQuestion"]["triggerType"], "PAST_EVENT")

    def test_something_already_over_when_mentioned_is_not_a_past_event(self):
        watched = memory(7001, "EVENT", "사용자는 2020-08-30에 코미디 영화를 봤다")
        fake = self._fake(options(option("PAST_EVENT", memoryId=7001)), candidates=False)

        with self.assertLogs(FOLLOW_UP_LOGGER, level="WARNING"):
            response = self._post(valid_memory_candidates_payload(existingMemories=[watched]), fake)

        self.assertFalse(self._follow_up_prompt(fake)["existingMemories"][0]["scheduledEventPassed"])
        self.assertEqual(response.json()["data"]["followUpQuestion"], NONE_QUESTION)

    def test_asked_memories_are_never_shown_or_selected(self):
        fake = self._fake(
            options(option("PAST_EVENT", memoryId=8990), option("HOBBY", memoryId=8801))
        )
        payload = valid_memory_candidates_payload(
            existingMemories=[JEJU_TRIP, GUITAR],
            askedMemoryIds=[8990],
        )

        response = self._post(payload, fake)

        prompt_memories = self._follow_up_prompt(fake)["existingMemories"]
        self.assertEqual([item["memoryId"] for item in prompt_memories], [8801])
        follow_up = response.json()["data"]["followUpQuestion"]
        self.assertEqual((follow_up["memoryId"], follow_up["triggerType"]), (8801, "HOBBY"))

    def test_cut_off_uses_a_new_candidate_and_wins_over_everything(self):
        fake = self._fake(
            options(option("PAST_EVENT", memoryId=8990), option("CUT_OFF", candidateIndex=0))
        )
        payload = valid_memory_candidates_payload(
            existingMemories=[JEJU_TRIP],
            sessionEndedBy="TIME_LIMIT_REACHED",
        )

        response = self._post(payload, fake)

        follow_up = response.json()["data"]["followUpQuestion"]
        self.assertEqual(
            (follow_up["memoryId"], follow_up["candidateIndex"], follow_up["triggerType"]),
            (None, 0, "CUT_OFF"),
        )
        self.assertEqual(self._follow_up_prompt(fake)["sessionEndedBy"], "TIME_LIMIT_REACHED")
        self.assertEqual(len(response.json()["data"]["candidates"]), 1)

    def test_upcoming_event_is_not_accepted_as_past_event(self):
        upcoming = memory(9020, "EVENT", "2099년 9월 23일에 면접이 있다", FUTURE)
        fake = self._fake(options(option("PAST_EVENT", memoryId=9020)), candidates=False)

        with self.assertLogs(FOLLOW_UP_LOGGER, level="WARNING"):
            response = self._post(
                valid_memory_candidates_payload(existingMemories=[upcoming]), fake
            )

        self.assertEqual(response.json()["data"]["followUpQuestion"], NONE_QUESTION)

    def test_nothing_to_ask_returns_default_wording_without_calling_the_model(self):
        fake = self._fake(candidates=False)
        payload = valid_memory_candidates_payload(existingMemories=[GUITAR], askedMemoryIds=[8801])

        response = self._post(payload, fake)

        self.assertEqual(response.json()["data"]["followUpQuestion"], NONE_QUESTION)
        self.assertEqual(len(fake.completions.follow_up_calls), 0)

    def test_empty_options_return_default_wording_without_a_warning(self):
        fake = self._fake(options())

        with self.assertNoLogs(FOLLOW_UP_LOGGER, level="WARNING"):
            response = self._post(valid_memory_candidates_payload(existingMemories=[GUITAR]), fake)

        self.assertEqual(response.json()["data"]["followUpQuestion"], NONE_QUESTION)

    def test_follow_up_failure_never_blocks_candidates(self):
        failures = {
            "generation_failed": AiGenerationFailedError(),
            "response_invalid": "not json",
            "contract_validation": json.dumps({"options": [{"triggerType": "NONE"}]}),
        }
        for reason, content in failures.items():
            with self.subTest(reason=reason):
                fake = self._fake(content)

                with self.assertLogs(FOLLOW_UP_LOGGER, level="WARNING") as logs:
                    response = self._post(
                        valid_memory_candidates_payload(existingMemories=[GUITAR]), fake
                    )

                self.assertEqual(response.status_code, 200)
                data = response.json()["data"]
                self.assertEqual(len(data["candidates"]), 1)
                self.assertEqual(data["followUpQuestion"], NONE_QUESTION)
                self.assertIn(FALLBACK_WORKFLOW, logs.output[-1])
                self.assertIn(f"reason={reason}", logs.output[-1])

    def test_follow_up_call_is_bounded_by_the_auxiliary_timeout_without_retries(self):
        fake = self._fake("not json")
        app = create_app(
            make_settings(
                openrouter_api_key="test-openrouter-key",
                openrouter_model="openrouter-test-model",
                free_talk_auxiliary_timeout_seconds=7.5,
            )
        )

        with (
            patch("app.core.openai_client.OpenAI", return_value=fake) as constructor,
            patch(
                "app.free_talk.application.memory_service.review_memory_candidates",
                side_effect=lambda drafts, *_: drafts,
            ),
            self.assertLogs(FOLLOW_UP_LOGGER, level="WARNING"),
        ):
            make_client(app).post(
                MEMORY_CANDIDATES_PATH,
                json=valid_memory_candidates_payload(existingMemories=[GUITAR]),
            )

        self.assertEqual(len(fake.completions.follow_up_calls), 1)
        timeouts = [call.kwargs.get("timeout") for call in constructor.call_args_list]
        self.assertIn(7.5, timeouts)

    def test_extraction_prompt_is_unchanged_by_follow_up_inputs(self):
        plain = self._fake()
        extended = self._fake()

        self._post(valid_memory_candidates_payload(), plain)
        self._post(
            valid_memory_candidates_payload(
                existingMemories=[JEJU_TRIP],
                askedMemoryIds=[8801],
                sessionEndedBy="USER_CONFIRMED",
            ),
            extended,
        )

        self.assertEqual(
            plain.completions.calls[0]["messages"],
            extended.completions.calls[0]["messages"],
        )

    def test_follow_up_prompt_carries_policy_conversation_and_new_candidates(self):
        fake = self._fake()

        self._post(valid_memory_candidates_payload(existingMemories=[GUITAR]), fake)

        system_prompt = fake.completions.follow_up_calls[0]["messages"][0]["content"]
        self.assertIn(FOLLOW_UP_POLICY_HEADING, system_prompt)
        self.assertIn("Asia/Seoul", system_prompt)
        prompt = self._follow_up_prompt(fake)
        self.assertEqual(prompt["characterId"], "chloe")
        self.assertEqual(len(prompt["conversationHistory"]), 2)
        self.assertEqual(prompt["newCandidates"][0]["candidateIndex"], 0)
        self.assertNotIn("embedding", prompt["newCandidates"][0])

    def test_rejects_invalid_follow_up_inputs(self):
        invalid_overrides = {
            "too_many_memories": {
                "existingMemories": [memory(index, "PROFILE", "기억") for index in range(1, 22)],
            },
            "duplicate_asked_id": {"askedMemoryIds": [5, 5]},
            "non_positive_asked_id": {"askedMemoryIds": [0]},
            "unknown_end_reason": {"sessionEndedBy": "CRASHED"},
            "undefined_memory_field": {"existingMemories": [GUITAR | {"score": 1}]},
        }
        for name, overrides in invalid_overrides.items():
            with self.subTest(name=name):
                fake = self._fake()

                response = self._post(valid_memory_candidates_payload(**overrides), fake)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
                self.assertEqual(len(fake.completions.calls), 0)

    def test_openapi_requires_follow_up_question(self):
        schemas = create_app(make_settings()).openapi()["components"]["schemas"]

        self.assertIn("followUpQuestion", schemas["MemoryCandidatesResponse"]["required"])
        for field in ("existingMemories", "askedMemoryIds", "sessionEndedBy"):
            self.assertIn(field, schemas["MemoryCandidatesRequest"]["properties"])
        self.assertEqual(
            schemas["FollowUpTriggerType"]["enum"],
            ["CUT_OFF", "PAST_EVENT", "CONCERN", "GOAL", "MOOD", "HOBBY", "NONE"],
        )


def askable(memory_id, memory_type, status="WITHIN_TIME_BOUNDS", has_valid_to=False):
    return AskableMemory(memory_id, memory_type, status, has_valid_to)


def proposed(trigger_type, memory_id=None, candidate_index=None, question="어떻게 됐어?"):
    return FollowUpOption(memory_id, candidate_index, trigger_type, question, "다음에 얘기하자.")


class FollowUpRulesTests(unittest.TestCase):
    def test_priority_follows_the_declared_trigger_order(self):
        memories = [askable(index, MemoryType.EVENT) for index in range(1, 6)]
        triggers = [
            FollowUpTriggerType.HOBBY,
            FollowUpTriggerType.MOOD,
            FollowUpTriggerType.GOAL,
            FollowUpTriggerType.CONCERN,
            FollowUpTriggerType.PAST_EVENT,
        ]
        remaining = [proposed(trigger, memory_id=index) for index, trigger in enumerate(triggers, 1)]
        remaining.append(proposed(FollowUpTriggerType.CUT_OFF, candidate_index=0))

        chosen_order = []
        while remaining:
            chosen = select_follow_up(remaining, memories, candidate_count=1)
            chosen_order.append(chosen.trigger_type.value)
            remaining.remove(chosen)

        self.assertEqual(
            chosen_order,
            ["CUT_OFF", "PAST_EVENT", "CONCERN", "GOAL", "MOOD", "HOBBY"],
        )

    def test_equal_priority_keeps_the_first_proposal(self):
        memories = [askable(1, MemoryType.PROFILE), askable(2, MemoryType.PROFILE)]
        first = proposed(FollowUpTriggerType.HOBBY, memory_id=1)
        second = proposed(FollowUpTriggerType.HOBBY, memory_id=2)

        self.assertIs(select_follow_up([first, second], memories, candidate_count=0), first)

    def test_expired_events_gate_the_memories_shown_to_the_model(self):
        expired = askable(1, MemoryType.EVENT, "EXPIRED", has_valid_to=True)
        expired_profile = askable(2, MemoryType.PROFILE, "EXPIRED", has_valid_to=True)
        concern = askable(3, MemoryType.EPISODE)

        self.assertEqual(memories_for_prompt([concern, expired_profile, expired]), [expired])
        self.assertEqual(
            memories_for_prompt([concern, expired_profile]), [concern, expired_profile]
        )

    def test_invalid_proposals_are_rejected(self):
        memories = [
            askable(1, MemoryType.EVENT, "EXPIRED", has_valid_to=True),
            askable(2, MemoryType.PROFILE),
            askable(3, MemoryType.EVENT, "WITHIN_TIME_BOUNDS", has_valid_to=True),
        ]
        rejected = {
            "unknown_memory": proposed(FollowUpTriggerType.HOBBY, memory_id=99),
            "candidate_out_of_range": proposed(FollowUpTriggerType.GOAL, candidate_index=1),
            "both_sources": proposed(FollowUpTriggerType.GOAL, memory_id=2, candidate_index=0),
            "no_source": proposed(FollowUpTriggerType.GOAL),
            "none_trigger": proposed(FollowUpTriggerType.NONE, memory_id=2),
            "past_event_on_profile": proposed(FollowUpTriggerType.PAST_EVENT, memory_id=2),
            "past_event_still_valid": proposed(FollowUpTriggerType.PAST_EVENT, memory_id=3),
            "past_event_on_new_candidate": proposed(
                FollowUpTriggerType.PAST_EVENT, candidate_index=0
            ),
            "cut_off_on_old_memory": proposed(FollowUpTriggerType.CUT_OFF, memory_id=2),
            "exclamation": proposed(FollowUpTriggerType.HOBBY, memory_id=2, question="어땠어!"),
            "blank": proposed(FollowUpTriggerType.HOBBY, memory_id=2, question="  "),
        }
        for name, item in rejected.items():
            with self.subTest(name=name):
                self.assertIsNone(select_follow_up([item], memories, candidate_count=1))

    def test_event_without_valid_to_or_readable_date_may_be_judged_past_by_the_model(self):
        memories = [askable(1, MemoryType.EVENT, "WITHIN_TIME_BOUNDS", has_valid_to=False)]
        item = proposed(FollowUpTriggerType.PAST_EVENT, memory_id=1)

        self.assertIs(select_follow_up([item], memories, candidate_count=0), item)

    def test_server_date_verdict_overrides_the_model_for_events_without_valid_to(self):
        item = proposed(FollowUpTriggerType.PAST_EVENT, memory_id=1)
        verdicts = {"PASSED": True, "UPCOMING": False, "NOT_SCHEDULED": False}
        for status, accepted in verdicts.items():
            with self.subTest(status=status):
                memories = [AskableMemory(1, MemoryType.EVENT, "WITHIN_TIME_BOUNDS", False, status)]

                chosen = select_follow_up([item], memories, candidate_count=0)

                self.assertEqual(chosen is item, accepted)
                self.assertEqual(memories_for_prompt(memories)[0].is_past_event, accepted)

    def test_valid_to_wins_over_the_content_date(self):
        still_valid = AskableMemory(1, MemoryType.EVENT, "WITHIN_TIME_BOUNDS", True, "PASSED")

        self.assertFalse(still_valid.is_past_event)

    def test_scheduled_date_status_reads_calendar_dates_from_content(self):
        observed, today = date(2026, 9, 1), date(2026, 9, 19)
        cases = {
            "사용자는 2026-09-12에 제주도 여행을 간다": "PASSED",
            "사용자는 2026년 9월 12일에 제주도 여행을 간다": "PASSED",
            "사용자는 2026-09-19에 면접이 있다": "UPCOMING",
            "사용자는 2026-10-03부터 2026-10-07까지 오사카에 간다": "UPCOMING",
            "사용자는 2026-09-03부터 2026-09-07까지 오사카에 간다": "PASSED",
            "사용자는 2026-08-30에 코미디 영화를 봤다": "NOT_SCHEDULED",
            "사용자는 2026-09-01에 마라톤에서 우승했다": "NOT_SCHEDULED",
            "사용자는 추석 연휴에 제주도에 간다": "UNKNOWN",
            "사용자는 2026-13-45에 무언가를 한다": "UNKNOWN",
        }
        for content, expected in cases.items():
            with self.subTest(content=content):
                self.assertEqual(scheduled_date_status(content, observed, today), expected)

    def test_scheduled_date_status_needs_an_observation_date(self):
        self.assertEqual(
            scheduled_date_status("2026-09-12에 여행을 간다", None, date(2026, 9, 19)),
            "UNKNOWN",
        )


if __name__ == "__main__":
    unittest.main()
