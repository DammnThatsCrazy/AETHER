#!/usr/bin/env python3
"""Financial-cohort credential-readiness certification + fail-closed gate.

A read-only reporter over the FINANCIAL provider cohort — the five payment-rail
adapters and the two stablecoin-chain observers. It resolves each first-release
financial adapter's HONEST ``CredentialReadiness`` from source (no network, no
credentials, no provider calls), runs the offline ``shared.certification``
checks against each descriptor, and prints an honest readiness verdict.
``--strict`` promotes that verdict into a fail-closed gate.

The financial cohort is exactly::

    payments:         bridge, coinbase, moonpay, privy, stripe_onramp
    stablecoin_chain: evm, svm

A provider is READY iff:

    * ``readiness_rank(state) >= readiness_rank(CREDENTIAL_WAITING)``, AND
    * ``state != SCAFFOLDED`` (a bare descriptor is never ready), AND
    * every ``run_certification(descriptor)`` check passed (skips are
      non-blocking; a skipped check reports ``passed=True``).

This FAILS CLOSED on a ``SCAFFOLDED`` adapter (rank below the threshold) and on
a dishonest ``PARTNER_LIVE`` descriptor — one that claims partner-live with no
live evidence, which the ``honest_status`` check fails.

Flags:
  (default)   Print the financial readiness table + certification summary.
              EXIT 0 (honest reporting during build-out — never blocks).
  --strict    EXIT 1 if any financial provider is not READY (fail-closed gate).
  --domain    Restrict to one financial domain {payments, stablecoin_chain}.
  --json      Print a secret-free evidence bundle as indented JSON and exit 0.

Exit codes:
  0  reporting succeeded (default/--json), or --strict with every financial
     provider READY
  1  --strict and one or more financial providers are not READY
  2  framework failed to load / resolve (import or resolution error)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ── backend import bootstrap (mirrors scripts/credentialless_certification.py) ─
BACKEND_ROOT = Path(__file__).parent.parent / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")

# The financial cohort this command certifies. Payment rails observe funding
# sessions; stablecoin-chain observers watch on-chain receipts. Neither executes.
FINANCIAL_DOMAINS = ("payments", "stablecoin_chain")


def _load():
    from shared.certification import (  # noqa: WPS433 (import inside fn is intentional)
        CredentialReadiness,
        iter_first_release_descriptors,
        readiness_rank,
        run_certification,
    )

    return (
        CredentialReadiness,
        iter_first_release_descriptors,
        readiness_rank,
        run_certification,
    )


def financial_descriptors(domain: str | None = None) -> list:
    """First-release financial descriptors resolved from source.

    Filters ``iter_first_release_descriptors()`` down to ``FINANCIAL_DOMAINS``
    (or a single financial domain when ``domain`` is given), sorted
    deterministically by (domain, provider). Read-only; no network.
    """
    if domain is not None and domain not in FINANCIAL_DOMAINS:
        raise ValueError(
            f"{domain!r} is not a financial domain (expected one of {FINANCIAL_DOMAINS})"
        )
    (_readiness, iter_first_release_descriptors, _rank, _run) = _load()
    wanted = (domain,) if domain else FINANCIAL_DOMAINS
    descriptors = [d for d in iter_first_release_descriptors() if d.domain in wanted]
    descriptors.sort(key=lambda d: (d.domain, d.provider))
    return descriptors


def evaluate(descriptors, run_certification, readiness_rank, CredentialReadiness) -> dict:
    """Compute the fail-closed readiness verdict over ``descriptors``.

    A provider is READY iff its readiness rank is at least CREDENTIAL_WAITING,
    it is not SCAFFOLDED, and no certification check failed. Returns a secret-
    free evidence bundle (domains, per-provider verdict, summary, strict verdict).
    """
    threshold = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    providers: list[dict] = []
    for d in descriptors:
        results = run_certification(d)
        failed = sorted(r.name for r in results if not r.passed)
        rank_ok = readiness_rank(d.implementation_state) >= threshold
        not_scaffolded = d.implementation_state != CredentialReadiness.SCAFFOLDED
        ready = bool(rank_ok and not_scaffolded and not failed)
        providers.append(
            {
                "domain": d.domain,
                "provider": d.provider,
                "adapter": d.adapter,
                "state": d.implementation_state.value,
                "state_rank": readiness_rank(d.implementation_state),
                "ready": ready,
                "failed_checks": failed,
            }
        )
    providers.sort(key=lambda p: (p["domain"], p["provider"]))

    by_domain: dict[str, int] = {}
    by_state: dict[str, int] = {}
    for p in providers:
        by_domain[p["domain"]] = by_domain.get(p["domain"], 0) + 1
        by_state[p["state"]] = by_state.get(p["state"], 0) + 1

    not_ready = [p for p in providers if not p["ready"]]
    all_ready = not not_ready
    return {
        "domains": sorted({p["domain"] for p in providers}),
        "providers": providers,
        "summary": {
            "total": len(providers),
            "ready": sum(1 for p in providers if p["ready"]),
            "not_ready": len(not_ready),
            "by_domain": dict(sorted(by_domain.items())),
            "by_state": dict(sorted(by_state.items())),
        },
        "not_ready": not_ready,
        "all_ready": all_ready,
        "strict_verdict": "PASS" if all_ready else "FAIL",
    }


def payment_operational_checks() -> list[dict]:
    """Fail-closed, code+config-level operational readiness checks for the
    payment-rail cohort. Each returns ``{name, ok, detail}`` with a SPECIFIC
    detail identifying the exact missing configuration when it fails — never a
    generic pass/fail. These assert the delivery-integrity plumbing has landed
    (migrations, workers, release flags, typed contract); the live-evidence
    dimensions (migration APPLIED, credential ACTIVE, endpoint registered,
    sandbox evidence, staging soak) are gated separately by the pilot preflight +
    evidence bundle, which fail closed when their artifacts are absent.
    """
    checks: list[dict] = []

    def _add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # 1. Migrations present + a single Alembic head.
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config()
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        heads = ScriptDirectory.from_config(cfg).get_heads()
        _add("single_alembic_head", len(heads) == 1,
             f"expected exactly one head, found {list(heads)}")
        versions = {p.name for p in (BACKEND_ROOT / "alembic" / "versions").glob("*.py")}
        _add("receipt_migration_present",
             any("payment_provider_receipts" in v for v in versions),
             "migration 20260817_payment_provider_receipts.py is missing")
        _add("endpoint_unique_migration_present",
             any("payment_webhook_endpoint_active_unique" in v for v in versions),
             "migration 20260816_payment_webhook_endpoint_active_unique.py is missing")
    except Exception as exc:  # pragma: no cover
        _add("migrations_loadable", False, f"could not resolve migrations: {exc}")

    # 2. Supervised workers registered + claimed by a runtime role.
    try:
        from services.runtime.roles import ROLE_TO_SPEC_NAMES

        class _S:  # a stand-in settings with the attrs build_worker_specs reads
            def __getattr__(self, _):  # pragma: no cover - never actually read
                return None

        claimed = set().union(*ROLE_TO_SPEC_NAMES.values())
        for worker in ("payment_rail_sync", "payment_canonical_repair", "event_outbox_relay"):
            _add(f"worker_role_claimed:{worker}", worker in claimed,
                 f"worker {worker!r} is not claimed by any runtime role in ROLE_TO_SPEC_NAMES")
    except Exception as exc:  # pragma: no cover
        _add("workers_registered", False, f"could not resolve worker roles: {exc}")

    # 3. Release feature flags exist on the settings object.
    try:
        from config.settings import settings

        pr = settings.payment_rails
        for flag in ("credential_authority_enabled", "canonical_outbox_enabled",
                     "canonical_repair_enabled", "usage_metering_enabled",
                     "legacy_webhook_route_enabled"):
            _add(f"flag_present:{flag}", hasattr(pr, flag),
                 f"settings.payment_rails.{flag} is not defined")
        # Outbox relay flag (separate config namespace).
        _add("flag_present:outbox_relay_enabled",
             hasattr(settings.ingestion_v2, "outbox_relay_enabled"),
             "settings.ingestion_v2.outbox_relay_enabled is not defined")
    except Exception as exc:  # pragma: no cover
        _add("settings_flags", False, f"could not resolve settings flags: {exc}")

    # 4. Typed operator contract + receipt/repair modules importable.
    for mod, label in (
        ("services.integrations.providers.payment_rails.kyber_contract", "kyber_contract"),
        ("services.integrations.providers.payment_rails.receipts", "receipt_lifecycle"),
        ("services.integrations.providers.payment_rails.repair_worker", "repair_worker"),
    ):
        try:
            __import__(mod)
            _add(f"module_present:{label}", True, "importable")
        except Exception as exc:  # pragma: no cover
            _add(f"module_present:{label}", False, f"{mod} failed to import: {exc}")

    return checks


def _print_operational(checks: list[dict]) -> None:
    print()
    print("Operational readiness (code + configuration invariants)")
    print("-" * 78)
    for c in checks:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"  [{mark}] {c['name']}" + ("" if c["ok"] else f" — {c['detail']}"))


def _print_report(verdict: dict, domain: str | None) -> None:
    scope = domain or "+".join(FINANCIAL_DOMAINS)
    print("Financial credential-readiness certification — readiness truth")
    print("=" * 78)
    print(f"scope: {scope}")
    header = f"{'PROVIDER':<20}{'DOMAIN':<20}{'STATE':<20}{'READY':<8}{'FAILED CHECKS'}"
    print(header)
    print("-" * 78)
    for p in verdict["providers"]:
        failed = ",".join(p["failed_checks"]) or "-"
        print(
            f"{p['provider']:<20}{p['domain']:<20}"
            f"{p['state']:<20}{str(p['ready']):<8}{failed}"
        )
    print("-" * 78)
    s = verdict["summary"]
    print(f"total={s['total']}  ready={s['ready']}  not_ready={s['not_ready']}")
    print(f"by_state={s['by_state']}")
    print(f"by_domain={s['by_domain']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any financial provider is not READY (fail-closed)",
    )
    parser.add_argument(
        "--domain",
        choices=list(FINANCIAL_DOMAINS),
        default=None,
        help="restrict the cohort to one financial domain",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print a secret-free evidence bundle as indented JSON and exit 0",
    )
    args = parser.parse_args(argv)

    try:
        (
            CredentialReadiness,
            _iter,
            readiness_rank,
            run_certification,
        ) = _load()
    except Exception as exc:  # pragma: no cover - import failure surface
        print(f"error: failed to load certification framework: {exc}", file=sys.stderr)
        return 2

    try:
        descriptors = financial_descriptors(args.domain)
    except Exception as exc:  # pragma: no cover - resolution failure surface
        print(f"error: failed to resolve financial descriptors: {exc}", file=sys.stderr)
        return 2

    verdict = evaluate(descriptors, run_certification, readiness_rank, CredentialReadiness)

    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0

    _print_report(verdict, args.domain)

    # Operational (code+config) checks apply to the payment-rail cohort.
    payments_in_scope = args.domain in (None, "payments")
    op_checks = payment_operational_checks() if payments_in_scope else []
    op_failures = [c for c in op_checks if not c["ok"]]
    if op_checks:
        _print_operational(op_checks)

    print()
    failed = False
    if verdict["not_ready"]:
        failed = True
        print(f"{len(verdict['not_ready'])} financial provider(s) not READY:")
        for p in verdict["not_ready"]:
            reason = ",".join(p["failed_checks"]) or f"state={p['state']}"
            print(f"  - {p['domain']}:{p['provider']} ({reason})")
    if op_failures:
        failed = True
        print(f"{len(op_failures)} operational readiness check(s) FAILED:")
        for c in op_failures:
            print(f"  - {c['name']}: {c['detail']}")

    if failed:
        if args.strict:
            print("strict gate: FAIL", file=sys.stderr)
            return 1
        print("strict gate not enabled — honest reporting only (exit 0).")
        return 0

    print(
        "all financial providers are READY "
        "(>= CREDENTIAL_WAITING, not SCAFFOLDED, all certification checks pass); "
        "operational code+config invariants satisfied."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
