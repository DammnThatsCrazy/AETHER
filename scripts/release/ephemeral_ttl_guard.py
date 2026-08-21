#!/usr/bin/env python3
"""Fail-closed TTL lifecycle guard for the demo/preview ephemeral profiles.

demo and preview are integration-class profiles that must never run forever
(``config/deployment_profiles.yaml`` marks both ``ttl_cleanup_required: true``;
preview additionally ``forbids`` ``run-forever``). Safety comes from a single
SSM lease, an absolute UTC ``expires-at`` timestamp written by
``scripts/release/ephemeral_env.py provision`` at
``/aether/{profile}/{env}/lifecycle/expires-at``.

This module is dual-purpose:

  1. Static analysis (no AWS credentials required). ``check()`` verifies the
     repo-structural invariants of the lifecycle: the fail-closed cron
     ``.github/workflows/ephemeral-ttl-guard.yml`` exists, its matrix covers
     both demo and preview, and ``lease_path`` produces the canonical SSM
     parameter name. Run as ``python scripts/release/ephemeral_ttl_guard.py``.

  2. Live lease decision logic. ``evaluate()`` is the single fail-closed
     decision: a missing lease, an unreadable lease, a malformed lease and an
     expired lease ALL mean "expired". ``--check`` exits non-zero on an expired
     lease so a cron can fail closed; ``--dry-run`` prints the decision without
     ever touching AWS. ``read_lease`` is injected so unit tests never call
     AWS.

Usage:
  python scripts/release/ephemeral_ttl_guard.py            # repo-structural check
  python scripts/release/ephemeral_ttl_guard.py --check    # same, explicit
  python scripts/release/ephemeral_ttl_guard.py --profile demo --env demo --check
  python scripts/release/ephemeral_ttl_guard.py --profile demo --env demo --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, main_guard, repo_root  # noqa: E402

# ---------------------------------------------------------------------------
# SSM lease path — the single source of truth for the parameter name. Mirrors
# .github/workflows/staging-ttl-guard.yml's /aether/staging/lifecycle/awake-until
# naming, with the profile and env kept as separate segments so a future
# per-PR preview env (env != profile) stays on the same format.
# ---------------------------------------------------------------------------
LEASE_PATH_TEMPLATE = "/aether/{profile}/{env}/lifecycle/expires-at"
LEASE_PATH_PATTERN = re.compile(r"^/aether/[^/]+/[^/]+/lifecycle/expires-at$")

# Canonical names the structural check pins to, so a future change to the
# template cannot silently drift the format both the cron and operators rely on.
EXPECTED_DEMO_LEASE = "/aether/demo/demo/lifecycle/expires-at"
EXPECTED_PREVIEW_LEASE = "/aether/preview/preview/lifecycle/expires-at"

# The fail-closed enforcement action returned by evaluate() for an expired env.
ACTION_NONE = "none"
ACTION_ENFORCE = "scale-to-zero + floor-zeroing"

WORKFLOW_REL = ".github/workflows/ephemeral-ttl-guard.yml"
REQUIRED_PROFILES = ("demo", "preview")


def lease_path(profile: str, env: str) -> str:
    """Build the SSM parameter name for an ephemeral env's expiry lease."""
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
    """Fail-closed TTL decision for one ephemeral environment.

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
def _matrix_pairs(data) -> list[tuple[str, str]]:
    """Extract (profile, env) pairs from the ephemeral-ttl-guard matrix."""
    pairs: list[tuple[str, str]] = []
    if not isinstance(data, dict):
        return pairs
    jobs = data.get("jobs") or {}
    guard = jobs.get("guard") or {}
    matrix = (guard.get("strategy") or {}).get("matrix") or {}
    if not isinstance(matrix, dict):
        return pairs
    for item in matrix.get("include") or []:
        if isinstance(item, dict) and item.get("profile") and item.get("env"):
            pairs.append((str(item["profile"]), str(item["env"])))
    plist = matrix.get("profile") or []
    elist = matrix.get("env") or []
    if isinstance(plist, list) and isinstance(elist, list):
        pairs.extend((str(p), str(e)) for p, e in zip(plist, elist))
    return list(dict.fromkeys(pairs))


def check() -> int:
    r = Reporter("EPHEMERAL TTL GUARD — demo/preview leases must auto-expire")

    root = repo_root()

    # 1. The fail-closed cron exists ------------------------------------------
    workflow = root / WORKFLOW_REL
    if not workflow.exists():
        r.fail(f"{WORKFLOW_REL} is missing — the hourly cron is the TTL tripwire")
        return r.finish()
    r.ok(f"{WORKFLOW_REL} exists")

    # 2. Its matrix covers both demo and preview ------------------------------
    try:
        with workflow.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        r.fail(f"{WORKFLOW_REL} is not readable YAML: {exc}")
        return r.finish()

    covered = {p for p, _ in _matrix_pairs(data)}
    for prof in REQUIRED_PROFILES:
        r.require(
            prof in covered,
            f"ephemeral TTL cron matrix covers {prof}",
            f"ephemeral TTL cron matrix is missing {prof}",
        )

    # 3. The lease-path format is correct -------------------------------------
    r.require(
        lease_path("demo", "demo") == EXPECTED_DEMO_LEASE,
        f"demo lease path is {EXPECTED_DEMO_LEASE}",
        f"demo lease path changed: {lease_path('demo', 'demo')}",
    )
    r.require(
        lease_path("preview", "preview") == EXPECTED_PREVIEW_LEASE,
        f"preview lease path is {EXPECTED_PREVIEW_LEASE}",
        f"preview lease path changed: {lease_path('preview', 'preview')}",
    )
    r.require(
        bool(LEASE_PATH_PATTERN.match(lease_path("demo", "demo")))
        and bool(LEASE_PATH_PATTERN.match(lease_path("preview", "preview"))),
        "lease path matches /aether/{profile}/{env}/lifecycle/expires-at",
        f"lease path no longer matches the canonical format: {LEASE_PATH_TEMPLATE}",
    )

    return r.finish()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_decision(d: dict) -> None:
    print(f"ephemeral TTL decision for {d['profile']}/{d['env']}")
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
        description="Fail-closed TTL guard for the demo/preview ephemeral profiles.",
    )
    parser.add_argument("--profile", help="deployment profile (demo|preview)")
    parser.add_argument("--env", help="environment name (e.g. demo, preview)")
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

    # Repo-structural check — the parity-style gate, no AWS credentials needed.
    return check()


if __name__ == "__main__":
    main_guard(main)
