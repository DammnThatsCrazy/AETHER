#!/usr/bin/env bash
set -euo pipefail

repository_name="aether-access-mcp"
digest="${1:-}"
if [[ $# -ne 1 || ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'Usage: %s sha256:<64 lowercase hex characters>\n' "${0##*/}" >&2
  exit 2
fi

aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [[ -z "$aws_region" ]]; then
  printf 'Set AWS_REGION or AWS_DEFAULT_REGION before verifying the image scan.\n' >&2
  exit 2
fi

timeout_seconds="${ACCESS_MCP_SCAN_TIMEOUT_SECONDS:-600}"
poll_seconds="${ACCESS_MCP_SCAN_POLL_SECONDS:-10}"
if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]] || (( timeout_seconds < 1 || timeout_seconds > 3600 )); then
  printf 'ACCESS_MCP_SCAN_TIMEOUT_SECONDS must be an integer from 1 through 3600.\n' >&2
  exit 2
fi
if [[ ! "$poll_seconds" =~ ^[0-9]+$ ]] || (( poll_seconds < 1 || poll_seconds > 60 )); then
  printf 'ACCESS_MCP_SCAN_POLL_SECONDS must be an integer from 1 through 60.\n' >&2
  exit 2
fi
if ! command -v aws >/dev/null 2>&1; then
  printf 'Required command not found: aws\n' >&2
  exit 2
fi

if ! published_digest="$(aws ecr describe-images \
  --repository-name "$repository_name" \
  --image-ids "imageDigest=$digest" \
  --query 'imageDetails[0].imageDigest' \
  --output text \
  --region "$aws_region" 2>/dev/null)"; then
  printf 'Could not verify that digest %s exists in ECR repository %s.\n' "$digest" "$repository_name" >&2
  exit 1
fi
if [[ "$published_digest" != "$digest" ]]; then
  printf 'ECR did not return the requested immutable digest for repository %s.\n' "$repository_name" >&2
  exit 1
fi

start_seconds=$SECONDS
while true; do
  if scan_summary="$(aws ecr describe-image-scan-findings \
    --repository-name "$repository_name" \
    --image-id "imageDigest=$digest" \
    --query '[imageScanStatus.status, imageScanFindings.findingSeverityCounts.HIGH || `0`, imageScanFindings.findingSeverityCounts.CRITICAL || `0`]' \
    --output text \
    --region "$aws_region" 2>&1)"; then
    read -r scan_status high_count critical_count <<< "$scan_summary"
    if [[ ! "$high_count" =~ ^[0-9]+$ || ! "$critical_count" =~ ^[0-9]+$ ]]; then
      printf 'ECR returned missing or malformed severity counts for digest %s.\n' "$digest" >&2
      exit 1
    fi

    case "$scan_status" in
      COMPLETE)
        if (( high_count > 0 || critical_count > 0 )); then
          printf 'ECR scan rejected digest %s: HIGH=%s CRITICAL=%s.\n' "$digest" "$high_count" "$critical_count" >&2
          exit 1
        fi
        printf '%s\n' "$digest"
        exit 0
        ;;
      IN_PROGRESS|PENDING)
        ;;
      *)
        printf 'ECR scan for digest %s ended in non-accepted status: %s.\n' "$digest" "${scan_status:-<missing>}" >&2
        exit 1
        ;;
    esac
  else
    if [[ "$scan_summary" != *ScanNotFoundException* ]]; then
      printf 'Could not read ECR scan findings for digest %s.\n' "$digest" >&2
      exit 1
    fi
  fi

  elapsed_seconds=$((SECONDS - start_seconds))
  if (( elapsed_seconds >= timeout_seconds )); then
    printf 'Timed out waiting for ECR scan completion for digest %s after %s seconds.\n' "$digest" "$timeout_seconds" >&2
    exit 1
  fi
  remaining_seconds=$((timeout_seconds - elapsed_seconds))
  sleep_seconds="$poll_seconds"
  if (( sleep_seconds > remaining_seconds )); then
    sleep_seconds="$remaining_seconds"
  fi
  sleep "$sleep_seconds"
done
