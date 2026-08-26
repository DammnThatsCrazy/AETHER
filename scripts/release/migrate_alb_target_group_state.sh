#!/usr/bin/env bash
# Migrate the pre-split backend target-group state address to the literal
# lifecycle resource selected by the deployment profile. This must run after
# backend init and before plan; it is state-only and never calls AWS.
set -euo pipefail

profile="${1:?usage: migrate_alb_target_group_state.sh PROFILE}"
case "$profile" in
  staging) target='module.alb.aws_lb_target_group.backend[0]' ;;
  production-lean|production-scale|enterprise-isolated|demo|preview)
    target='module.alb.aws_lb_target_group.backend_replacement[0]' ;;
  *) echo "unsupported deployment profile: $profile" >&2; exit 2 ;;
esac

legacy='module.alb.aws_lb_target_group.backend'
state_list="$(terraform state list)"
if ! grep -Fxq "$legacy" <<<"$state_list"; then
  exit 0
fi
if grep -Fxq "$target" <<<"$state_list"; then
  echo "refusing target-group state migration: both $legacy and $target exist" >&2
  exit 1
fi
terraform state mv -lock-timeout=5m "$legacy" "$target"
