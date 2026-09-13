from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from .lifecycle_scenarios import LIFECYCLE_SUITES, LifecycleSuite
from .manifest import DEFAULT_NAMESPACE
from .service import DemoSeedService

_LIFECYCLE_EPILOG = """\
seed-lifecycle — stage the end-user lifecycle E2E scenario tenants (A-F).

For each suite whose tenant email + password are provided (env
E2E_TENANT_EMAIL_<SUITE> / E2E_TENANT_PASSWORD_<SUITE>, or --email/--password
for a single suite) this creates/updates that scenario tenant through the
canonical repositories the API reads: tenant, sign-in-able admin user,
tenant_implementation_plans (the TenantLanding routing state), the
tenant_activations record with saved WS-3 intents, and — for suite C only —
the comms cohort's record-fact-false connector rows.

It NEVER writes a credential value, a secret reference, a sync_status, a
revoked credential, or any readiness/evidence row, and it NEVER seeds
activation state 'complete'. Suite A is left activation-incomplete so the run
drives it; suites B/D/E's connector/evidence preconditions (commerce-connected,
revoked Google Ads, open mapping review) are operator/env layer inputs the E2E
run supplies with REAL credentials + syncs (the runbook reset seed). Use a
single --suite to point at one tenant with the shared E2E_TENANT_EMAIL/PASSWORD
pair; a multi-suite run requires per-suite E2E_TENANT_EMAIL_<SUITE> pairs so
each suite owns a distinct tenant.

Run:
    E2E_TENANT_EMAIL_C=tenant-c@acme.test E2E_TENANT_PASSWORD_C='<pw>' \\
        AETHER_ENV=local python -m services.demo_seed.cli seed-lifecycle
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.demo_seed.cli",
        description="Explicit backend-owned demonstration dataset management",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("seed", "status", "verify", "reset"):
        item = sub.add_parser(command)
        item.add_argument("--tenant", required=True, dest="tenant_id")
        item.add_argument("--namespace", default=DEFAULT_NAMESPACE)
        if command == "reset":
            item.add_argument(
                "--confirm",
                required=True,
                help='must exactly equal "RESET <tenant> <namespace>"',
            )

    lifecycle = sub.add_parser(
        "seed-lifecycle",
        help="seed end-user lifecycle E2E scenario tenants (A-F)",
        epilog=_LIFECYCLE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    lifecycle.add_argument(
        "--suite",
        dest="suites",
        action="append",
        choices=[suite.value for suite in LIFECYCLE_SUITES],
        help="seed only this suite (repeatable; default: all A-F)",
    )
    lifecycle.add_argument(
        "--email",
        default=None,
        help="explicit tenant email for a SINGLE --suite (overrides the suite env var)",
    )
    lifecycle.add_argument(
        "--password",
        default=None,
        help="explicit tenant password for a SINGLE --suite (overrides the suite env var)",
    )
    lifecycle.add_argument(
        "--environment",
        default=None,
        help="AETHER_ENV override (default: $AETHER_ENV; local/test/staging only)",
    )
    return parser


def _target_suites(args: argparse.Namespace) -> list[LifecycleSuite]:
    if args.suites:
        return [LifecycleSuite(suite) for suite in args.suites]
    return list(LIFECYCLE_SUITES)


async def _run_seed_lifecycle(args: argparse.Namespace) -> dict[str, Any]:
    from .lifecycle_seeder import LifecycleSeeder, resolve_credentials

    suites = _target_suites(args)
    environment = args.environment or os.getenv("AETHER_ENV")
    if not environment:
        raise SystemExit(
            "seed-lifecycle requires AETHER_ENV (local/test/staging); refusing to "
            "guess an environment"
        )
    if args.email is not None or args.password is not None:
        if len(suites) != 1:
            raise SystemExit("--email/--password override requires exactly one --suite")
    overrides = {
        "overrides_email": args.email,
        "overrides_password": args.password,
    }
    # A multi-suite run needs per-suite tenant emails (each suite a distinct
    # tenant); the shared E2E_TENANT_EMAIL/PASSWORD fallback is single-suite only.
    allow_shared = len(suites) == 1
    credentials: dict[LifecycleSuite, tuple[str, str]] = {}
    for suite in suites:
        resolved = resolve_credentials(
            suite, allow_shared=allow_shared, **overrides
        )
        if resolved[0] and resolved[1]:
            credentials[suite] = (resolved[0], resolved[1])
    seeder = LifecycleSeeder(environment=environment)
    return await seeder.seed_many(suites, credentials=credentials)


def _print_lifecycle_table(result: dict[str, Any]) -> None:
    print(
        f"lifecycle scenario seed  (AETHER_ENV={result.get('environment', '?')}, "
        f"source={result.get('seed_source', '?')})"
    )
    print(f"{'suite':<5} {'tenant':<16} {'plan':<9} {'activation':<24} email | connectors")
    for row in result.get("suites", []):
        conn = ", ".join(
            f"{item['family']}={item['action']}" for item in row.get("connectors", [])
        ) or "-"
        email = row.get("email") or "-"
        print(
            f"{row['suite']:<5} {row.get('tenant_status', '-'):<16} "
            f"{row.get('plan_action', '-'):<9} {row.get('activation_action', '-'):<24} "
            f"{email} | {conn}"
        )
    for row in result.get("suites", []):
        operator_bound = row.get("operator_bound", [])
        warnings = row.get("warnings", [])
        if not operator_bound and not warnings:
            continue
        print(f"\n[suite {row['suite']}] operator/evidence-bound — NOT seeded by CLI:")
        for item in operator_bound:
            print(f"  - {item}")
        if warnings:
            print("  remaining env/credential steps before the suite can run:")
            for warning in warnings:
                print(f"    · {warning}")


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "seed-lifecycle":
        return await _run_seed_lifecycle(args)
    service = DemoSeedService(environment=os.getenv("AETHER_ENV"))
    common = {"tenant_id": args.tenant_id, "namespace": args.namespace}
    if args.command == "seed":
        return (await service.seed(**common, actor="demo-seed-cli")).to_dict()
    if args.command == "status":
        return await service.status(**common)
    if args.command == "verify":
        return await service.verify(**common)
    if args.command == "reset":
        return await service.reset(
            **common, confirmation=args.confirm, actor="demo-reset-cli",
        )
    raise AssertionError(args.command)


def main() -> None:
    args = _parser().parse_args()
    result = asyncio.run(_run(args))
    if args.command == "seed-lifecycle":
        _print_lifecycle_table(result)
        return
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
