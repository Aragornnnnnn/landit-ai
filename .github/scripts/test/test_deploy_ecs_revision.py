# ECS revision 배포가 기존 설정과 롤백 digest를 보존하고 동시 변경을 거부하는지 검증한다.
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("deploy", Path(__file__).parents[1] / "deploy-ecs-revision.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeployEcsRevisionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.container = "api"
        self.reads = 0
        self.change_before_update = False
        self.registration = None
        self.updates = []
        self.repository = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/prod-landit-api"
        self.old_digest = "sha256:" + "a" * 64
        self.new_digest = "sha256:" + "b" * 64

    def environment(self):
        return {"ECS_CLUSTER": "cluster", "ECS_SERVICE": "service", "CONTAINER_NAME": self.container,
                "ECR_IMAGE_URI": self.repository, "ECR_REPOSITORY": "prod-landit-api",
                "GITHUB_SHA": "c" * 40, "RELEASE_RECORD": str(self.path / "record.json"),
                "GITHUB_OUTPUT": str(self.path / "outputs")}

    def description(self):
        return {"taskDefinition": {"taskDefinitionArn": "arn:task/api:1", "revision": 1,
            "status": "ACTIVE", "requiresAttributes": [], "compatibilities": ["FARGATE"],
            "registeredAt": "yesterday", "registeredBy": "operator", "family": "prod-landit-api",
            "taskRoleArn": "arn:task-role", "executionRoleArn": "arn:execution-role",
            "networkMode": "awsvpc", "requiresCompatibilities": ["FARGATE"], "cpu": "256", "memory": "512",
            "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
            "containerDefinitions": [{"name": self.container, "image": self.repository + ":latest",
                "environment": [{"name": "EXAMPLE", "value": "must-not-be-published"}], "stopTimeout": 120},
                {"name": "sidecar", "image": "sidecar@sha256:unchanged"}]},
            "tags": [{"key": "Project", "value": "landit"}, {"key": "Environment", "value": "prod"}]}

    def aws(self, *args):
        operation = args[1]
        if operation == "describe-services":
            self.reads += 1
            definition = "arn:task/api:other" if self.change_before_update and self.reads == 3 else "arn:task/api:1"
            return {"services": [{"taskDefinition": definition, "desiredCount": 1, "runningCount": 1,
                "pendingCount": 0, "deployments": [{"id": "old", "rolloutState": "COMPLETED"}]}]}
        if operation == "list-tasks":
            return {"taskArns": ["arn:task/one"]}
        if operation == "describe-tasks":
            return {"tasks": [{"taskDefinitionArn": "arn:task/api:1", "lastStatus": "RUNNING",
                "containers": [{"name": self.container, "imageDigest": self.old_digest}]}]}
        if operation == "describe-images":
            self.assertIn("imageTag=" + "c" * 40, args)
            return {"imageDetails": [{"imageDigest": self.new_digest}]}
        if operation == "describe-task-definition":
            self.assertIn("TAGS", args)
            return self.description()
        if operation == "register-task-definition":
            self.registration = json.loads(Path(args[-1].removeprefix("file://")).read_text())
            return {"taskDefinition": {"taskDefinitionArn": "arn:task/api:2"}}
        if operation == "update-service":
            self.updates.append(args)
            return {"service": {"taskDefinition": "arn:task/api:2", "deployments": [{"status": "PRIMARY",
                "taskDefinition": "arn:task/api:2", "id": "new", "createdAt": "2026-09-11T00:00:00Z"}]}}
        raise AssertionError(args)

    def test_image_only_revision_and_actual_previous_digest_are_preserved(self):
        for container in ("api", "worker"):
            with self.subTest(container=container), patch.object(deploy, "aws", self.aws):
                self.container = container
                deploy.deploy(self.environment())
                expected = self.description()["taskDefinition"]
                self.assertEqual(self.registration["runtimePlatform"], expected["runtimePlatform"])
                self.assertEqual(self.registration["containerDefinitions"][1], expected["containerDefinitions"][1])
                self.assertEqual(self.registration["containerDefinitions"][0]["environment"],
                                 expected["containerDefinitions"][0]["environment"])
                self.assertEqual(self.registration["containerDefinitions"][0]["image"],
                                 self.repository + "@" + self.new_digest)
                self.assertNotIn("revision", self.registration)
                record_text = (self.path / "record.json").read_text()
                self.assertNotIn("must-not-be-published", record_text)
                record = json.loads(record_text)
                self.assertEqual(record["previous_image"], self.repository + "@" + self.old_digest)
                self.assertEqual(record["task_definition"], "arn:task/api:2")
                self.assertIn("image_digest=" + self.new_digest, (self.path / "outputs").read_text())

    def test_changed_service_after_registration_never_updates_service(self):
        self.change_before_update = True
        with patch.object(deploy, "aws", self.aws), self.assertRaises(ValueError):
            deploy.deploy(self.environment())
        self.assertEqual(self.updates, [])
        self.assertEqual(json.loads((self.path / "record.json").read_text())["status"], "registered")

    def test_repository_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            deploy.registration(self.description(), self.container, "other-repository@" + self.new_digest)


if __name__ == "__main__":
    unittest.main()
