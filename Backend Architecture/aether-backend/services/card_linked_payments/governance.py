"""Card-linked release-gate checks — fail closed on semantic/privacy drift.

Each check is a structural assertion over the codebase/config (no live
data): the catalog is seeded, basis semantics are enforced, blocked PII
is rejected, flags default off, and the product surfaces exist. The
release gate test suite runs `run_release_gate()` and fails the build on
any violation.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""


def _check_catalog_seeded() -> GateResult:
    from services.payment_catalog.catalog import (
        PAYMENTSCAN_CARD_PROGRAMS,
        PAYMENTSCAN_ISSUERS,
        PAYMENT_NETWORKS,
    )

    ok = (len(PAYMENTSCAN_CARD_PROGRAMS) >= 23 and len(PAYMENTSCAN_ISSUERS) >= 6
          and {n.slug for n in PAYMENT_NETWORKS} == {"visa", "mastercard", "unknown"})
    return GateResult("catalog_seeded", ok,
                      f"programs={len(PAYMENTSCAN_CARD_PROGRAMS)} issuers={len(PAYMENTSCAN_ISSUERS)}")


def _check_basis_validation() -> GateResult:
    from services.card_linked_payments.models import CardActivityBasis

    try:
        CardActivityBasis("onchain_card_spend")
        return GateResult("basis_validation", False, "unsupported basis accepted")
    except ValueError:
        return GateResult("basis_validation", True)


def _check_topup_spend_non_conflation() -> GateResult:
    """The normalizers must structurally refuse cross-basis claims."""
    from services.card_linked_payments.normalizer import (
        normalize_onchain_observation,
        normalize_provider_webhook,
    )

    try:
        normalize_onchain_observation({"id": "g", "tenant_id": "g", "basis": "spend"})
        return GateResult("topup_spend_non_conflation", False, "onchain accepted spend")
    except ValueError:
        pass
    try:
        normalize_provider_webhook({"id": "g", "tenant_id": "g", "basis": "topup"})
        return GateResult("topup_spend_non_conflation", False, "provider accepted topup")
    except ValueError:
        return GateResult("topup_spend_non_conflation", True)


def _check_blocked_pii_rejection() -> GateResult:
    from services.card_linked_payments.models import reject_blocked_fields

    for field in ("pan", "cvv", "raw_kyc_document", "routing_number", "provider_secret"):
        try:
            reject_blocked_fields({field: "x"})
            return GateResult("blocked_pii_rejection", False, f"{field} accepted")
        except ValueError:
            continue
    return GateResult("blocked_pii_rejection", True)


def _check_flags_default_off() -> GateResult:
    import os

    flag_vars = [
        "AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED", "AETHER_PAYMENTSCAN_CATALOG_ENABLED",
        "AETHER_PAYMENTSCAN_BENCHMARKS_ENABLED", "AETHER_CARD_LINKED_PROFILE360_ENABLED",
        "AETHER_CARD_LINKED_CAMPAIGN_ATTRIBUTION_ENABLED", "AETHER_CARD_LINKED_CLUSTERING_ENABLED",
        "KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED",
    ]
    saved = {var: os.environ.pop(var, None) for var in flag_vars}
    try:
        from config.settings import CardLinkedPaymentRailsConfig

        config = CardLinkedPaymentRailsConfig()
        rollout_off = not any([
            config.enabled, config.paymentscan_catalog_enabled,
            config.paymentscan_benchmarks_enabled, config.profile360_enabled,
            config.campaign_attribution_enabled, config.clustering_enabled,
            config.kyber_enabled,
        ])
        safety_on = config.eu_restricted_mode and config.apac_restricted_mode and config.provider_pii_block
        return GateResult("flags_default_off", rollout_off and safety_on)
    finally:
        for var, value in saved.items():
            if value is not None:
                os.environ[var] = value


def _check_benchmark_only_handling() -> GateResult:
    from services.card_linked_payments.models import CardLinkedFlowObserved

    flow = CardLinkedFlowObserved.benchmark(tenant_id="g", catalog_entity_id="card_program:redotpay")
    ok = flow.reconciliation_state == "benchmark_only" and str(flow.basis) == "benchmark_only"
    return GateResult("paymentscan_benchmark_only", ok)


def _check_graph_projection() -> GateResult:
    from services.card_linked_payments.graph_projector import build_flow_mutations

    benchmark_flow = {"tenant_id": "g", "id": "g", "basis": "benchmark_only",
                      "reconciliation_state": "benchmark_only"}
    vertices, edges = build_flow_mutations(benchmark_flow)
    return GateResult("graph_projection_honesty", vertices == [] and edges == [])


def _check_surface(module: str, attribute: str, name: str) -> GateResult:
    try:
        mod = importlib.import_module(module)
        return GateResult(name, hasattr(mod, attribute))
    except Exception as exc:  # pragma: no cover - import failure is the finding
        return GateResult(name, False, str(exc))


def _check_docs_present() -> GateResult:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3].parent
    docs = [
        root / "docs" / "source-of-truth" / "CARD_LINKED_PAYMENT_RAILS.md",
        root / "docs" / "source-of-truth" / "PAYMENTSCAN_CATALOG.md",
    ]
    missing = [str(d) for d in docs if not d.exists()]
    return GateResult("docs_source_of_truth_present", not missing, ", ".join(missing))


CHECKS: list[Callable[[], GateResult]] = [
    _check_catalog_seeded,
    _check_basis_validation,
    _check_topup_spend_non_conflation,
    _check_blocked_pii_rejection,
    _check_flags_default_off,
    _check_benchmark_only_handling,
    _check_graph_projection,
    lambda: _check_surface("services.card_linked_payments.profile_summary",
                           "get_card_linked_profile_summary", "profile360_surface_present"),
    lambda: _check_surface("services.card_linked_payments.gold",
                           "campaign_card_linked_outcomes", "campaign360_surface_present"),
    lambda: _check_surface("services.card_linked_payments.diagnostics",
                           "card_linked_diagnostics", "kyber_diagnostics_present"),
    _check_docs_present,
]


def run_release_gate() -> list[GateResult]:
    return [check() for check in CHECKS]


def release_gate_passed() -> bool:
    return all(result.passed for result in run_release_gate())
