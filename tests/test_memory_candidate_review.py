# 기억 후보의 원문 대조 결과와 임베딩 전 검증 경계를 검사한다.
import json
import unittest
from unittest.mock import patch

from tests.test_free_talk_api import (
    FakeOpenAI, make_client, make_settings, valid_memory_candidate_completion,
    valid_memory_candidates_payload,
)
from app.main import create_app


class MemoryCandidateReviewTests(unittest.TestCase):
    def post(self, candidates, reviews, *, source=None):
        payload = valid_memory_candidates_payload()
        if source:
            payload["conversationHistory"][1]["content"] = source
        if not isinstance(reviews, Exception):
            reviews = [{"isPersonal": True, "eventDateIsGrounded": True, "isStableProfile": True,
                        "reason": "Synthetic evidence verdict.", **r} for r in reviews]
        review_content = reviews if isinstance(reviews, Exception) else json.dumps({"reviews": reviews})
        fake = FakeOpenAI(contents=[json.dumps(candidates), review_content])
        settings = make_settings(openrouter_api_key="test-key", openrouter_model="test-model")
        with patch("app.core.openai_client.OpenAI", return_value=fake):
            response = make_client(create_app(settings)).post(
                "/api/v1/free-talk/memory-candidates", json=payload,
            )
        return response, fake

    def test_keeps_explicit_fact_even_when_source_ends_in_question(self):
        for source in (
            "I am studying for a language exam because my employer requires it. You know?",
            "I am studying for a language exam because my employer requires it, you know?",
            "회사 요구 때문에 어학 시험을 준비하고 있어. 무슨 말인지 알겠어？",
        ):
            with self.subTest(source=source):
                content = "사용자는 회사 요구로 어학 시험을 준비한다."
                response, fake = self.post(
                    valid_memory_candidate_completion(memoryType="PROFILE", content=content),
                    [{"candidateIndex": 0, "decision": "KEEP"}], source=source,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(fake.completions.calls), 2)
                self.assertEqual(fake.embeddings.calls[0]["input"], [content])

    def test_reviews_question_presuppositions_before_embedding(self):
        for source in (
            "Where should I go for my usual Saturday walk with Nori?",
            "I wonder where I should go for my usual Saturday walk with Nori?",
            "혹시 노리랑 매주 토요일에 산책할 만한 곳이 어디일까?",
            "노리랑 매주 토요일에 산책해도 될까?",
            "Hello. Where should I go for my usual Saturday walk with Nori?",
        ):
            with self.subTest(source=source):
                response, fake = self.post(
                    valid_memory_candidate_completion(
                        memoryType="PROFILE", content="사용자는 Nori와 매주 토요일에 산책한다.",
                    ),
                    [{"candidateIndex": 0, "decision": "DROP"}], source=source,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(fake.completions.calls), 2)
                self.assertEqual(response.json()["data"]["candidates"], [])
                self.assertEqual(fake.embeddings.calls, [])

    def test_mixed_message_keeps_only_the_explicit_fact(self):
        candidates = valid_memory_candidate_completion(
            memoryType="PROFILE", content="사용자는 채식주의자다.",
        )["candidates"]
        candidates += valid_memory_candidate_completion(
            candidateIndex=1, memoryType="PROFILE", content="사용자는 매주 토요일 산책한다.",
        )["candidates"]
        response, fake = self.post(
            {"candidates": candidates},
            [{"candidateIndex": 0, "decision": "KEEP"},
             {"candidateIndex": 1, "decision": "DROP"}],
            source="I am vegetarian. Where should I go for my usual Saturday walk?",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.embeddings.calls[0]["input"], ["사용자는 채식주의자다."])

    def test_drops_unverified_event_before_embedding(self):
        for source, content in (
            ("I visited a castle once.", "사용자는 성을 방문했다."),
            ("The Atlas game was released yesterday.", "Atlas 게임이 출시됐다."),
        ):
            with self.subTest(source=source):
                response, fake = self.post(
                    valid_memory_candidate_completion(content=content),
                    [{"candidateIndex": 0, "decision": "DROP"}], source=source,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["candidates"], [])
                self.assertEqual(len(fake.completions.calls), 2)
                self.assertEqual(fake.embeddings.calls, [])

    def test_refines_only_content_and_preserves_date_and_sources(self):
        content = "사용자의 여동생은 2026-08-28에 결혼한다."
        response, fake = self.post(
            valid_memory_candidate_completion(content="사용자의 동생은 2026-08-28에 결혼한다."),
            [{"candidateIndex": 0, "decision": "REFINE", "content": content,
              "sourceMessageId": 3002, "quote": "My younger sister"}],
            source="My younger sister is getting married on August 28, 2026.",
        )
        self.assertEqual(response.status_code, 200)
        candidate = response.json()["data"]["candidates"][0]
        self.assertEqual(candidate["content"], content)
        self.assertEqual(candidate["validFrom"], "2026-08-25T20:10:00+09:00")
        self.assertEqual(candidate["sourceMessageIds"], [3002])
        self.assertEqual(fake.embeddings.calls[0]["input"], [content])
        self.assertNotIn("quote", candidate)

    def test_rejects_missing_duplicate_unknown_and_ungrounded_reviews(self):
        for reviews in (
            [],
            [{"candidateIndex": 1, "decision": "KEEP"}],
            [{"candidateIndex": 0, "decision": "KEEP"}] * 2,
            [{"candidateIndex": 0, "decision": "REFINE", "content": "새 사실",
              "sourceMessageId": 3002, "quote": "not in source"}],
            [{"candidateIndex": 0, "decision": "REFINE", "content": "새 사실",
              "sourceMessageId": 3001, "quote": "How was your weekend?"}],
            [{"candidateIndex": 0, "decision": "KEEP", "content": "새 사실"}],
            [{"candidateIndex": 0, "decision": "REFINE", "content": "면접은 2027년이다.",
              "sourceMessageId": 3002, "quote": "I have an interview"}],
            [{"candidateIndex": 0, "decision": "REFINE", "content": "  ",
              "sourceMessageId": 3002, "quote": "I have an interview"}],
            [{"candidateIndex": 0, "decision": "KEEP", "validFrom": "2027-01-01"}],
        ):
            with self.subTest(reviews=reviews):
                response, fake = self.post(valid_memory_candidate_completion(), reviews)
                self.assertEqual(response.status_code, 502)
                self.assertEqual(fake.embeddings.calls, [])

    def test_keeps_supported_candidate_and_reindexes_after_drop(self):
        candidates = valid_memory_candidate_completion()["candidates"]
        candidates += valid_memory_candidate_completion(
            candidateIndex=1, memoryType="PROFILE", content="사용자는 채식주의자다.",
        )["candidates"]
        response, fake = self.post(
            {"candidates": candidates},
            [{"candidateIndex": 0, "decision": "DROP"},
             {"candidateIndex": 1, "decision": "KEEP"}],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([c["candidateIndex"] for c in response.json()["data"]["candidates"]], [0])
        self.assertEqual(fake.embeddings.calls[0]["input"], ["사용자는 채식주의자다."])

    def test_skips_review_and_embedding_for_empty_candidates(self):
        response, fake = self.post({"candidates": []}, [])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(fake.completions.calls), 1)
        self.assertEqual(fake.embeddings.calls, [])

    def test_review_failure_never_embeds_unverified_candidates(self):
        response, fake = self.post(valid_memory_candidate_completion(), TimeoutError())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(fake.embeddings.calls, [])

    def test_ignores_keep_when_subject_or_event_time_is_unsupported(self):
        for verdict in ({"isPersonal": False}, {"eventDateIsGrounded": False}):
            with self.subTest(verdict=verdict):
                response, fake = self.post(
                    valid_memory_candidate_completion(),
                    [{"candidateIndex": 0, "decision": "KEEP", **verdict}],
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["candidates"], [])
                self.assertEqual(fake.embeddings.calls, [])

    def test_keep_restores_only_unambiguous_sibling_detail(self):
        for source, expected in (
            ("My younger sister is getting married.", "여동생"),
            ("My younger brother is getting married.", "남동생"),
            ("내 여동생이 결혼해.", "여동생"),
            ("My younger brother and younger sister are at home.", "동생"),
            ("My brother is getting married. I also have a younger sister.", "동생"),
        ):
            with self.subTest(source=source):
                response, fake = self.post(
                    valid_memory_candidate_completion(content="사용자의 동생이 결혼한다."),
                    [{"candidateIndex": 0, "decision": "KEEP"}], source=source,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(fake.embeddings.calls[0]["input"],
                                 [f"사용자의 {expected}이 결혼한다."])

    def test_ignores_keep_for_one_off_profile(self):
        response, fake = self.post(
            valid_memory_candidate_completion(memoryType="PROFILE", content="사용자는 계획을 저장했다."),
            [{"candidateIndex": 0, "decision": "KEEP", "isStableProfile": False}],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["candidates"], [])
        self.assertEqual(fake.embeddings.calls, [])

    def test_sibling_restoration_does_not_change_other_relatives(self):
        for content in ("사용자의 사촌동생은 매주 수영한다.", "친구의 동생은 매주 수영한다.",
                        "동생은 매주 수영한다."):
            with self.subTest(content=content):
                response, fake = self.post(
                    valid_memory_candidate_completion(memoryType="PROFILE", content=content),
                    [{"candidateIndex": 0, "decision": "KEEP"}],
                    source="My younger cousin swims every week. My younger sister is a teacher.",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(fake.embeddings.calls[0]["input"], [content])

    def test_restores_standalone_sibling_only_with_exclusive_user_source(self):
        response, fake = self.post(
            valid_memory_candidate_completion(content="동생의 결혼식이 2026년 9월 20일에 있다."),
            [{"candidateIndex": 0, "decision": "KEEP"}],
            source="My younger sister is getting married on September 20, 2026.",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.embeddings.calls[0]["input"],
                         ["여동생의 결혼식이 2026년 9월 20일에 있다."])

    def test_restores_sibling_after_event_date(self):
        response, fake = self.post(
            valid_memory_candidate_completion(content="사용자는 2026-09-07에 동생 집에 간다."),
            [{"candidateIndex": 0, "decision": "KEEP"}],
            source="I go to my younger brother home house now.",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.embeddings.calls[0]["input"],
                         ["사용자는 2026-09-07에 남동생 집에 간다."])

    def test_does_not_restore_sibling_with_another_owner(self):
        for content in ("사용자의 아내 동생은 매주 수영한다.", "친구의 동생은 매주 수영한다."):
            with self.subTest(content=content):
                response, fake = self.post(
                    valid_memory_candidate_completion(memoryType="PROFILE", content=content),
                    [{"candidateIndex": 0, "decision": "KEEP"}],
                    source="내 여동생은 의사야. 처남은 매주 수영해.",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(fake.embeddings.calls[0]["input"], [content])
