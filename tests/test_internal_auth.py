# 내부 토큰 적용 시 AI API가 외부 호출을 거절하고 헬스체크를 유지하는지 검증한다.
import unittest

from app.main import create_app
from tests.test_conversation_api import make_client, make_settings


class InternalAuthTests(unittest.TestCase):
    def test_all_api_groups_require_token_before_body_validation(self):
        client = make_client(create_app(make_settings(landit_ai_internal_token="test-token")))
        for path in ("/api/v1/conversation/session-feedback", "/api/v1/free-talk/turn",
                     "/api/v1/pronunciation/sentence-analysis"):
            for headers in ({}, {"X-Landit-Internal-Token": "wrong"}):
                with self.subTest(path=path, headers=headers):
                    response = client.post(path, json={}, headers=headers)
                    self.assertEqual(response.status_code, 401)
                    self.assertNotIn("test-token", response.text)
        self.assertEqual(client.get("/health").status_code, 200)

    def test_authorized_and_transition_requests_reach_normal_api_validation(self):
        for token, headers in (("test-token", {"X-Landit-Internal-Token": "test-token"}),
                               (None, {})):
            client = make_client(create_app(make_settings(landit_ai_internal_token=token)))
            self.assertEqual(client.post("/api/v1/conversation/session-feedback",
                                         json={}, headers=headers).status_code, 400)
