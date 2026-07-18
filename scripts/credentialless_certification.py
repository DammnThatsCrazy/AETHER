#!/usr/bin/env python3
"""Credentialless provider certification + readiness-truth reporter.

Builds the first-release capability matrix from source (no network, no
credentials), runs the credentialless certification checks against each
first-release descriptor, and prints an honest readiness table.

Flags:
  (default)   Print the capability matrix + certification summary. EXIT 0
              (honest reporting during build-out — never blocks).
  --strict    EXIT NON-ZERO if any first_release descriptor is below
              CREDENTIAL_WAITING or equal to SCAFFOLDED (PR7-time enforcement).
  --json      Print build_capability_matrix() as indented JSON and exit 0.

Exit codes:
  0  reporting succeeded (default/--json), or --strict with all first-release
     providers at least CREDENTIAL_WAITING and none SCAFFOLDED
  1  --strict and one or more first-release providers are not yet ready
  2  framework failed to load/build (import or resolution error)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ── backend import bootstrap (mirrors scripts/connector_smoke.py) ─────────────
BACKEND_ROOT = Path(__file__).parent.parent / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")


def _load():
    from shared.certification import (  # noqa: WPS433 (import inside fn is intentional)
        CredentialReadiness,
        build_capability_matrix,
        iter_first_release_descriptors,
        readiness_rank,
        run_certification,
    )

    return (
        CredentialReadiness,
        build_capability_matrix,
        iter_first_release_descriptors,
        readiness_rank,
        run_certification,
    )


def _print_matrix(matrix: dict) -> None:
    providers = matrix["providers"]
    summary = matrix["summary"]
    print("Credentialless provider certification — readiness truth")
    print("=" * 78)
    header = f"{'PROVIDER':<28}{'DOMAIN':<18}{'STATE':<20}{'FIRST_RELEASE':<14}"
    print(header)
    print("-" * 78)
    for _key, row in providers.items():
        print(
            f"{row['provider']:<28}{row['domain']:<18}"
            f"{row['state']:<20}{str(row['first_release']):<14}"
        )
    print("-" * 78)
    print(f"total={summary['total']}  first_release={summary['first_release']}")
    print(f"by_state={summary['by_state']}")
    print(f"by_domain={summary['by_domain']}")


def _print_certification(descriptors, run_certification) -> None:
    print()
    print("Certification checks (credentialless — descriptor-level; hooks skip)")
    print("-" * 78)
    print(f"{'PROVIDER':<28}{'PASS':<8}{'SKIP':<8}{'FAIL':<8}{'FAILED CHECKS'}")
    print("-" * 78)
    for d in descriptors:
        results = run_certification(d)
        passed = sum(1 for r in results if r.passed and not r.skipped)
        skipped = sum(1 for r in results if r.skipped)
        failed = [r for r in results if not r.passed]
        failed_names = ",".join(r.name for r in failed) or "-"
        print(
            f"{d.provider:<28}{passed:<8}{skipped:<8}{len(failed):<8}{failed_names}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any first-release provider is not at least CREDENTIAL_WAITING",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print build_capability_matrix() as indented JSON and exit 0",
    )
    args = parser.parse_args(argv)

    try:
        (
            CredentialReadiness,
            build_capability_matrix,
            iter_first_release_descriptors,
            readiness_rank,
            run_certification,
        ) = _load()
    except Exception as exc:  # pragma: no cover - import failure surface
        print(f"error: failed to load certification framework: {exc}", file=sys.stderr)
        return 2

    try:
        matrix = build_capability_matrix()
        descriptors = iter_first_release_descriptors()
    except Exception as exc:  # pragma: no cover
        print(f"error: failed to build capability matrix: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(matrix, indent=2, sort_keys=True))
        return 0

    _print_matrix(matrix)
    _print_certification(descriptors, run_certification)

    threshold = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    not_ready = [
        d
        for d in descriptors
        if d.first_release
        and (
            readiness_rank(d.implementation_state) < threshold
            or d.implementation_state == CredentialReadiness.SCAFFOLDED
        )
    ]

    print()
    if not_ready:
        print(
            f"{len(not_ready)} first-release provider(s) below CREDENTIAL_WAITING "
            f"(or SCAFFOLDED):"
        )
        for d in not_ready:
            print(f"  - {d.domain}:{d.provider} = {d.implementation_state.value}")
        if args.strict:
            print("strict gate: FAIL", file=sys.stderr)
            return 1
        print("strict gate not enabled — honest reporting only (exit 0).")
        return 0

    print("all first-release providers are at least CREDENTIAL_WAITING.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
