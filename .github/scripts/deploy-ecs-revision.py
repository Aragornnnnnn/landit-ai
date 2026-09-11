#!/usr/bin/env python3
# 현재 task 설정을 보존해 검증한 이미지 digest만 바꾸고 배포 전후 버전을 기록한다.
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--output", "json"], text=True))


def service_state(cluster, service):
    response = aws("ecs", "describe-services", "--cluster", cluster, "--services", service)
    if response.get("failures") or len(response.get("services", [])) != 1:
        raise ValueError("Expected ECS service is unavailable")
    return response["services"][0]


def stable_identity(service):
    deployments = service.get("deployments", [])
    if (len(deployments) != 1 or deployments[0].get("rolloutState") != "COMPLETED"
            or service.get("desiredCount", 0) < 1 or service.get("pendingCount") != 0
            or service["runningCount"] != service["desiredCount"]):
        raise ValueError("Finish the current application or infrastructure deployment first")
    return service["taskDefinition"], deployments[0]["id"], service["desiredCount"]


def running_digest(cluster, service, definition, container, count):
    arns = aws("ecs", "list-tasks", "--cluster", cluster, "--service-name", service,
               "--desired-status", "RUNNING")["taskArns"]
    if len(arns) != count or not arns or len(arns) > 100:
        raise ValueError("Running task count changed before deployment")
    response = aws("ecs", "describe-tasks", "--cluster", cluster, "--tasks", *arns)
    tasks = response.get("tasks", [])
    if response.get("failures") or len(tasks) != count:
        raise ValueError("Cannot inspect every running task")
    digests = set()
    for task in tasks:
        if task["taskDefinitionArn"] != definition or task["lastStatus"] != "RUNNING":
            raise ValueError("Mixed task revisions are running")
        matches = [item for item in task["containers"] if item["name"] == container]
        if len(matches) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", matches[0].get("imageDigest", "")):
            raise ValueError("The running image digest is unavailable")
        digests.add(matches[0]["imageDigest"])
    if len(digests) != 1:
        raise ValueError("Mixed image digests are running")
    return digests.pop()


def registration(description, container, image):
    definition = copy.deepcopy(description["taskDefinition"])
    for key in ("taskDefinitionArn", "revision", "status", "requiresAttributes", "compatibilities",
                "registeredAt", "registeredBy", "deregisteredAt"):
        definition.pop(key, None)
    matches = [item for item in definition["containerDefinitions"] if item["name"] == container]
    if len(matches) != 1 or re.split(r"[:@]", matches[0]["image"])[0] != image.split("@")[0]:
        raise ValueError("The deployment repository does not match the running application")
    matches[0]["image"] = image
    definition["tags"] = description.get("tags", [])
    return definition


def save_record(path, record):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(path)


def deploy(environ):
    cluster, service = environ["ECS_CLUSTER"], environ["ECS_SERVICE"]
    container, repository = environ["CONTAINER_NAME"], environ["ECR_IMAGE_URI"]
    sha = environ["GITHUB_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or repository.rsplit("/", 1)[-1] != environ["ECR_REPOSITORY"]:
        raise ValueError("A full Git SHA and matching ECR repository are required")
    previous = service_state(cluster, service)
    identity = stable_identity(previous)
    previous_digest = running_digest(cluster, service, identity[0], container, identity[2])
    response = aws("ecr", "describe-images", "--repository-name", environ["ECR_REPOSITORY"],
                   "--image-ids", f"imageTag={sha}")
    digest = response["imageDetails"][0]["imageDigest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("The published SHA does not resolve to an image digest")
    description = aws("ecs", "describe-task-definition", "--task-definition", identity[0], "--include", "TAGS")
    request = registration(description, container, f"{repository}@{digest}")
    record_path = Path(environ["RELEASE_RECORD"])
    record = {"status": "prepared", "git_sha": sha, "cluster": cluster, "service": service,
              "container": container, "previous_task_definition": identity[0],
              "previous_image": f"{repository}@{previous_digest}", "image": f"{repository}@{digest}"}
    save_record(record_path, record)
    if stable_identity(service_state(cluster, service)) != identity:
        raise ValueError("Service changed while preparing the task definition")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as task_file:
        json.dump(request, task_file)
        task_file.flush()
        registered = aws("ecs", "register-task-definition", "--cli-input-json", f"file://{task_file.name}")
    definition = registered["taskDefinition"]["taskDefinitionArn"]
    record.update(status="registered", task_definition=definition)
    save_record(record_path, record)
    if stable_identity(service_state(cluster, service)) != identity:
        raise ValueError("Service changed before deployment; the new revision was not applied")
    deployed = aws("ecs", "update-service", "--cluster", cluster, "--service", service,
                   "--task-definition", definition)["service"]
    primary = [item for item in deployed["deployments"]
               if item["status"] == "PRIMARY" and item["taskDefinition"] == definition]
    if len(primary) != 1 or deployed["taskDefinition"] != definition:
        raise ValueError("ECS did not return the expected deployment")
    record.update(status="deploying", deployment_id=primary[0]["id"])
    save_record(record_path, record)
    outputs = {"deployment_id": primary[0]["id"], "deployment_created_at": primary[0]["createdAt"],
               "task_definition": definition, "image_digest": digest}
    with open(environ["GITHUB_OUTPUT"], "a") as stream:
        for key, value in outputs.items():
            stream.write(f"{key}={value}\n")
    print("Created an image-pinned ECS revision; runtime verification is still required.")


if __name__ == "__main__":
    deploy(os.environ)
