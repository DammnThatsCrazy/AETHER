#!/usr/bin/env bash
# Initialise Terraform with a deterministic lockfile and bounded provider retry.
# Provider registry and GitHub release assets occasionally reset connections;
# retries handle that transient failure without ever accepting lockfile drift.
set -euo pipefail

if [[ ! -f .terraform.lock.hcl ]]; then
  echo '::error::.terraform.lock.hcl is required before Terraform init' >&2
  exit 1
fi

lock_before="$(sha256sum .terraform.lock.hcl | cut -d' ' -f1)"
mkdir -p "${TF_PLUGIN_CACHE_DIR:-$HOME/.terraform.d/plugin-cache}"

success=false
for attempt in 1 2 3; do
  if terraform init -lockfile=readonly "$@"; then
    success=true
    break
  fi
  if [[ "$attempt" -lt 3 ]]; then
    sleep "$((attempt * 10))"
  fi
done

if [[ "$success" != true ]]; then
  echo '::error::Terraform init failed after three attempts; refusing to continue' >&2
  exit 1
fi

lock_after="$(sha256sum .terraform.lock.hcl | cut -d' ' -f1)"
if [[ "$lock_before" != "$lock_after" ]]; then
  echo '::error::Terraform init changed .terraform.lock.hcl; refusing non-deterministic provider selection' >&2
  exit 1
fi
