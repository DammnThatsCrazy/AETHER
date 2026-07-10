"""Kyber diagnostics — coverage, freshness, reconciliation, privacy state.

Everything an operator needs to judge card-linked data quality without
seeing tenant-private payloads: catalog freshness, source health,
unmatched evidence, reconciliation conflicts, suppression counts, blocked
PII attempts, and basis-mislabeling warnings.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.card_linked_payments.paymentscan import catalog_freshness
from services.card_linked_payments.repositories import get_card_linked_repositories


async def card_linked_diagnostics(tenant_id: str) -> dict[str, Any]:
    repos = get_card_linked_repositories()
    flows = await repos.flows.list_for_tenant(tenant_id, limit=500)
    health = await repos.provider_health.list_for_tenant(tenant_id)
    reconciliations = await repos.reconciliation.list_for_tenant(tenant_id)

    by_reconciliation: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    by_basis: dict[str, int] = defaultdict(int)
    region_restricted = 0
    for flow in flows:
        by_reconciliation[str(flow.get("reconciliation_state") or "unknown")] += 1
        by_source[str(flow.get("source") or "unknown")] += 1
        by_basis[str(flow.get("basis") or "unknown")] += 1
        if flow.get("region_policy") in ("EU_RESTRICTED", "UK_RESTRICTED", "APAC_RESTRICTED"):
            region_restricted += 1

    blocked_pii = await repos.audit.list_for_tenant(tenant_id, kind="blocked_pii")
    region_suppressed = await repos.audit.list_for_tenant(tenant_id, kind="region_suppressed")
    consent_suppressed = await repos.audit.list_for_tenant(tenant_id, kind="consent_suppressed")
    basis_warnings = await repos.audit.list_for_tenant(tenant_id, kind="basis_warning")

    unmatched = {
        state: count for state, count in by_reconciliation.items()
        if state in ("sdk_only", "provider_only", "onchain_only")
    }
    conflicts = [r for r in reconciliations if r.get("state") == "conflict"]

    # Which sources can prove which bases (top-up vs spend support map)
    basis_support: dict[str, list[str]] = defaultdict(list)
    for flow in flows:
        source = str(flow.get("source"))
        basis = str(flow.get("basis"))
        if basis not in basis_support[source]:
            basis_support[source].append(basis)

    return {
        "paymentscan": await catalog_freshness(tenant_id),
        "source_health": health,
        "flow_count": len(flows),
        "by_source": dict(by_source),
        "by_basis": dict(by_basis),
        "by_reconciliation_state": dict(by_reconciliation),
        "unmatched_events": unmatched,
        "reconciliation_conflicts": len(conflicts),
        "basis_support_by_source": {k: sorted(v) for k, v in basis_support.items()},
        "privacy": {
            "region_restricted_records": region_restricted,
            "region_suppression_events": len(region_suppressed),
            "consent_suppression_events": len(consent_suppressed),
            "blocked_pii_attempts": len(blocked_pii),
        },
        "warnings": {
            "basis_mislabeling": len(basis_warnings),
            "recent_basis_warnings": [w.get("detail") for w in basis_warnings[:10]],
        },
    }
