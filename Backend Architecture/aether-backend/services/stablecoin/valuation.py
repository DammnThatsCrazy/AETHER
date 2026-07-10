"""Stablecoin peg valuation snapshots + depeg transition detection.

Prices arrive from governed sources (API submissions today; the Chainlink
price-feed connector is CREDENTIAL_GATED and not wired here). Every snapshot
is timestamped and source-attributed; nothing ever assumes a stablecoin is
worth exactly one dollar.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from repositories.stablecoin_repos import StablecoinDeploymentRepo, ValuationSnapshotRepo
from services.stablecoin.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
)
from services.stablecoin.models import PegStatus, StablecoinValuationRequest

# |peg deviation| thresholds in basis points
_MINOR_DEVIATION_BPS = Decimal("25")
_DEPEG_BPS = Decimal("100")


def classify_peg(peg_deviation_bps: Decimal) -> PegStatus:
    magnitude = abs(peg_deviation_bps)
    if magnitude < _MINOR_DEVIATION_BPS:
        return "on_peg"
    if magnitude < _DEPEG_BPS:
        return "minor_deviation"
    return "depegged"


class ValuationService:
    def __init__(
        self,
        snapshot_repo: Optional[ValuationSnapshotRepo] = None,
        deployment_repo: Optional[StablecoinDeploymentRepo] = None,
    ) -> None:
        self.snapshots = snapshot_repo or ValuationSnapshotRepo()
        self.deployments = deployment_repo or StablecoinDeploymentRepo()

    async def record_valuation(
        self, tenant_id: str, request: StablecoinValuationRequest,
    ) -> dict[str, Any]:
        deployment = await self.deployments.find_one(
            {"deployment_id": request.deployment_id}
        )
        pegged_to = "USD"
        if deployment is not None:
            asset_peg = deployment.get("pegged_to")
            if asset_peg:
                pegged_to = asset_peg
        if pegged_to != "USD":
            raise NotImplementedError(
                f"peg valuation for {pegged_to}-pegged assets requires an FX "
                "reference source — only USD pegs are supported"
            )

        deviation_bps = (request.price_usd - Decimal("1")) * Decimal("10000")
        peg_status = classify_peg(deviation_bps)

        previous = await self.snapshots.find_many(
            {"tenant_id": tenant_id, "deployment_id": request.deployment_id},
            limit=1, order_by="observed_at", descending=True,
        )
        previous_status = previous[0]["peg_status"] if previous else None

        basis = f"{request.deployment_id}|{request.source}|{request.observed_at}"
        record = {
            "tenant_id": tenant_id,
            "valuation_id": deterministic_id("scval_", basis),
            "deployment_id": request.deployment_id,
            "price_usd": request.price_usd,
            "peg_deviation_bps": deviation_bps,
            "peg_status": peg_status,
            "source": request.source,
            "source_record_id": request.source_record_id,
            "observed_at": request.observed_at,
            "stale_after": request.stale_after,
            "idempotency_key": deterministic_idempotency_key(basis),
            "evidence": request.evidence.model_dump() if request.evidence else None,
            "execution_by_aether": False,
        }
        inserted = await self.snapshots.insert(record)

        emitted: list[dict] = []
        if inserted:
            payload = {
                "deployment_id": request.deployment_id,
                "price_usd": str(request.price_usd),
                "peg_deviation_bps": str(deviation_bps),
                "peg_status": peg_status,
                "source": request.source,
            }
            emitted.append(make_event("stablecoin_valuation_observed", tenant_id, payload))
            # Transition events only — steady state never re-alerts.
            if peg_status == "depegged" and previous_status != "depegged":
                emitted.append(make_event("stablecoin_depeg_detected", tenant_id, payload))
            elif previous_status == "depegged" and peg_status != "depegged":
                emitted.append(make_event("stablecoin_depeg_resolved", tenant_id, payload))

        return {
            "inserted": inserted,
            "peg_status": peg_status,
            "peg_deviation_bps": str(deviation_bps),
            "emitted_events": emitted,
        }
