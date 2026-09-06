# 온보딩 수준 평가 블라인드 실행기의 집계 경계를 검증한다.
import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

from scripts.evaluate_onboarding_level_blind import score


class OnboardingLevelBlindScoreTests(unittest.TestCase):
    def test_missing_level_assessment_is_counted_as_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            self._write_jsonl(
                output_dir / "reference.jsonl",
                [{
                    "caseId": "missing-core",
                    "status": "SUCCESS",
                    "reference": {
                        "assessable": True,
                        "allowedLevelRange": [2, 3],
                        "messages": [],
                    },
                    "usage": {},
                }],
            )
            self._write_jsonl(
                output_dir / "product.jsonl",
                [{
                    "caseId": "missing-core",
                    "split": "holdout",
                    "run": 1,
                    "status": "SUCCESS",
                    "levelAssessment": None,
                    "bePolicy": {
                        "source": "FALLBACK",
                        "changeType": "NOT_APPLIED",
                        "assessedLevel": None,
                    },
                    "latencySeconds": 1.0,
                    "calls": [{"finishReason": "stop", "usage": {}}],
                }],
            )

            with redirect_stdout(io.StringIO()):
                score(
                    Namespace(output_dir=output_dir),
                    [{"caseId": "missing-core", "split": "holdout", "repeat": False}],
                )

            summary = json.loads(
                (output_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["execution"]["validLevelAssessment"], 0)
            self.assertEqual(summary["execution"]["missingLevelAssessment"], 1)
            self.assertEqual(summary["primary"]["comparable"], 0)
            self.assertEqual(summary["expectedBeFallbacks"], 1)
            self.assertEqual(
                summary["failureReasons"],
                {"MISSING_LEVEL_ASSESSMENT": 1},
            )

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
