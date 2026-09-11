#!/usr/bin/env bash
# ECS 배포 검증 스크립트의 성공과 즉시 실패 조건을 mock AWS CLI로 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="$ROOT_DIR/.github/scripts/verify-ecs-deployment.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cat > "$TMP_DIR/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  *"describe-services"*) printf '%s\n' "$MOCK_SERVICE_JSON" ;;
  *"list-tasks"*) printf '%s\n' "$MOCK_TASK_LIST_JSON" ;;
  *"describe-tasks"*) printf '%s\n' "$MOCK_TASKS_JSON" ;;
  *) exit 1 ;;
esac
EOF
cat > "$TMP_DIR/curl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$TMP_DIR/aws" "$TMP_DIR/curl"

service_json() {
  local rollout_state="$1" failed_tasks="$2" running_count="$3" deployment_count="$4"
  printf '{"services":[{"serviceName":"api","taskDefinition":"arn:task-definition/api:1","status":"ACTIVE","desiredCount":1,"runningCount":%s,"pendingCount":0,"deployments":[' "$running_count"
  printf '{"id":"ecs-svc/primary","taskDefinition":"arn:task-definition/api:1","status":"PRIMARY","createdAt":"2026-07-11T00:00:00Z","rolloutState":"%s","failedTasks":%s,"desiredCount":1,"runningCount":%s,"pendingCount":0}' "$rollout_state" "$failed_tasks" "$running_count"
  if [ "$deployment_count" = 2 ]; then
    printf ',{"id":"ecs-svc/old","status":"ACTIVE","createdAt":"2026-07-10T00:00:00Z","rolloutState":"COMPLETED","failedTasks":0,"desiredCount":0,"runningCount":0,"pendingCount":0}'
  fi
  printf '],"events":[]}]}'
}

run_case() {
  local name="$1" expected_status="$2" expected_text="$3"
  shift 3
  set +e
  local output
  output="$(PATH="$TMP_DIR:$PATH" ECS_CLUSTER=cluster ECS_SERVICE=service HEALTH_CHECK_URL=https://health.example \
    TASK_DEFINITION=arn:task-definition/api:1 IMAGE_DIGEST=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa CONTAINER_NAME=api \
    DEPLOYMENT_ID=ecs-svc/primary DEPLOYMENT_CREATED_AT=2026-07-11T00:00:00Z \
    POLL_INTERVAL_SECONDS=0 MAX_ATTEMPTS=1 bash "$SCRIPT" 2>&1)"
  local status=$?
  set -e
  if [ "$status" -ne "$expected_status" ] || ! grep -Fq "$expected_text" <<< "$output"; then
    echo "$name failed with status $status"
    echo "$output"
    exit 1
  fi
}

MOCK_TASK_LIST_JSON='{"taskArns":[]}'
MOCK_TASKS_JSON='{"tasks":[]}'
export MOCK_SERVICE_JSON MOCK_TASK_LIST_JSON MOCK_TASKS_JSON

MOCK_SERVICE_JSON="$(service_json COMPLETED null 1 1)"
MOCK_TASK_LIST_JSON='{"taskArns":["arn:task/new"]}'
MOCK_TASKS_JSON='{"tasks":[{"taskArn":"arn:task/new","taskDefinitionArn":"arn:task-definition/api:1","lastStatus":"RUNNING","createdAt":"2026-07-11T00:00:01Z","containers":[{"name":"api","imageDigest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}]}'
run_case stable 0 "ECS service is stable"
MOCK_TASKS_JSON="${MOCK_TASKS_JSON/sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}"
run_case wrong_digest 1 "image digest does not match the release"
MOCK_TASKS_JSON='{"tasks":[]}'
run_case missing_running_task 1 "image digest does not match the release"

MOCK_SERVICE_JSON="$(service_json IN_PROGRESS 1 0 2)"
run_case failed_tasks 1 "PRIMARY ECS deployment has failed tasks"

MOCK_SERVICE_JSON="$(service_json IN_PROGRESS '"None"' 0 2)"
run_case nullable_failed_tasks 1 "ECS service did not become stable within 5 minutes"

MOCK_SERVICE_JSON="$(service_json IN_PROGRESS '""' 0 2)"
run_case empty_failed_tasks 1 "ECS service did not become stable within 5 minutes"

MOCK_SERVICE_JSON="$(service_json IN_PROGRESS 0 0 2)"
MOCK_TASK_LIST_JSON='{"taskArns":["arn:task/new"]}'
MOCK_TASKS_JSON='{"tasks":[{"taskArn":"arn:task/new","taskDefinitionArn":"arn:task-definition/api:1","lastStatus":"STOPPED","startedAt":"2026-07-11T00:00:01Z","stopCode":"EssentialContainerExited","stoppedReason":"Essential container exited","containers":[{"name":"api","essential":true,"exitCode":0,"reason":"error"}]}]}'
run_case essential_container_exited 1 "stopped task indicates startup failure"

MOCK_TASKS_JSON='{"tasks":[{"taskArn":"arn:task/new","taskDefinitionArn":"arn:task-definition/api:1","lastStatus":"STOPPED","createdAt":"2026-07-11T00:00:01Z","startedAt":null,"stopCode":"TaskFailedToStart","stoppedReason":"Container exited","containers":[{"name":"api","essential":true,"exitCode":1,"reason":"error"}]}]}'
run_case nonzero_exit_code 1 "stopped task indicates startup failure"

MOCK_TASKS_JSON='{"tasks":[{"taskArn":"arn:task/old","taskDefinitionArn":"arn:task-definition/api:1","lastStatus":"STOPPED","createdAt":"2026-07-10T00:00:01Z","startedAt":null,"stopCode":"EssentialContainerExited","stoppedReason":"Old deployment","containers":[{"name":"api","essential":true,"exitCode":1,"reason":"error"}]}]}'
run_case old_stopped_task 1 "ECS service did not become stable within 5 minutes"
