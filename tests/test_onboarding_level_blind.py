# 온보딩 수준 평가 블라인드 실행기의 집계 경계를 검증한다.
import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import evaluate_onboarding_level_blind as runner
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
                product_model="product",
                reference_model="reference",
            )
            write_manifest(args)
            path = args.output_dir / "manifest.json"
            original = path.read_text()
            write_manifest(args)
            self.assertEqual(path.read_text(), original)
            for key in (
                "datasetSha256", "rubricSha256", "sessionLevelAssessmentPromptSha256",
                "questionSha256", "productModel", "productEndpoint", "coreRetryPromptSha256",
                "referenceModel", "assessmentVersion",
            ):
                manifest = json.loads(original)
                manifest[key] = "changed"
                path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, key):
                    write_manifest(args)
                self.assertEqual(json.loads(path.read_text()), manifest)

    def test_product_calls_independent_assessment_and_preserves_factory_timeout(self):
        fixture = Path(__file__).parent / "fixtures/lan_438_onboarding_blind_cases.json"
        case = load_cases(fixture)[0]
        completion = SimpleNamespace(
            id="request", usage=None,
            choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content="{}")
            )],
        )
        client = Mock()
        client.chat.completions.create.return_value = completion
        original_factory = runner.next_message_service.create_openai_client

        def assess(request, settings):
            self.assertIsInstance(request, runner.SessionLevelAssessmentRequest)
            self.assertEqual(settings.openrouter_model, "product-model")
            wrapped = runner.next_message_service.create_openai_client(settings, timeout=9.5)
            wrapped.chat.completions.create(model=settings.openrouter_model)
            return SimpleNamespace(levelAssessment=None)

        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(
                output_dir=Path(directory), aws_profile="test", ssm_key="test",
                product_model="product-model", repeat_runs=1, limit=None,
            )
            with (
                patch.object(runner, "api_key", return_value="test-key"),
                patch.object(runner, "create_openai_client", return_value=client) as factory,
                patch.object(runner, "generate_session_level_assessment", side_effect=assess) as evaluate,
                patch.object(runner.next_message_service, "generate_message_feedback") as feedback,
                patch.object(runner.next_message_service, "generate_session_feedback") as summary,
                redirect_stdout(io.StringIO()),
            ):
                runner.run_product(args, [case])
            evaluate.assert_called_once()
            feedback.assert_not_called()
            summary.assert_not_called()
            self.assertEqual(factory.call_args.kwargs, {"timeout": 9.5})
            self.assertIs(runner.next_message_service.create_openai_client, original_factory)
            row = runner.read_jsonl(args.output_dir / "product.jsonl")[0]
            self.assertEqual(row["status"], "SUCCESS")
            self.assertEqual(len(row["calls"]), 1)
            self.assertNotIn("messageFeedbackStatuses", row)

    def test_reference_reuse_rejects_mismatched_input_and_duplicate_cases(self):
        fixture = Path(__file__).parent / "fixtures/lan_438_onboarding_blind_cases.json"
        cases = load_cases(fixture)
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.mkdir()
            target.mkdir()
            args = Namespace(
                output_dir=target, reference_dir=source, cases=fixture,
                product_model="product", reference_model="reference",
            )
            write_manifest(args)
            manifest = json.loads((target / "manifest.json").read_text())
            manifest["datasetSha256"] = "mismatch"
            (source / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "datasetSha256"):
                runner.reuse_reference(args, cases)
            manifest["datasetSha256"] = runner.file_sha256(fixture)
            (source / "manifest.json").write_text(json.dumps(manifest))
            rows = [{"caseId": case["caseId"], "status": "FAILED"} for case in cases]
            self._write_jsonl(source / "reference.jsonl", [rows[0]] * len(cases))
            with self.assertRaisesRegex(ValueError, "exactly once"):
                runner.reuse_reference(args, cases)
            self._write_jsonl(source / "reference.jsonl", rows)
            runner.reuse_reference(args, cases)
            self.assertEqual((source / "reference.jsonl").read_bytes(), (target / "reference.jsonl").read_bytes())
            stored = json.loads((target / "manifest.json").read_text())
            self.assertEqual(stored["referenceReuse"]["sha256"], runner.file_sha256(source / "reference.jsonl"))
            with self.assertRaises(FileExistsError):
                runner.reuse_reference(args, cases)

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
            references = runner.read_jsonl(output_dir / "reference.jsonl")
            references[0]["usage"] = {"cost": 2.0}
            self._write_jsonl(output_dir / "reference.jsonl", references)
            (output_dir / "manifest.json").write_text(json.dumps({
                "referenceReuse": {"sha256": runner.file_sha256(output_dir / "reference.jsonl")}
            }))
            with redirect_stdout(io.StringIO()):
                score(Namespace(output_dir=output_dir), [])
            execution = json.loads((output_dir / "summary.json").read_text())["execution"]
            self.assertEqual(execution["referenceCostUsd"], "0.00")
            self.assertEqual(execution["historicalReferenceCostUsd"], "2.00")
            self.assertEqual(execution["referenceModelCalls"], 0)
            self.assertEqual(execution["reusedReferenceResults"], 1)

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
