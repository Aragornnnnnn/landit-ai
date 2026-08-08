#!/usr/bin/env bash
# EC2 배포 helper의 SSM 명령과 상태 처리를 fake AWS CLI로 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="$ROOT_DIR/.github/scripts/deploy-ec2-service.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [ ! -f "$SCRIPT" ]; then
  echo "Missing deploy helper: $SCRIPT"
  exit 1
fi

cat > "$TMP_DIR/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$*" >> "$AWS_CALL_LOG"

if [ -n "${MOCK_AWS_ERROR:-}" ]; then
  echo "$MOCK_AWS_ERROR" >&2
  exit 1
fi

case "$1 $2" in
  "ssm send-command")
    printf '%s\n' "command-123"
    ;;
  "ssm get-command-invocation")
    invocation_count=0
    if [ -f "$AWS_INVOCATION_COUNT" ]; then
      invocation_count="$(cat "$AWS_INVOCATION_COUNT")"
    fi
    invocation_count=$((invocation_count + 1))
    printf '%s' "$invocation_count" > "$AWS_INVOCATION_COUNT"

    IFS=',' read -r -a statuses <<< "$MOCK_STATUSES"
    status_index=$((invocation_count - 1))
    status="${statuses[$status_index]:-${statuses[${#statuses[@]} - 1]}}"

    if [[ "$status" == error:* ]]; then
      error_code="${status#error:}"
      echo "An error occurred ($error_code): ${MOCK_INVOCATION_ERROR_DETAIL:-command is not available}" >&2
      exit 255
    fi
    printf '%s\n' "$status"
    ;;
  *)
    echo "unexpected aws command: $*" >&2
    exit 1
    ;;
esac
EOF
chmod +x "$TMP_DIR/aws"

SHA="0123456789abcdef0123456789abcdef01234567"

run_helper() {
  local max_attempts="${MAX_ATTEMPTS:-3}"

  PATH="$TMP_DIR:$PATH" \
    AWS_CALL_LOG="$TMP_DIR/aws-calls" \
    AWS_INVOCATION_COUNT="$TMP_DIR/invocation-count" \
    POLL_INTERVAL_SECONDS=0 \
    MAX_ATTEMPTS="$max_attempts" \
    bash "$SCRIPT" "$@"
}

assert_failure_without_aws_call() {
  local name="$1"
  shift
  rm -f "$TMP_DIR/aws-calls" "$TMP_DIR/invocation-count"

  set +e
  output="$(run_helper "$@" 2>&1)"
  status=$?
  set -e

  if [ "$status" -eq 0 ] || [ -f "$TMP_DIR/aws-calls" ]; then
    echo "$name should fail before AWS is called"
    echo "$output"
    exit 1
  fi
}

MOCK_STATUSES=Success assert_failure_without_aws_call missing_instance ai "$SHA"
EC2_INSTANCE_ID=i-123 MOCK_STATUSES=Success assert_failure_without_aws_call missing_service "" "$SHA"
EC2_INSTANCE_ID=i-123 MOCK_STATUSES=Success assert_failure_without_aws_call missing_image_tag ai
EC2_INSTANCE_ID=i-123 MOCK_STATUSES=Success assert_failure_without_aws_call invalid_service worker "$SHA"
EC2_INSTANCE_ID=i-123 MOCK_STATUSES=Success assert_failure_without_aws_call invalid_sha ai short-sha

rm -f "$TMP_DIR/aws-calls" "$TMP_DIR/invocation-count"
success_output="$(EC2_INSTANCE_ID=i-123 MOCK_STATUSES=Pending,InProgress,Success run_helper ai "$SHA")"
expected_command="ssm send-command --instance-ids i-123 --document-name AWS-RunShellScript --parameters commands=sudo /opt/landit/bin/deploy-service ai $SHA --query Command.CommandId --output text"

if ! grep -Fxq "$expected_command" "$TMP_DIR/aws-calls"; then
  echo "send-command did not receive only the expected deployment command"
  cat "$TMP_DIR/aws-calls"
  exit 1
fi
if [ "$(grep -Fc 'ssm get-command-invocation' "$TMP_DIR/aws-calls")" -ne 3 ]; then
  echo "command status was not polled with the returned command ID"
  cat "$TMP_DIR/aws-calls"
  exit 1
fi
expected_status_command="ssm get-command-invocation --command-id command-123 --instance-id i-123 --query Status --output text"
if [ "$(grep -Fxc "$expected_status_command" "$TMP_DIR/aws-calls")" -ne 3 ]; then
  echo "command invocation must query status without command logs"
  cat "$TMP_DIR/aws-calls"
  exit 1
fi
if ! grep -Fq "SSM command command-123 status: Success" <<< "$success_output"; then
  echo "successful command status was not reported"
  echo "$success_output"
  exit 1
fi

rm -f "$TMP_DIR/aws-calls" "$TMP_DIR/invocation-count"
eventual_success_output="$(EC2_INSTANCE_ID=i-123 MAX_ATTEMPTS=4 MOCK_STATUSES=error:InvocationDoesNotExist,Pending,InProgress,Success run_helper ai "$SHA")"
if ! grep -Fq "SSM command command-123 status: Success" <<< "$eventual_success_output"; then
  echo "InvocationDoesNotExist should be retried until the command succeeds"
  echo "$eventual_success_output"
  exit 1
fi
if [ "$(grep -Fxc "$expected_status_command" "$TMP_DIR/aws-calls")" -ne 4 ]; then
  echo "InvocationDoesNotExist should consume one bounded polling attempt"
  cat "$TMP_DIR/aws-calls"
  exit 1
fi

rm -f "$TMP_DIR/aws-calls" "$TMP_DIR/invocation-count"
set +e
eventual_timeout_output="$(EC2_INSTANCE_ID=i-123 MAX_ATTEMPTS=2 MOCK_STATUSES=error:InvocationDoesNotExist MOCK_INVOCATION_ERROR_DETAIL=super-secret run_helper ai "$SHA" 2>&1)"
eventual_timeout_status=$?
set -e
if [ "$eventual_timeout_status" -eq 0 ] || ! grep -Fq "SSM command command-123 did not complete within 2 attempts" <<< "$eventual_timeout_output" || grep -Fq "super-secret" <<< "$eventual_timeout_output"; then
  echo "InvocationDoesNotExist retries should be bounded without leaking AWS output"
  echo "$eventual_timeout_output"
  exit 1
fi

rm -f "$TMP_DIR/aws-calls" "$TMP_DIR/invocation-count"
set +e
access_denied_output="$(EC2_INSTANCE_ID=i-123 MOCK_STATUSES=error:AccessDeniedException MOCK_INVOCATION_ERROR_DETAIL=super-secret run_helper ai "$SHA" 2>&1)"
access_denied_status=$?
set -e
if [ "$access_denied_status" -eq 0 ] || ! grep -Fq "Unable to retrieve SSM command status" <<< "$access_denied_output" || grep -Fq "super-secret" <<< "$access_denied_output" || [ "$(grep -Fxc "$expected_status_command" "$TMP_DIR/aws-calls")" -ne 1 ]; then
  echo "non-retryable command invocation errors should fail once without leaking AWS output"
  echo "$access_denied_output"
  exit 1
fi

for terminal_status in Failed TimedOut Cancelled; do
  rm -f "$TMP_DIR/aws-calls" "$TMP_DIR/invocation-count"
  set +e
  output="$(EC2_INSTANCE_ID=i-123 MOCK_STATUSES="$terminal_status" run_helper ai "$SHA" 2>&1)"
  status=$?
  set -e

  if [ "$status" -eq 0 ] || ! grep -Fq "SSM command command-123 status: $terminal_status" <<< "$output"; then
    echo "$terminal_status command status should fail the deployment"
    echo "$output"
    exit 1
  fi
done

rm -f "$TMP_DIR/aws-calls" "$TMP_DIR/invocation-count"
set +e
secret_output="$(EC2_INSTANCE_ID=i-123 MOCK_STATUSES=Success MOCK_AWS_ERROR=super-secret run_helper ai "$SHA" 2>&1)"
secret_status=$?
set -e
if [ "$secret_status" -eq 0 ] || grep -Fq "super-secret" <<< "$secret_output"; then
  echo "AWS command output leaked to deployment logs"
  exit 1
fi

WORKFLOW="$ROOT_DIR/.github/workflows/deploy-dev-worker.yml"
workflow_concurrency="$(sed -n '/^concurrency:/,/^jobs:/p' "$WORKFLOW")"
if ! rg -q '^concurrency:' <<<"$workflow_concurrency" || ! rg -q 'group:[[:space:]]*deploy-develop-worker' <<<"$workflow_concurrency" || ! rg -q 'cancel-in-progress:[[:space:]]*false' <<<"$workflow_concurrency"; then
  echo 'develop worker workflow must serialize runs without cancellation.' >&2
  exit 1
fi

ecs_verify_line="$(rg -n -F 'name: Verify ECS service' "$WORKFLOW" | cut -d: -f1)"
ec2_mirror_line="$(rg -n -F 'name: Deploy the same image to develop EC2' "$WORKFLOW" | cut -d: -f1)"
if [ -z "$ecs_verify_line" ] || [ -z "$ec2_mirror_line" ] || [ "$ecs_verify_line" -ge "$ec2_mirror_line" ]; then
  echo 'develop worker workflow must mirror to EC2 only after ECS verification.' >&2
  exit 1
fi

echo "deploy-ec2-service tests passed"
