"""Gold rollups for card-linked activity.

Every rollup separates bases — top-up volume and spend volume are NEVER
summed into one number, and benchmark-only observations never contribute
to user-level metrics. All materialized rows are tenant-scoped and
``model_training_eligible=False``.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from shared.logger.logger import get_logger

from services.card_linked_payments.models import (
    CardActivityBasis,
    assert_topup_spend_separated,
)
from services.card_linked_payments.repositories import get_card_linked_repositories
from services.value.models import to_decimal

logger = get_logger("aether.card_linked.gold")

_SPEND_BASES = {CardActivityBasis.SPEND.value, CardActivityBasis.CLEARING.value}
_TOPUP_BASES = {CardActivityBasis.TOPUP.value, CardActivityBasis.FUNDING.value}


def _sum_usd(rows: list[dict]) -> str:
    """Sum decimal-string USD amounts exactly — never float money.

    An unparseable/absent amount contributes nothing (unknown != 0); the total
    is Decimal math over the exact decimal-string amounts and is emitted as a
    2-decimal string, preserving the historical rollup output contract.
    """
    total = Decimal(0)
    for row in rows:
        amount = to_decimal(row.get("amount_usd"))
        if amount is None:
            # not a finite number — never coerced to 0, contributes nothing
            continue
        total += amount
    return format(total, ".2f")


def _breakdown(rows: list[dict], field: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get(field) or "unknown")] += 1
    return dict(counts)


def _user_level(rows: list[dict]) -> list[dict]:
    """Benchmark-only records never contribute to user-level metrics."""
    return [r for r in rows if r.get("reconciliation_state") != "benchmark_only"
            and r.get("basis") != CardActivityBasis.BENCHMARK_ONLY.value]


async def entity_economic_activity(tenant_id: str, entity_id: str) -> dict[str, Any]:
    """Per-entity card-linked economic rollup (Profile360 backing)."""
    repos = get_card_linked_repositories()
    rows = _user_level(await repos.flows.list_for_tenant(tenant_id))
    attributed = [r for r in rows if entity_id in (
        r.get("canonical_entity_id"), r.get("user_id"), r.get("agent_id"),
        r.get("org_id"), r.get("wallet_address_hash"),
    )]
    topups = [r for r in attributed if r.get("basis") in _TOPUP_BASES]
    spends = [r for r in attributed if r.get("basis") in _SPEND_BASES]
    bases = sorted({str(r.get("basis")) for r in attributed})
    return assert_topup_spend_separated({
        "entity_id": entity_id,
        "flow_count": len(attributed),
        "topup_count": len(topups),
        "topup_volume_usd": _sum_usd(topups),
        "spend_count": len(spends),
        "spend_volume_usd": _sum_usd(spends),
        # combined label is honest about mixture — never a single number
        "basis": "mixed" if len(bases) > 1 else (bases[0] if bases else "unknown"),
        "basis_breakdown": _breakdown(attributed, "basis"),
        "source_breakdown": _breakdown(attributed, "source"),
        "confidence_breakdown": _breakdown(attributed, "confidence"),
        "evidence_breakdown": _breakdown(attributed, "evidence_strength"),
        "programs_observed": sorted({r.get("card_program_id") for r in attributed if r.get("card_program_id")}),
        "issuers_observed": sorted({r.get("issuer_id") for r in attributed if r.get("issuer_id")}),
        "networks_observed": sorted({str(r.get("payment_network") or "unknown") for r in attributed}),
        "chains_observed": sorted({r.get("chain") for r in attributed if r.get("chain")}),
        "assets_observed": sorted({r.get("asset") for r in attributed if r.get("asset")}),
    })


def _attribution_basis(flows: list[dict]) -> str:
    """Label how strongly the campaign linkage is supported — correlation
    is never presented as causality."""
    if not flows:
        return "insufficient_evidence"
    sources = {f.get("source") for f in flows}
    if sources == {"paymentscan"}:
        return "benchmark_only"
    if any(f.get("campaign_id") for f in flows):
        strong = [f for f in flows if f.get("confidence") in ("strong", "deterministic")]
        return "direct" if strong else "temporal"
    return "probabilistic"


async def campaign_card_linked_outcomes(tenant_id: str, campaign_id: str) -> dict[str, Any]:
    """Campaign360 card-linked outcome rollup."""
    repos = get_card_linked_repositories()
    rows = _user_level(await repos.flows.list_for_tenant(tenant_id, campaign_id=campaign_id))
    topups = [r for r in rows if r.get("basis") in _TOPUP_BASES]
    spends = [r for r in rows if r.get("basis") in _SPEND_BASES]

    def _users(subset: list[dict]) -> int:
        return len({r.get("canonical_entity_id") or r.get("user_id") or r.get("wallet_address_hash")
                    for r in subset if any((r.get("canonical_entity_id"), r.get("user_id"), r.get("wallet_address_hash")))})

    first_ts = sorted(r.get("occurred_at") or "" for r in rows if r.get("occurred_at"))
    return assert_topup_spend_separated({
        "campaign_id": campaign_id,
        "card_topup_users": _users(topups),
        "card_spend_users": _users(spends),
        "card_topup_volume_usd": _sum_usd(topups),
        "card_spend_volume_usd": _sum_usd(spends),
        "card_linked_flow_count": len(rows),
        "active_card_wallets": len({r.get("wallet_address_hash") for r in rows if r.get("wallet_address_hash")}),
        "programs_observed": sorted({r.get("card_program_id") for r in rows if r.get("card_program_id")}),
        "issuers_observed": sorted({r.get("issuer_id") for r in rows if r.get("issuer_id")}),
        "payment_networks_observed": sorted({str(r.get("payment_network") or "unknown") for r in rows}),
        "time_to_first_card_event": first_ts[0] if first_ts else None,
        "confidence_breakdown": _breakdown(rows, "confidence"),
        "basis_breakdown": _breakdown(rows, "basis"),
        "source_breakdown": _breakdown(rows, "source"),
        "evidence_breakdown": _breakdown(rows, "evidence_strength"),
        "attribution_basis": _attribution_basis(rows),
    })


async def program_issuer_benchmarks(tenant_id: str) -> dict[str, Any]:
    """Catalog-level benchmark rollup (PaymentScan + observed coverage)."""
    repos = get_card_linked_repositories()
    benchmarks = await repos.benchmarks.list_for_tenant(tenant_id)
    flows = _user_level(await repos.flows.list_for_tenant(tenant_id))
    return {
        "benchmark_count": len(benchmarks),
        "benchmark_basis_breakdown": _breakdown(benchmarks, "basis"),
        "observed_program_breakdown": _breakdown(flows, "card_program_id"),
        "observed_issuer_breakdown": _breakdown(flows, "issuer_id"),
        "observed_network_breakdown": _breakdown(flows, "payment_network"),
        "observed_chain_breakdown": _breakdown(flows, "chain"),
        "observed_asset_breakdown": _breakdown(flows, "asset"),
    }


async def cluster_features(tenant_id: str) -> list[dict[str, Any]]:
    """Per-entity cluster feature rows (program/chain/asset/volume/basis)."""
    repos = get_card_linked_repositories()
    rows = _user_level(await repos.flows.list_for_tenant(tenant_id))
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        entity = row.get("canonical_entity_id") or row.get("user_id") or row.get("wallet_address_hash")
        if entity:
            by_entity[str(entity)].append(row)
    features = []
    for entity, entity_rows in by_entity.items():
        spends = [r for r in entity_rows if r.get("basis") in _SPEND_BASES]
        topups = [r for r in entity_rows if r.get("basis") in _TOPUP_BASES]
        refunds = [r for r in entity_rows if r.get("basis") in
                   (CardActivityBasis.REFUND.value, CardActivityBasis.REVERSAL.value)]
        features.append({
            "entity_id": entity,
            "programs": sorted({r.get("card_program_id") for r in entity_rows if r.get("card_program_id")}),
            "issuers": sorted({r.get("issuer_id") for r in entity_rows if r.get("issuer_id")}),
            "chains": sorted({r.get("chain") for r in entity_rows if r.get("chain")}),
            "assets": sorted({r.get("asset") for r in entity_rows if r.get("asset")}),
            "topup_count": len(topups),
            "topup_volume_usd": _sum_usd(topups),
            "spend_count": len(spends),
            "spend_volume_usd": _sum_usd(spends),
            "refund_count": len(refunds),
            "refund_loop_suspect": len(refunds) >= 3 and len(refunds) >= max(1, len(spends)) // 2,
            "agent_influenced": any(r.get("agent_id") for r in entity_rows),
            "campaign_converted": any(r.get("campaign_id") for r in entity_rows),
        })
    return features


async def materialize_gold(tenant_id: str) -> dict[str, int]:
    """Push rollups into the Gold layer via the shared GoldRepository."""
    from repositories.lake import GoldRepository

    gold = GoldRepository()
    written = 0
    for feature in await cluster_features(tenant_id):
        await gold.materialize(
            metric_name="card_linked_entity_features",
            entity_id=feature["entity_id"],
            entity_type="entity",
            value=feature,
            dimensions={"programs": ",".join(feature["programs"])},
            source_tag="card_linked_payments",
            tenant_id=tenant_id,
            model_training_eligible=False,
        )
        written += 1
    return {"cluster_feature_rows": written}
