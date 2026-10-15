#!/usr/bin/env python3
"""Fail-closed TTL lease guard for environments that must not run forever.

Staging is the one such environment now (it is woken for validation and must
sleep again; see ``.github/workflows/staging-ttl-guard.yml`` and
``scripts/staging_state_machine.py``, which uses this module's ``evaluate`` and
``lease_path``). The demo and preview profiles that once shared this guard have
been retired. Safety comes from a single SSM lease: an absolute UTC
``expires-at`` timestamp at ``/aether/{profile}/{env}/lifecycle/expires-at``.

This module is dual-purpose:

  1. Static analysis (no AWS credentials required). ``check()`` verifies that
     ``lease_path`` still produces the canonical SSM parameter name. Run as
     ``python scripts/release/ephemeral_ttl_guard.py``.

  2. Live lease decision logic. ``evaluate()`` is the single fail-closed
     decision: a missing lease, an unreadable lease, a malformed lease and an
     expired lease ALL mean "expired". ``--check`` exits non-zero on an expired
     lease so a cron can fail closed; ``--dry-run`` prints the decision without
     ever touching AWS. ``read_lease`` is injected so unit tests never call
     AWS.

Usage:
  python scripts/release/ephemeral_ttl_guard.py            # lease-path format check
  python scripts/release/ephemeral_ttl_guard.py --check    # same, explicit
  python scripts/release/ephemeral_ttl_guard.py --profile staging --env staging --check
  python scripts/release/ephemeral_ttl_guard.py --profile staging --env staging --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, main_guard, repo_root  # noqa: E402

# ---------------------------------------------------------------------------
# SSM lease path — the single source of truth for the parameter name. Mirrors
# .github/workflows/staging-ttl-guard.yml's /aether/staging/lifecycle/awake-until
# naming, with the profile and env kept as separate segments so an environment
# whose name differs from its profile stays on the same format.
# ---------------------------------------------------------------------------
LEASE_PATH_TEMPLATE = "/aether/{profile}/{env}/lifecycle/expires-at"
LEASE_PATH_PATTERN = re.compile(r"^/aether/[^/]+/[^/]+/lifecycle/expires-at$")

# Canonical name the structural check pins to, so a future change to the
# template cannot silently drift the format both the cron and operators rely on.
EXPECTED_STAGING_LEASE = "/aether/staging/staging/lifecycle/expires-at"

# The fail-closed enforcement action returned by evaluate() for an expired env.
ACTION_NONE = "none"
ACTION_ENFORCE = "scale-to-zero + floor-zeroing"


def lease_path(profile: str, env: str) -> str:
    """Build the SSM parameter name for an environment's expiry lease."""
    return LEASE_PATH_TEMPLATE.format(profile=profile, env=env)


def parse_lease(raw_text) -> datetime | None:
    """Parse the ISO-8601 ``expires-at`` value; None on absent/malformed input."""
    if raw_text is None:
        return None
    raw = str(raw_text).strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def is_expired(expires_at: datetime | None, now: datetime) -> bool:
    """Pure, deterministic expiry check. None fails closed."""
    if expires_at is None:
        return True
    return now >= expires_at


def evaluate(profile: str, env: str, read_lease, now: datetime) -> dict:
    """Fail-closed TTL decision for one environment.

    A missing lease, an unreadable lease, a malformed lease and an expired
    lease ALL mean "expired" — an environment nobody can account for must never
    be reported live.
    """
    path = lease_path(profile, env)
    try:
        raw = read_lease(profile, env)
    except Exception as exc:  # unreadable lease -> expired (fail closed)
        return _decision(profile, env, path, expired=True,
                         reason=f"lease unreadable: {exc}")
    parsed = parse_lease(raw)
    if parsed is None:
        return _decision(profile, env, path, expired=True,
                         reason="no parseable expires-at lease")
    if is_expired(parsed, now):
        return _decision(profile, env, path, expired=True,
                         reason="lease has expired")
    return _decision(profile, env, path, expired=False, reason=None,
                     expires_at=parsed,
                     remaining_seconds=int((parsed - now).total_seconds()))


def _decision(profile: str, env: str, path: str, *, expired: bool, reason,
              expires_at=None, remaining_seconds: int = 0) -> dict:
    return {
        "profile": profile,
        "env": env,
        "lease_path": path,
        "expired": bool(expired),
        "action": ACTION_ENFORCE if expired else ACTION_NONE,
        "reason": reason,
        "expires_at": expires_at,
        "remaining_seconds": remaining_seconds,
    }


def read_lease_aws(profile: str, env: str) -> str | None:
    """Read the SSM lease via the AWS CLI. None on absent or unreadable lease.

    Every failure mode returns None, which evaluate() treats as expired — the
    fail-closed default. No exception escapes: a broken, throttled or
    unauthorised call must never read as a live lease.
    """
    proc = subprocess.run(
        ["aws", "ssm", "get-parameter", "--name", lease_path(profile, env),
         "--query", "Parameter.Value", "--output", "text"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    raw = (proc.stdout or "").strip()
    if not raw or raw == "None":
        return None
    return raw


# ---------------------------------------------------------------------------
# Repo-structural check (no AWS credentials required)
# ---------------------------------------------------------------------------
def check() -> int:
    r = Reporter("TTL LEASE GUARD — lease path format")

    r.require(
        lease_path("staging", "staging") == EXPECTED_STAGING_LEASE,
        f"staging lease path is {EXPECTED_STAGING_LEASE}",
        f"staging lease path changed: {lease_path('staging', 'staging')}",
    )
    r.require(
        bool(LEASE_PATH_PATTERN.match(lease_path("staging", "staging"))),
        "lease path matches /aether/{profile}/{env}/lifecycle/expires-at",
        f"lease path no longer matches the canonical format: {LEASE_PATH_TEMPLATE}",
    )

    return r.finish()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_decision(d: dict) -> None:
    print(f"TTL lease decision for {d['profile']}/{d['env']}")
    print(f"  lease path: {d['lease_path']}")
    print(f"  expired: {str(d['expired']).lower()}")
    print(f"  action: {d['action']}")
    if d["reason"]:
        print(f"  reason: {d['reason']}")
    print(f"ephemeral_expired={str(d['expired']).lower()}")
    print(f"ephemeral_action={d['action']}")
    print(f"ephemeral_lease_path={d['lease_path']}")
    if d["reason"]:
        print(f"ephemeral_reason={d['reason']}")


def _cli_read_lease(args):
    if args.dry_run:
        def fake_read_lease(profile, env):
            # A dry run never touches AWS: the lease is read from the
            # environment when provided, otherwise simulated as absent.
            return os.environ.get("EPHEMERAL_LEASE")
        return fake_read_lease
    return read_lease_aws


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ephemeral_ttl_guard",
        description="Fail-closed TTL lease guard (staging).",
    )
    parser.add_argument("--profile", help="deployment profile (staging)")
    parser.add_argument("--env", help="environment name (e.g. staging)")
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero on an expired/absent lease (or on a structural failure)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the decision and would-be actions without executing any AWS call")
    args = parser.parse_args(argv)

    if args.profile or args.env:
        if not (args.profile and args.env):
            print("error: --profile and --env must be given together", file=sys.stderr)
            return 2
        decision = evaluate(args.profile, args.env, _cli_read_lease(args),
                            datetime.now(timezone.utc))
        _print_decision(decision)
        if args.check and decision["expired"]:
            return 1
        return 0

    # Lease-path format check — no AWS credentials needed.
    return check()


if __name__ == "__main__":
    main_guard(main)
