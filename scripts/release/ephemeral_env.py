#!/usr/bin/env python3
"""Provision and teardown TTL leases for the demo/preview ephemeral profiles.

The ephemeral profiles (demo, preview) must never run forever
(``config/deployment_profiles.yaml`` marks both ``ttl_cleanup_required: true``;
preview additionally ``forbids`` ``run-forever``). Safety is a single SSM lease
— an absolute UTC ``expires-at`` timestamp at
``/aether/{profile}/{env}/lifecycle/expires-at``:

  - ``provision`` writes a fresh lease (``expires-at`` = now + TTL) and
    validates the environment is reachable.
  - ``teardown`` scales the environment to zero, drops autoscaling floors so
    nothing scales it straight back up, and removes the lease. It FAILS CLOSED
    when the lease is missing, because a teardown that found nothing to close
    must not silently succeed and leave the env running.

The lease is written as an ABSOLUTE UTC deadline so it expires by the passage
of time — there is no state to clean up and no way for a forgotten lease to
persist. ``.github/workflows/ephemeral-ttl-guard.yml`` enforces the window
hourly, treating a missing or unparseable lease as expired.

The lease semantics (``lease_path``, ``is_expired``, ``evaluate``) are imported
from ``scripts/release/ephemeral_ttl_guard.py`` so there is one source of
truth.

Usage:
  python scripts/release/ephemeral_env.py provision --profile demo --env demo
  python scripts/release/ephemeral_env.py provision --profile demo --env demo --ttl-hours 6 --dry-run
  python scripts/release/ephemeral_env.py teardown --profile preview --env preview --dry-run
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ephemeral_ttl_guard import evaluate, is_expired, lease_path, parse_lease  # noqa: E402

DEFAULT_TTL_HOURS = 4
MIN_TTL_HOURS = 1
MAX_TTL_HOURS = 8

ALLOWED_PROFILES = ("demo", "preview")


def _cli(profile: str, env: str) -> tuple[str, ...]:
    """The AWS CLI command prefix for one ephemeral env's SSM lease."""
    return ("aws", "ssm", "--region", "us-east-1")


def _run(cmd: list, dry_run: bool, *, check=True) -> int:
    """Run a command, printing it first. Dry runs print the would-be command."""
    print("would-run:" if dry_run else "run:", " ".join(cmd))
    if dry_run:
        return 0
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        sys.exit(proc.returncode or 1)
    if proc.stdout.strip():
        print(proc.stdout.strip())
    return proc.returncode


def _read_lease_cli(profile: str, env: str) -> str | None:
    """Read the SSM lease directly (returns None on absent/unreadable)."""
    from ephemeral_ttl_guard import read_lease_aws
    return read_lease_aws(profile, env)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def provision(args) -> int:
    """Write the SSM lease (expires-at = now + TTL) and validate reachability."""
    if args.dry_run:
        print(f"[dry-run] would provision a {args.ttl_hours}h TTL lease for "
              f"{args.profile}/{args.env} at {lease_path(args.profile, args.env)} "
              f"(expires-at {_now_utc()})")
        return 0

    # Validate reachability FIRST so we never write a lease for an env we
    # cannot even talk to. Read the current lease (if any) so a failed write
    # does not silently leave a stale lease in place.
    current = _read_lease_cli(args.profile, args.env)

    expires_at = datetime.now(timezone.utc) + timedelta(hours=args.ttl_hours)
    value = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    cmd = [
        *_cli(args.profile, args.env),
        "put-parameter",
        "--name", lease_path(args.profile, args.env),
        "--type", "String",
        "--overwrite",
        "--value", value,
        "--description", f"ephemeral {args.profile}/{args.env} TTL lease (expires {value})",
    ]
    _run(cmd, args.dry_run)

    # Read it back and confirm the env is live on the new lease.
    back = _read_lease_cli(args.profile, args.env)
    parsed = parse_lease(back)
    if not is_expired(parsed, datetime.now(timezone.utc)):
        print(f"provisioned {args.profile}/{args.env} TTL lease at "
              f"{lease_path(args.profile, args.env)} (expires-at {value})")
    else:
        print("error: lease write was not confirmed on read-back", file=sys.stderr)
        return 1
    return 0


def teardown(args) -> int:
    """Scale the env to zero and remove/expire its lease. Fail-closed."""
    # FAIL CLOSED. A teardown that found no lease did not tear anything down.
    # Refusing to silently succeed is exactly what keeps an unaccountable
    # ephemeral env from quietly staying alive.
    if args.dry_run:
        print(f"[dry-run] would teardown {args.profile}/{args.env}: scale to zero, "
              f"floor-zero autoscaling, and delete lease "
              f"{lease_path(args.profile, args.env)}")
        return 0

    current = _read_lease_cli(args.profile, args.env)
    decision = evaluate(args.profile, args.env, lambda p, e: current,
                        datetime.now(timezone.utc))
    if decision["expired"]:
        print(f"fail-closed: no live lease for {args.profile}/{args.env} "
              f"({decision['reason']}); refusing to silently succeed", file=sys.stderr)
        return 1

    # Scale to zero and drop autoscaling floors (the same enforcement action the
    # staging guard performs on the staging cluster).
    cluster = f"AETHER-{args.profile}"
    list_cmd = [
        "aws", "ecs", "--region", "us-east-1", "list-services",
        "--cluster", cluster, "--query", "serviceArns[]", "--output", "text",
    ]
    proc = subprocess.run(list_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"fail-closed: could not enumerate {cluster} ECS services; "
              f"teardown did not run ({proc.stderr.strip()})", file=sys.stderr)
        return 1
    services = [s for s in proc.stdout.replace("\t", "\n").splitlines() if s]
    for service in services:
        _run(["aws", "ecs", "--region", "us-east-1", "update-service",
              "--cluster", cluster, "--service", service, "--desired-count", "0"],
             args.dry_run)
        print(f"scaled {service} to desired-count 0")

    # Floor-zero autoscaling so nothing scales the group straight back up.
    targets_cmd = [
        "aws", "application-autoscaling", "--region", "us-east-1",
        "describe-scalable-targets", "--service-namespace", "ecs",
        "--query", f"ScalableTargets[?starts_with(ResourceId, 'service/{cluster}/')].ResourceId",
        "--output", "text",
    ]
    proc = subprocess.run(targets_cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        targets = [t for t in proc.stdout.replace("\t", "\n").splitlines() if t]
        for target in targets:
            _run(["aws", "application-autoscaling", "--region", "us-east-1",
                  "register-scalable-target", "--service-namespace", "ecs",
                  "--scalable-dimension", "ecs:service:DesiredCount",
                  "--resource-id", target, "--min-capacity", "0"], args.dry_run)
            print(f"autoscaling floor zeroed for {target}")
    else:
        print(f"warning: could not read autoscaling targets for {cluster}: "
              f"{proc.stderr.strip()}", file=sys.stderr)

    # Remove the lease last, so a partial failure leaves the lease in place and
    # the TTL guard still trips.
    _run([*_cli(args.profile, args.env), "delete-parameter",
          "--name", lease_path(args.profile, args.env)],
         args.dry_run)
    print(f"teardown complete for {args.profile}/{args.env} "
          f"(lease removed from {lease_path(args.profile, args.env)})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ephemeral_env",
        description="Provision and teardown TTL leases for demo/preview ephemeral envs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_prov = sub.add_parser("provision", help="write the SSM TTL lease")
    p_prov.add_argument("--profile", required=True, choices=ALLOWED_PROFILES)
    p_prov.add_argument("--env", required=True)
    p_prov.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS,
                        help=f"lease length in hours ({MIN_TTL_HOURS}-{MAX_TTL_HOURS}, default {DEFAULT_TTL_HOURS})")
    p_prov.add_argument("--dry-run", action="store_true",
                        help="print the would-be actions without executing any AWS call")
    p_prov.set_defaults(func=provision)

    p_tear = sub.add_parser("teardown", help="scale to zero and remove the lease")
    p_tear.add_argument("--profile", required=True, choices=ALLOWED_PROFILES)
    p_tear.add_argument("--env", required=True)
    p_tear.add_argument("--dry-run", action="store_true",
                        help="print the would-be actions without executing any AWS call")
    p_tear.set_defaults(func=teardown)

    args = parser.parse_args(argv)

    if args.command == "provision" and not (MIN_TTL_HOURS <= args.ttl_hours <= MAX_TTL_HOURS):
        print(f"error: --ttl-hours must be within {MIN_TTL_HOURS}-{MAX_TTL_HOURS}",
              file=sys.stderr)
        return 2

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
