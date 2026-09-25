# 로컬 지연 HTTP 응답으로 평가의 남은 시간과 실제 SDK 재시도 상한을 검증한다.
import json
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.conversation.application import next_message_service as service
from tests.test_assessment_output_budget import assessment_request
from tests.test_conversation_api import make_settings, valid_level_assessment


def http_completion(content):
    return {
        "id": "gen-local-test", "object": "chat.completion", "created": 1, "model": "test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
    }


@contextmanager
def local_provider(responses):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            delay, status, payload = responses[min(len(requests) - 1, len(responses) - 1)]
            time.sleep(delay)
            body = json.dumps(payload).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class AssessmentHttpBudgetTests(unittest.TestCase):
    def settings(self, base_url, budget):
        return make_settings(openrouter_base_url=base_url, openrouter_api_key="local-test",
                             openrouter_model="test", session_level_assessment_budget_seconds=budget)

    def test_delayed_initial_response_times_out_without_sdk_retry(self):
        with local_provider([(0.6, 200, http_completion('{}'))]) as (url, requests):
            started = time.monotonic()
            with self.assertRaises(service.AiGenerationFailedError):
                service.generate_session_level_assessment(assessment_request(), self.settings(url, 0.2))
            elapsed = time.monotonic() - started
            self.assertEqual(len(requests), 1)
            self.assertLess(elapsed, 0.6)

    def test_core_retry_uses_remaining_budget_instead_of_resetting_it(self):
        with local_provider([(0.15, 200, http_completion('{}')),
                             (0.7, 200, http_completion('{}'))]) as (url, requests):
            started = time.monotonic()
            with self.assertLogs("app.conversation.llm.assessment_observation") as logs:
                with self.assertRaises(service.AiGenerationFailedError):
                    service.generate_session_level_assessment(assessment_request(), self.settings(url, 0.4))
            elapsed = time.monotonic() - started
            self.assertEqual(len(requests), 2)
            self.assertLess(elapsed, 0.65)
            self.assertIn("assessment_session_mismatch", logs.output[-1])
            self.assertIn("terminal_failure", logs.output[-1])

    def test_format_fallback_and_core_retry_make_at_most_four_requests(self):
        unsupported = {"error": {"message": "response_format is not supported"}}
        valid = {"sessionId": 100, "levelAssessment": valid_level_assessment()}
        with local_provider([(0, 400, unsupported), (0, 400, unsupported),
                             (0, 200, http_completion('{}')),
                             (0, 200, http_completion(json.dumps(valid)))]) as (url, requests):
            with self.assertLogs("app.conversation.llm.assessment_observation") as logs:
                result = service.generate_session_level_assessment(assessment_request(), self.settings(url, 3))
            self.assertIsNotNone(result.levelAssessment)
            self.assertEqual(len(requests), 4)
            self.assertEqual([request.get("response_format", {}).get("type") for request in requests],
                             ["json_schema", "json_object", None, None])
            diagnostic = json.loads(logs.records[-1].getMessage().split("assessment_diagnostics ", 1)[1])
            self.assertEqual([c["attempt"] for c in diagnostic["calls"]], [1, 2, 3, 4])
            self.assertEqual([c["stage"] for c in diagnostic["calls"]], [1, 1, 1, 2])
