"""PaymentScan ingestion — catalog and benchmark intelligence ONLY.

PaymentScan is never deterministic user-level truth. Everything ingested
here lands as ``source=paymentscan``, ``reconciliation_state=benchmark_only``,
``basis=benchmark_only`` (or the exact basis PaymentScan reports), and
``confidence`` weak/probable depending on metric type.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.logger.logger import get_logger

from services.card_linked_payments.models import (
    CardActivityBasis,
    paymentscan_idempotency_key,
)
from services.card_linked_payments.repositories import get_card_linked_repositories
from services.payment_catalog.catalog import PAYMENTSCAN_CATALOG_SEED, resolve_slug

logger = get_logger("aether.card_linked.paymentscan")

# Metric types PaymentScan reports with enough methodology to call "probable";
# everything else stays "weak".
_PROBABLE_METRICS = frozenset({"program_count", "issuer_count", "network_share"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def sync_catalog(tenant_id: str) -> dict[str, Any]:
    """Refresh catalog freshness from the seed (or a live refresh upstream).

    Records provider health so Kyber can surface catalog staleness.
    """
    repos = get_card_linked_repositories()
    await repos.provider_health.record_sync(tenant_id, "paymentscan")
    by_type: dict[str, int] = {}
    for entity in PAYMENTSCAN_CATALOG_SEED:
        by_type[entity.entity_type] = by_type.get(entity.entity_type, 0) + 1
    return {
        "synced_at": _now(),
        "entity_count": len(PAYMENTSCAN_CATALOG_SEED),
        "by_type": by_type,
    }


async def ingest_benchmark(
    tenant_id: str,
    *,
    entity_type: str,
    entity_ref: str,
    metric_name: str,
    metric_window: str,
    value: str | None = None,
    basis: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Persist one PaymentScan benchmark observation.

    ``entity_ref`` may be a display name, alias, or slug — it resolves
    through the catalog. Unknown refs are kept (slug ``unknown``) so
    coverage gaps stay visible rather than silently dropped.
    """
    repos = get_card_linked_repositories()
    slug = resolve_slug(entity_ref) or "unknown"
    ts = observed_at or _now()

    if basis is not None and basis != CardActivityBasis.BENCHMARK_ONLY.value:
        # PaymentScan may report a specific basis (e.g. topup volume); keep
        # the exact basis but never let it masquerade as user-level spend
        # truth — reconciliation_state stays benchmark_only.
        resolved_basis = CardActivityBasis(basis).value
    else:
        resolved_basis = CardActivityBasis.BENCHMARK_ONLY.value

    record = {
        "id": f"psb_{slug}_{metric_name}_{metric_window}",
        "tenant_id": tenant_id,
        "catalog_entity_id": f"{entity_type}:{slug}",
        "metric_name": metric_name,
        "metric_window": metric_window,
        "value": value,
        "basis": resolved_basis,
        "source": "paymentscan",
        "confidence": "probable" if metric_name in _PROBABLE_METRICS else "weak",
        "reconciliation_state": "benchmark_only",
        "observed_at": ts,
        "idempotency_key": paymentscan_idempotency_key(
            tenant_id, entity_type, slug, metric_window, ts,
        ),
    }
    await repos.benchmarks.upsert(tenant_id, record)
    await repos.provider_health.record_event(tenant_id, "paymentscan")
    return record


async def catalog_freshness(tenant_id: str) -> dict[str, Any]:
    """Freshness snapshot for Kyber diagnostics."""
    repos = get_card_linked_repositories()
    health_rows = await repos.provider_health.list_for_tenant(tenant_id)
    paymentscan = next((h for h in health_rows if h.get("source") == "paymentscan"), None)
    programs = [e for e in PAYMENTSCAN_CATALOG_SEED if e.entity_type == "card_program"]
    issuers = [e for e in PAYMENTSCAN_CATALOG_SEED if e.entity_type == "issuer"]
    networks = [e for e in PAYMENTSCAN_CATALOG_SEED if e.entity_type == "payment_network"]
    chains = [e for e in PAYMENTSCAN_CATALOG_SEED if e.entity_type == "chain"]
    currencies = [e for e in PAYMENTSCAN_CATALOG_SEED if e.entity_type == "currency"]
    return {
        "last_sync_at": (paymentscan or {}).get("last_sync_at"),
        "stale": paymentscan is None or paymentscan.get("last_sync_at") is None,
        "card_program_count": len(programs),
        "issuer_count": len(issuers),
        "payment_network_count": len(networks),
        "chain_count": len(chains),
        "currency_count": len(currencies),
    }
