from __future__ import annotations
from collections import Counter
from typing import Any
from services.card_linked_payments.repositories import get_card_linked_repositories
from services.payment_catalog.catalog import PAYMENTSCAN_CARD_PROGRAMS, PAYMENTSCAN_ISSUERS, PAYMENT_NETWORKS, CHAINS, CURRENCIES

async def card_linked_diagnostics(tenant_id: str | None = None) -> dict[str, Any]:
    repos = get_card_linked_repositories()
    flows = await (repos.flows.list_for_tenant(tenant_id) if tenant_id else repos.flows.list_all())
    benchmarks = await (repos.benchmarks.list_for_tenant(tenant_id) if tenant_id else repos.benchmarks.list_all())
    by_basis = Counter(str(f.get("basis", "unknown")) for f in flows)
    by_source = Counter(str(f.get("source", "unknown")) for f in flows)
    region_restricted = sum(1 for f in flows if str(f.get("region_policy", "")).endswith("RESTRICTED") or f.get("region_policy") == "GLOBAL_AGGREGATE_ONLY")
    consent_blocked = sum(1 for f in flows if f.get("consent_snapshot") and not all(bool(v) for v in f.get("consent_snapshot", {}).values()))
    warnings = []
    if by_basis.get("topup") and not by_basis.get("spend"):
        warnings.append("Top-up/funding records exist without provider spend coverage; do not report them as card spend.")
    if by_basis.get("benchmark_only"):
        warnings.append("PaymentScan records are benchmark-only and not deterministic user-level truth.")
    if by_basis.get("unknown"):
        warnings.append("Unknown-basis card-linked records require review.")
    return {
        "tenant_id": tenant_id,
        "catalog_freshness": "seeded",
        "paymentscan_status": "catalog_and_benchmarks_only",
        "card_program_count": len(PAYMENTSCAN_CARD_PROGRAMS),
        "issuer_count": len(PAYMENTSCAN_ISSUERS),
        "payment_network_count": len(PAYMENT_NETWORKS),
        "chain_count": len(CHAINS),
        "currency_count": len(CURRENCIES),
        "flow_count": len(flows),
        "benchmark_count": len(benchmarks),
        "basis_breakdown": dict(by_basis),
        "source_breakdown": dict(by_source),
        "topup_support": by_basis.get("topup", 0) + by_basis.get("funding", 0),
        "spend_support": by_basis.get("spend", 0),
        "provider_webhook_health": {"source": "provider_webhook", "records": by_source.get("provider_webhook", 0)},
        "unmatched_events": sum(1 for f in flows if f.get("reconciliation_state") in {"sdk_only", "provider_only", "onchain_only"}),
        "reconciliation_conflicts": by_source.get("conflict", 0),
        "graph_projection_queue": {"pending": 0, "failed": 0},
        "region_restricted_records": region_restricted,
        "consent_blocked_records": consent_blocked,
        "blocked_pii_attempts": 0,
        "basis_mislabeling_warnings": warnings,
        "region_policy_state": {"eu_restricted_mode": True, "apac_restricted_mode": True},
    }
