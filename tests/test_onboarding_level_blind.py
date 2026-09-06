# 온보딩 수준 평가 블라인드 실행기의 집계 경계를 검증한다.
import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

from scripts.evaluate_onboarding_level_blind import load_cases, score, write_manifest


class OnboardingLevelBlindScoreTests(unittest.TestCase):
    def test_fixture_contract_rejects_invalid_cases_before_calls(self):
        fixture = Path(__file__).parent / "fixtures/lan_438_onboarding_blind_cases.json"
        self.assertEqual(len(load_cases(fixture)), 40)
        mutations = [
            lambda cases: cases[0].pop("repeat"),
            lambda cases: cases[0].update(repeat=1),
            lambda cases: cases[0].update(split="unknown"),
            lambda cases: cases[0].update(answers=[1, "", "", ""]),
            lambda cases: cases[0].update(answers=[""]),
            lambda cases: cases[0].update(caseId=cases[1]["caseId"]),
            lambda cases: cases.pop(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            for mutate in mutations:
                cases = json.loads(fixture.read_text())
                mutate(cases)
                path.write_text(json.dumps(cases))
                with self.assertRaises(ValueError):
                    load_cases(path)

    def test_manifest_reuse_requires_matching_execution_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(
                output_dir=Path(directory),
                cases=Path(__file__).parent / "fixtures/lan_438_onboarding_blind_cases.json",
                product_model="product", message_feedback_model="feedback",
                reference_model="reference",
            )
            write_manifest(args)
            path = args.output_dir / "manifest.json"
            original = path.read_text()
            write_manifest(args)
            self.assertEqual(path.read_text(), original)
            for key in (
                "datasetSha256", "rubricSha256", "sessionFeedbackPromptSha256",
                "questionSha256", "productModel", "messageFeedbackModel",
                "referenceModel", "assessmentVersion",
            ):
                manifest = json.loads(original)
                manifest[key] = "changed"
                path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, key):
                    write_manifest(args)
                self.assertEqual(json.loads(path.read_text()), manifest)

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
