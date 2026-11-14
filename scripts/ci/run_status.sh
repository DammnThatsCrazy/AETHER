#!/usr/bin/env bash
# Print a workflow run's status: `run_status.sh <owner/repo> <run_id> [grace_seconds]`.
#
# A just-dispatched run can answer HTTP 404 for a few seconds (staging
# lifecycle run 43387214569 read its sleep plan 0.3 s after dispatch). Only a
# 404, and only within the grace window (default 120 s, counted from the first
# 404 seen for this run), prints `lookup_pending` and exits 0. Any other error,
# or a 404 after the window, prints gh's error and exits 1.
set -uo pipefail

repo="$1"
run_id="$2"
grace="${3:-120}"
state_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
first_404="${state_dir}/run-status-${run_id}.first404"
error_file="${state_dir}/run-status-${run_id}.err"

if status="$(gh api "repos/${repo}/actions/runs/${run_id}" --jq '.status' 2>"$error_file")"; then
  printf '%s\n' "$status"
  exit 0
fi
if grep -q "HTTP 404" "$error_file"; then
  now="$(date -u +%s)"
  [ -s "$first_404" ] || printf '%s\n' "$now" >"$first_404"
  if [ "$now" -lt "$(( $(cat "$first_404") + grace ))" ]; then
    echo lookup_pending
    exit 0
  fi
fi
cat "$error_file" >&2
echo "::error::could not read run ${run_id} status" >&2
exit 1
