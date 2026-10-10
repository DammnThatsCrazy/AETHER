"""Stablecoin Gold materialization helpers with accounting safeguards."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping

from repositories.stablecoin_repos import StablecoinGoldRepository

from .models import FinalityState, StablecoinEventType, StablecoinMoney

PAYMENT_VOLUME_EVENTS = {
    StablecoinEventType.PAYMENT,
    StablecoinEventType.X402_PAYMENT_OBSERVED,
    StablecoinEventType.SETTLEMENT_OBSERVATION,
}
EXCLUDED_ORGANIC_VOLUME_EVENTS = {
    StablecoinEventType.MINT,
    StablecoinEventType.BURN,
    StablecoinEventType.BRIDGE_MINT,
    StablecoinEventType.BRIDGE_BURN,
}


@dataclass(frozen=True)
class StablecoinMetricInput:
    tenant_id: str
    entity_id: str
    entity_type: str
    event_type: StablecoinEventType
    finality_status: FinalityState
    money: StablecoinMoney
    direction: str
    source: str
    internal_transfer: bool = False
    bridge_leg_group: str = ""
    swap_group: str = ""


@dataclass(frozen=True)
class StablecoinGoldMetric:
    tenant_id: str
    metric_name: str
    metric_version: str
    entity_id: str
    entity_type: str
    canonical_asset_id: str
    deployment_id: str
    chain_id: str
    window_start: str
    window_end: str
    dimensions: Mapping[str, Any]
    source: str
    value: Mapping[str, Any]


class StablecoinGoldMaterializer:
    def __init__(self, repo: StablecoinGoldRepository | None = None) -> None:
        self.repo = repo or StablecoinGoldRepository()

    def summarize_finalized_payment_volume(
        self,
        rows: Iterable[StablecoinMetricInput],
        *,
        window_start: str,
        window_end: str,
    ) -> list[StablecoinGoldMetric]:
        buckets: dict[tuple[str, str, str, str, str, str, str], int] = {}
        for row in rows:
            if row.finality_status != FinalityState.FINALIZED:
                continue
            if row.event_type not in PAYMENT_VOLUME_EVENTS:
                continue
            if row.event_type in EXCLUDED_ORGANIC_VOLUME_EVENTS or row.internal_transfer:
                continue
            key = (
                row.tenant_id,
                row.entity_id,
                row.entity_type,
                row.money.canonical_asset_id,
                row.money.deployment_id,
                row.money.chain_id,
                row.source,
            )
            buckets[key] = buckets.get(key, 0) + row.money.amount_atomic
        metrics: list[StablecoinGoldMetric] = []
        for (tenant_id, entity_id, entity_type, asset_id, deployment_id, chain_id, source), amount_atomic in buckets.items():
            metrics.append(StablecoinGoldMetric(
                tenant_id=tenant_id,
                metric_name="finalized_payment_volume_atomic",
                metric_version="stablecoin_gold_v1",
                entity_id=entity_id,
                entity_type=entity_type,
                canonical_asset_id=asset_id,
                deployment_id=deployment_id,
                chain_id=chain_id,
                window_start=window_start,
                window_end=window_end,
                dimensions={"accounting_basis": "finalized_only", "unit": "atomic_token_amount"},
                source=source,
                value={"amount_atomic": str(amount_atomic)},
            ))
        return metrics

    async def persist(self, metric: StablecoinGoldMetric) -> dict[str, Any]:
        return await self.repo.materialize_metric(
            tenant_id=metric.tenant_id,
            metric_name=metric.metric_name,
            metric_version=metric.metric_version,
            entity_id=metric.entity_id,
            entity_type=metric.entity_type,
            canonical_asset_id=metric.canonical_asset_id,
            deployment_id=metric.deployment_id,
            chain_id=metric.chain_id,
            window_start=metric.window_start,
            window_end=metric.window_end,
            dimensions=dict(metric.dimensions),
            source=metric.source,
            value=dict(metric.value),
            lineage={"materializer": "stablecoin_gold_v1"},
        )
