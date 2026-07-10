#!/usr/bin/env python3
"""Aether Platform — Staging Preflight Gate.

Fail-closed gate run before promoting a build to staging/production.
Exit 0 iff every executed check passes (SKIPs never fail the gate; any
FAIL does).

Supported CLI contract::

    python scripts/staging_preflight.py
    python scripts/staging_preflight.py --env-file deploy/staging.env
    python scripts/staging_preflight.py --base-url https://api.staging.aether.io
    python scripts/staging_preflight.py --dry-run
    python scripts/staging_preflight.py --json

Checks
------
env        candidate env vars (AETHER_ENV, CORS, secrets, placeholders,
           in-memory override) + a subprocess constructing the real
           config.settings.Settings() under exactly that environment
db         asyncpg connect + SELECT 1, alembic head parity, and
           migration-vs-runtime table-shape parity (SKIP in --dry-run)
redis      redis.asyncio PING (SKIP in --dry-run)
http       GET {base}/v1/health + GET {base}/v1/ready
           (only with --base-url; SKIP otherwise and in --dry-run)
contracts  scripts/validate_sdk_contracts.py,
           scripts/check_version_consistency.py (missing => FAIL live,
           SKIP+warn in --dry-run), and scripts/bump_version.py --check

--dry-run is a self-test of the gate itself: env checks run against
tests/fixtures/staging_preflight/valid.env (which must PASS) and
invalid.env (which must FAIL — proving the gate fails closed). A dry run
NEVER certifies a live environment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import (  # noqa: E402
    preflight_contracts,
    preflight_db,
    preflight_env,
    preflight_http,
    preflight_redis,
)
from scripts.lib.preflight_results import (  # noqa: E402
    CheckResult,
    all_passed,
    count_by_status,
    failed,
    passed,
    render_results,
)

FIXTURES_DIR = ROOT / "tests" / "fixtures" / "staging_preflight"
VALID_FIXTURE = FIXTURES_DIR / "valid.env"
INVALID_FIXTURE = FIXTURES_DIR / "invalid.env"

VALID_PREFIX = "env:valid-fixture"
INVALID_PREFIX = "env:invalid-fixture"
SELF_TEST_NAME = "dry-run:invalid-fixture-fails-closed"

# Check suffixes the invalid fixture MUST fail for the gate to be considered
# fail-closed: local AETHER_ENV, wildcard CORS, missing DATABASE_URL, and a
# placeholder ("changeme") secret.
EXPECTED_INVALID_FAILURES = (
    "aether-env",
    "cors-origins",
    "database-url",
    "no-placeholder-secrets",
)

DRY_RUN_BANNER = (
    "MODE: DRY-RUN — self-test of the gate against committed fixtures.",
    "A dry run does NOT certify a live environment. Run without --dry-run",
    "against the real staging environment/services before promoting.",
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether staging preflight gate")
    parser.add_argument(
        "--env-file",
        help="Load the candidate environment from a KEY=VALUE file instead of "
        "the process environment ('#' comments and blank lines ignored)",
    )
    parser.add_argument(
        "--base-url",
        help="Base URL of a live deployment for HTTP health/ready checks "
        "(e.g. https://api.staging.aether.io); HTTP checks SKIP without it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Self-test the gate against tests/fixtures/staging_preflight "
        "fixtures; DB/Redis/HTTP checks SKIP; never certifies an environment",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON report")
    args = parser.parse_args(argv)
    if args.dry_run and (args.env_file or args.base_url):
        parser.error("--dry-run runs against committed fixtures only; "
                     "drop --env-file/--base-url or run without --dry-run")
    if args.env_file and not Path(args.env_file).is_file():
        parser.error(f"--env-file not found: {args.env_file}")
    return args


def evaluate_fail_closed_self_test(
    invalid_results: Sequence[CheckResult],
    *,
    prefix: str = INVALID_PREFIX,
) -> CheckResult:
    """PASS iff the invalid fixture failed every expected check.

    This is the dry-run proof that the gate fails closed: if the known-bad
    fixture stops failing, the gate has regressed and the dry run must fail.
    """
    by_name = {r.name: r for r in invalid_results}
    not_failing = [
        suffix for suffix in EXPECTED_INVALID_FAILURES
        if not (by_name.get(f"{prefix}:{suffix}") and by_name[f"{prefix}:{suffix}"].failed)
    ]
    if not_failing:
        return failed(
            SELF_TEST_NAME,
            "invalid fixture did NOT fail these checks: " + ", ".join(not_failing),
            "the gate has regressed — restore fail-closed behavior in "
            "scripts/lib/preflight_env.py (do not weaken "
            "tests/fixtures/staging_preflight/invalid.env)",
        )
    return passed(
        SELF_TEST_NAME,
        "invalid fixture correctly failed: " + ", ".join(EXPECTED_INVALID_FAILURES),
    )


def build_report(
    checks: Sequence[CheckResult],
    *,
    invalid_fixture_checks: Sequence[CheckResult] = (),
    dry_run: bool = False,
) -> dict:
    """Aggregate check results into the machine-readable report shape."""
    report: dict = {
        "dry_run": dry_run,
        "passed": all_passed(checks),
        "checks": [c.to_dict() for c in checks],
    }
    if dry_run:
        report["invalid_fixture_checks"] = [c.to_dict() for c in invalid_fixture_checks]
    return report


async def _run_service_checks(
    env: dict,
    base_url: Optional[str],
    dry_run: bool,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    results += await preflight_db.run_db_checks(env, dry_run=dry_run)
    results += await preflight_redis.run_redis_checks(env, dry_run=dry_run)
    results += await preflight_http.run_http_checks(base_url, dry_run=dry_run)
    return results


def run_preflight(
    *,
    env_file: Optional[str] = None,
    base_url: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    checks: list[CheckResult] = []
    invalid_fixture_checks: list[CheckResult] = []

    if dry_run:
        valid_env = preflight_env.parse_env_file(VALID_FIXTURE)
        checks += preflight_env.run_env_checks(valid_env, prefix=VALID_PREFIX)
        invalid_env = preflight_env.parse_env_file(INVALID_FIXTURE)
        invalid_fixture_checks = preflight_env.run_env_checks(
            invalid_env, prefix=INVALID_PREFIX
        )
        checks.append(evaluate_fail_closed_self_test(invalid_fixture_checks))
        candidate_env = valid_env
    else:
        candidate_env = preflight_env.load_candidate_env(env_file)
        checks += preflight_env.run_env_checks(candidate_env)

    checks += asyncio.run(_run_service_checks(candidate_env, base_url, dry_run))
    checks += preflight_contracts.run_contract_checks(dry_run=dry_run)

    return build_report(
        checks, invalid_fixture_checks=invalid_fixture_checks, dry_run=dry_run
    )


def _print_report(report: dict) -> None:
    checks = [CheckResult(**c) for c in report["checks"]]
    print("=" * 70)
    print("AETHER STAGING PREFLIGHT")
    print("=" * 70)
    if report["dry_run"]:
        for line in DRY_RUN_BANNER:
            print(line)
        print("-" * 70)
    for line in render_results(checks):
        print(line)
    invalid = [CheckResult(**c) for c in report.get("invalid_fixture_checks", [])]
    if invalid:
        print()
        print("Invalid-fixture self-test detail (these SHOULD fail — informational,")
        print("not counted toward the gate result):")
        for line in render_results(invalid, indent="    "):
            print(line)
    counts = count_by_status(checks)
    print("-" * 70)
    print(
        f"  Checks: {counts['PASS']} passed, {counts['FAIL']} failed, "
        f"{counts['SKIP']} skipped"
    )
    print(f"RESULT: {'PASS' if report['passed'] else 'FAIL'}")
    if report["dry_run"]:
        print("NOTE: dry-run validates the gate itself; it does NOT certify a "
              "live environment.")
    print("=" * 70)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = run_preflight(
        env_file=args.env_file, base_url=args.base_url, dry_run=args.dry_run
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
