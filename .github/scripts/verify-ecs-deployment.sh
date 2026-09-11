#!/usr/bin/env bash
# 새 ECS PRIMARY deployment의 기동 실패와 안정화를 검증한다.
set -euo pipefail

: "${ECS_CLUSTER:?ECS_CLUSTER is required}"
: "${ECS_SERVICE:?ECS_SERVICE is required}"
: "${DEPLOYMENT_ID:?DEPLOYMENT_ID is required}"
: "${DEPLOYMENT_CREATED_AT:?DEPLOYMENT_CREATED_AT is required}"
: "${TASK_DEFINITION:?TASK_DEFINITION is required}"
: "${IMAGE_DIGEST:?IMAGE_DIGEST is required}"
: "${CONTAINER_NAME:?CONTAINER_NAME is required}"

POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-10}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-30}"

describe_service() {
  aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --output json
}

print_service_events() {
  describe_service | jq '{services: [.services[]? | {serviceName, status, desiredCount, runningCount, pendingCount, deployments, events: (.events[0:10] // [])}]}'
}

new_deployment_tasks() {
  local status arns task_arns=""
  for status in RUNNING PENDING STOPPED; do
    arns="$(aws ecs list-tasks --cluster "$ECS_CLUSTER" --service-name "$ECS_SERVICE" --desired-status "$status" --output json)"
    task_arns="$task_arns $(jq -r '.taskArns[]?' <<< "$arns")"
  done

  if [ -z "${task_arns// /}" ]; then
    printf '{"tasks":[]}'
    return
  fi

  aws ecs describe-tasks --cluster "$ECS_CLUSTER" --tasks $task_arns --output json \
    | jq --arg deployment_created_at "$DEPLOYMENT_CREATED_AT" '{tasks: [.tasks[]? | select((.createdAt // .startedAt // "") >= $deployment_created_at)]}'
}

print_task_diagnostics() {
  local tasks_json="$1"
  echo "Tasks created by the new deployment"
  jq '{tasks: [.tasks[]? | {taskArn, taskDefinitionArn, lastStatus, desiredStatus, createdAt, startedAt, stoppedAt, stopCode, stoppedReason, containers: [.containers[]? | {name, essential, exitCode, reason, logStreamName}]}]}' <<< "$tasks_json"
}

fail_deployment() {
  local reason="$1" tasks_json="${2:-}"
  if [ -z "$tasks_json" ]; then
    tasks_json='{"tasks":[]}'
  fi
  echo "$reason"
  echo "ECS service state and recent events"
  print_service_events
  print_task_diagnostics "$tasks_json"
  exit 1
}

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  service_json="$(describe_service)"
  if ! jq -e '.services[0]' >/dev/null <<< "$service_json"; then
    fail_deployment "ECS service not found"
  fi

  primary="$(jq -c --arg deployment_id "$DEPLOYMENT_ID" '.services[0].deployments[]? | select(.id == $deployment_id and .status == "PRIMARY")' <<< "$service_json" | head -n 1)"
  if [ -z "$primary" ]; then
    fail_deployment "New PRIMARY ECS deployment not found"
  fi

  failed_tasks="$(jq -r '.failedTasks // 0' <<< "$primary")"
  case "$failed_tasks" in
    "" | "None" | "null" | *[!0-9]*) failed_tasks=0 ;;
  esac
  rollout_state="$(jq -r '.rolloutState // "UNKNOWN"' <<< "$primary")"
  desired_count="$(jq -r '.services[0].desiredCount // -1' <<< "$service_json")"
  running_count="$(jq -r '.services[0].runningCount // -1' <<< "$service_json")"
  deployment_count="$(jq -r '.services[0].deployments | length' <<< "$service_json")"

  echo "ECS deployment poll $attempt/$MAX_ATTEMPTS"
  jq --arg deployment_id "$DEPLOYMENT_ID" '{service: .services[0] | {serviceName, status, desiredCount, runningCount, pendingCount}, primaryDeployment: [.services[0].deployments[]? | select(.id == $deployment_id)]}' <<< "$service_json"

  tasks_json="$(new_deployment_tasks)"
  print_task_diagnostics "$tasks_json"

  if [ "$rollout_state" = "FAILED" ]; then
    fail_deployment "PRIMARY ECS deployment failed" "$tasks_json"
  fi
  if [ "$failed_tasks" -gt 0 ]; then
    fail_deployment "PRIMARY ECS deployment has failed tasks" "$tasks_json"
  fi
  if jq -e '[.tasks[]? | select(.lastStatus == "STOPPED") | select(.stopCode == "EssentialContainerExited" or ([.containers[]? | select(.essential == true and (.exitCode? != null) and (.exitCode != 0))] | length > 0))] | length > 0' >/dev/null <<< "$tasks_json"; then
    fail_deployment "New stopped task indicates startup failure" "$tasks_json"
  fi

  if [ "$desired_count" -lt 1 ]; then
    fail_deployment "Production deployment must keep a running application" "$tasks_json"
  fi
  if [ "$(jq -r '.services[0].taskDefinition' <<< "$service_json")" != "$TASK_DEFINITION" ] || \
    [ "$(jq -r '.taskDefinition' <<< "$primary")" != "$TASK_DEFINITION" ]; then
    fail_deployment "The expected task revision was replaced by another deployment" "$tasks_json"
  fi

  if [ "$deployment_count" -eq 1 ] && [ "$running_count" -eq "$desired_count" ] && [ "$rollout_state" = "COMPLETED" ]; then
    if ! jq -e --arg task_definition "$TASK_DEFINITION" --arg digest "$IMAGE_DIGEST" \
      --arg container "$CONTAINER_NAME" --argjson desired "$desired_count" '
      [.tasks[] | select(.lastStatus == "RUNNING")] | unique_by(.taskArn)
      | length == $desired and all(.[]; .taskDefinitionArn == $task_definition
        and ([.containers[] | select(.name == $container)] | length == 1
          and .[0].imageDigest == $digest))' >/dev/null <<< "$tasks_json"; then
      fail_deployment "Running task revision or image digest does not match the release" "$tasks_json"
    fi
    if [ -z "${HEALTH_CHECK_URL:-}" ]; then
      fail_deployment "HEALTH_CHECK_URL is required when desired count is greater than 0" "$tasks_json"
    fi
    curl --fail --silent --show-error --retry 3 --retry-delay 3 --retry-connrefused "$HEALTH_CHECK_URL" >/dev/null
    if [ -n "${RELEASE_RECORD:-}" ]; then
      jq '.status = "verified" | .verification = "task revision, image digest, and HTTP health"' \
        "$RELEASE_RECORD" > "${RELEASE_RECORD}.tmp"
      mv "${RELEASE_RECORD}.tmp" "$RELEASE_RECORD"
    fi
    echo "ECS service is stable; task revision, digest, and health verified (not a functional smoke test)"
    exit 0
  fi

  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    sleep "$POLL_INTERVAL_SECONDS"
  fi
done

fail_deployment "ECS service did not become stable within 5 minutes"
