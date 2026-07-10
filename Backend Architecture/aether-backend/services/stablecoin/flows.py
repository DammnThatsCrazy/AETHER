"""Stablecoin windowed flow aggregation.

Financial-correctness rules enforced here (tested in
tests/unit/stablecoin/test_flows.py):
- Only FINALIZED observations count — pending/provisional/reverted/reorged
  activity never enters flow metrics.
- Mint and burn are supply events, never transfer volume.
- Self-transfers (from == to) never inflate volumes.
- Payment volume counts payment observations only — payments and their
  settlements are one economic event, not two.
- Historical windows are immutable: (window, metric_version) rows insert
  idempotently and are never overwritten.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from repositories.stablecoin_repos import FlowAggregateRepo, StablecoinObservationRepo
from services.stablecoin.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)
from services.stablecoin.models import StablecoinFlowComputeRequest

METRIC_VERSION = "1.0.0"

# Movement families for gross transfer volume: value moving between parties.
_TRANSFER_FAMILY = {
    "transfer", "payment", "bridge_outbound", "bridge_inbound", "swap",
    "x402_settlement", "treasury_movement", "payout",
    "venue_deposit", "venue_withdrawal",
}
_PAYMENT_FAMILY = {"payment", "x402_settlement"}
_SUPPLY_FAMILY = {"mint", "burn"}  # explicitly excluded from transfer volume


class FlowService:
    def __init__(
        self,
        observation_repo: Optional[StablecoinObservationRepo] = None,
        aggregate_repo: Optional[FlowAggregateRepo] = None,
    ) -> None:
        self.observations = observation_repo or StablecoinObservationRepo()
        self.aggregates = aggregate_repo or FlowAggregateRepo()

    async def compute_flow_aggregate(
        self, tenant_id: str, request: StablecoinFlowComputeRequest,
    ) -> dict[str, Any]:
        rows = await self.observations.find_many(
            {
                "tenant_id": tenant_id,
                "canonical_asset_id": request.canonical_asset_id,
                "finality_status": "finalized",
            },
            limit=100_000,
        )

        gross = Decimal("0")
        payment_volume = Decimal("0")
        transfer_count = 0
        senders: set[str] = set()
        recipients: set[str] = set()

        for row in rows:
            if request.deployment_id and row.get("deployment_id") != request.deployment_id:
                continue
            if request.chain_id and row.get("chain_id") != request.chain_id:
                continue
            observed_at = row.get("observed_at") or ""
            if not (request.window_start <= observed_at < request.window_end):
                continue
            obs_type = row.get("observation_type")
            if obs_type in _SUPPLY_FAMILY:
                continue  # mint/burn never counts as transfer volume
            from_addr = row.get("from_address")
            to_addr = row.get("to_address")
            if from_addr and to_addr and from_addr == to_addr:
                continue  # self-transfers never inflate volume
            if obs_type not in _TRANSFER_FAMILY:
                continue
            amount = row.get("amount_decimal")
            amount = amount if isinstance(amount, Decimal) else Decimal(str(amount))
            gross += amount
            transfer_count += 1
            if obs_type in _PAYMENT_FAMILY:
                payment_volume += amount
            if from_addr:
                senders.add(from_addr)
            if to_addr:
                recipients.add(to_addr)

        basis = (
            f"{request.canonical_asset_id}|{request.deployment_id or ''}"
            f"|{request.chain_id or ''}|{request.window_start}|{request.window_end}"
            f"|net|{METRIC_VERSION}"
        )
        record = {
            "tenant_id": tenant_id,
            "flow_aggregate_id": deterministic_id("scflow_", basis),
            "canonical_asset_id": request.canonical_asset_id,
            "deployment_id": request.deployment_id,
            "chain_id": request.chain_id,
            "window_start": request.window_start,
            "window_end": request.window_end,
            "direction": "net",
            "gross_transfer_volume": gross,
            "finalized_payment_volume": payment_volume,
            "transfer_count": transfer_count,
            "unique_senders": len(senders),
            "unique_recipients": len(recipients),
            "metric_version": METRIC_VERSION,
            "materialized_at": utc_now_iso(),
            "idempotency_key": deterministic_idempotency_key(basis),
            "evidence": None,
            "execution_by_aether": False,
        }
        inserted = await self.aggregates.insert(record)

        emitted: list[dict] = []
        if inserted:
            emitted.append(make_event("stablecoin_flow_aggregate_materialized", tenant_id, {
                "flow_aggregate_id": record["flow_aggregate_id"],
                "canonical_asset_id": request.canonical_asset_id,
                "window_start": request.window_start,
                "window_end": request.window_end,
                "gross_transfer_volume": str(gross),
                "finalized_payment_volume": str(payment_volume),
                "transfer_count": transfer_count,
                "metric_version": METRIC_VERSION,
            }))
        return {
            "inserted": inserted,
            "flow_aggregate_id": record["flow_aggregate_id"],
            "gross_transfer_volume": str(gross),
            "finalized_payment_volume": str(payment_volume),
            "transfer_count": transfer_count,
            "unique_senders": len(senders),
            "unique_recipients": len(recipients),
            "emitted_events": emitted,
        }
