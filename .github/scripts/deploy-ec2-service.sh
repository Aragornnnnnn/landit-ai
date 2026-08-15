#!/usr/bin/env bash
# 동일한 컨테이너 이미지를 SSM Run Command로 개발 EC2 서비스에 배포한다.
set -euo pipefail

: "${EC2_INSTANCE_ID:?EC2_INSTANCE_ID is required}"

service="${1:-}"
image_tag="${2:-}"

case "$service" in
  api | ai) ;;
  *)
    echo "service must be api or ai" >&2
    exit 1
    ;;
esac

if [ -z "$image_tag" ]; then
  echo "image tag is required" >&2
  exit 1
fi

if [[ ! "$image_tag" =~ ^[0-9a-f]{40}$ ]]; then
  echo "image tag must be a 40-character lowercase SHA" >&2
  exit 1
fi

POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-10}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-30}"

if ! command_id="$(aws ssm send-command \
  --instance-ids "$EC2_INSTANCE_ID" \
  --document-name develop-landit-ec2-deploy \
  --parameters "service=$service,imageSha=$image_tag" \
  --query 'Command.CommandId' \
  --output text 2>&1)"; then
  echo "Unable to start SSM deployment command" >&2
  exit 1
fi

if [ -z "$command_id" ] || [ "$command_id" = "None" ]; then
  echo "SSM deployment command ID was not returned" >&2
  exit 1
fi

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  if ! status="$(aws ssm get-command-invocation \
    --command-id "$command_id" \
    --instance-id "$EC2_INSTANCE_ID" \
    --query Status \
    --output text 2>&1)"; then
    if [[ "$status" == *"(InvocationDoesNotExist)"* ]]; then
      if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
        sleep "$POLL_INTERVAL_SECONDS"
      fi
      continue
    fi

    echo "Unable to retrieve SSM command status" >&2
    exit 1
  fi

  case "$status" in
    Success)
      echo "SSM command $command_id status: Success"
      exit 0
      ;;
    Failed | TimedOut | Cancelled)
      echo "SSM command $command_id status: $status" >&2
      exit 1
      ;;
  esac

  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    sleep "$POLL_INTERVAL_SECONDS"
  fi
done

echo "SSM command $command_id did not complete within $MAX_ATTEMPTS attempts" >&2
exit 1
