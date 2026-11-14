#!/usr/bin/env bash
# Dispatch a workflow: `dispatch_workflow.sh <workflow> [gh workflow run args...]`.
#
# Prints gh's output (which carries the created run URL) on success. On failure
# it prints that output to stderr with an error annotation and exits 1, so a
# caller's `out="$(dispatch_workflow.sh ...)"` under `set -e` can never end a
# step silently (staging lifecycle run 43462809460 did). It never retries: a
# dispatch that errors after GitHub created the run could otherwise start a
# duplicate plan, apply or delivery.
set -uo pipefail

if output="$(gh workflow run "$@" 2>&1)"; then
  printf '%s\n' "$output"
  exit 0
fi
printf '%s\n' "$output" >&2
echo "::error::workflow dispatch failed; see the gh output above" >&2
exit 1
