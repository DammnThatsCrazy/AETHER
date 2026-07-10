"""Stablecoin Profile360 composer for tenant-facing read models."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any, Mapping

from repositories.stablecoin_repos import StablecoinObservationRepository, StablecoinSupportAssertionRepository, StablecoinReconciliationRepository
from services.stablecoins.models import FinalityState, StablecoinEventType
from shared.common.common import utc_now


class StablecoinProfile360Composer:
    def __init__(
        self,
        observations: StablecoinObservationRepository | None = None,
        support: StablecoinSupportAssertionRepository | None = None,
        reconciliation: StablecoinReconciliationRepository | None = None,
    ) -> None:
        self.observations = observations or StablecoinObservationRepository()
        self.support = support or StablecoinSupportAssertionRepository()
        self.reconciliation = reconciliation or StablecoinReconciliationRepository()

    async def compose(self, *, tenant_id: str, profile_id: str, kind: str = "overview", limit: int = 100) -> dict[str, Any]:
        if not tenant_id:
            raise ValueError("tenant_id is required for Stablecoin Profile360")
        rows = await self.observations.find_many(filters={"tenant_id": tenant_id}, limit=limit)
        scoped = [r for r in rows if self._matches_profile(r, profile_id)]
        summary = self._summary(scoped)
        return {
            "entity_id": profile_id,
            "tenant_id": tenant_id,
            "kind": kind,
            "items": scoped,
            "summary": summary,
            "pagination": {"limit": limit, "count": len(scoped), "has_more": len(rows) > len(scoped)},
            "computed_at": utc_now().isoformat(),
            "freshness": "local_computed",
            "provider_status": "not_configured" if not rows else "available",
            "provenance": [{"observation_id": r.get("observation_id"), "evidence_id": r.get("evidence_id"), "source": r.get("source")} for r in scoped],
            "warnings": [] if rows else ["no_stablecoin_observations_available"],
            "drill_links": [f"/v1/stablecoins/observations/{r.get('observation_id')}" for r in scoped if r.get("observation_id")],
        }

    @staticmethod
    def _matches_profile(row: Mapping[str, Any], profile_id: str) -> bool:
        if profile_id in {"all", "*"}:
            return True
        fields = ("from_entity_id", "to_entity_id", "agent_id", "merchant_id", "protocol_id", "campaign_id", "journey_id", "from_wallet_id", "to_wallet_id")
        if any(str(row.get(field, "")) == profile_id for field in fields):
            return True
        return str(row.get("from_address", "")).lower() == profile_id.lower() or str(row.get("to_address", "")).lower() == profile_id.lower()

    @staticmethod
    def _summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
        finalized_payment_atomic = 0
        assets: Counter[str] = Counter()
        deployments: Counter[str] = Counter()
        chains: Counter[str] = Counter()
        finality: Counter[str] = Counter()
        for row in rows:
            assets[str(row.get("canonical_asset_id", "unknown"))] += 1
            deployments[str(row.get("deployment_id", "unknown"))] += 1
            chains[str(row.get("chain_id", "unknown"))] += 1
            status = str(row.get("finality_status", "unknown"))
            finality[status] += 1
            if status == FinalityState.FINALIZED.value and row.get("event_type") in {StablecoinEventType.PAYMENT.value, StablecoinEventType.X402_PAYMENT_OBSERVED.value, StablecoinEventType.SETTLEMENT_OBSERVATION.value}:
                finalized_payment_atomic += int(row.get("amount_atomic", 0) or 0)
        return {
            "observation_count": len(rows),
            "finalized_payment_volume_atomic": str(finalized_payment_atomic),
            "top_assets": assets.most_common(5),
            "top_deployments": deployments.most_common(5),
            "top_chains": chains.most_common(5),
            "finality": dict(finality),
            "unattributed_visible": any(not r.get("campaign_id") for r in rows),
            "unresolved_wallets_visible": any(not r.get("from_entity_id") or not r.get("to_entity_id") for r in rows),
        }
