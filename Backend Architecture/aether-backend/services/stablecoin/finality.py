"""Stablecoin finality + reorganization engine.

Observations are immutable facts; ``finality_status`` / ``finalized_at`` are
the single mutable projection over them — finality is a property derived
from chain state, not new evidence, and the correction trail lives in the
emitted canonical events plus appended reconciliation records.

Rules enforced here:
- Checkpoints advance monotonically per (tenant, chain); regression raises.
- Confirmation only promotes provisional/confirmed rows at or below the
  confirmed block.
- Reorgs only demote provisional/confirmed rows at or above the fork block.
  FINALIZED OBSERVATIONS ARE NEVER REORGED — a finalized row predates the
  confirmation horizon by definition; touching it would falsify history.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.stablecoin_repos import (
    FinalityCheckpointRepo,
    ReconciliationRepo,
    StablecoinObservationRepo,
)
from services.stablecoin.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)

_REORGABLE_STATES = ("provisional", "confirmed")


class FinalityEngine:
    def __init__(
        self,
        checkpoint_repo: Optional[FinalityCheckpointRepo] = None,
        observation_repo: Optional[StablecoinObservationRepo] = None,
        reconciliation_repo: Optional[ReconciliationRepo] = None,
    ) -> None:
        self.checkpoints = checkpoint_repo or FinalityCheckpointRepo()
        self.observations = observation_repo or StablecoinObservationRepo()
        self.reconciliations = reconciliation_repo or ReconciliationRepo()

    async def get_checkpoint(self, tenant_id: str, chain_id: str) -> Optional[dict]:
        return await self.checkpoints.find_one(
            {"tenant_id": tenant_id, "chain_id": chain_id}
        )

    async def advance_checkpoint(
        self,
        tenant_id: str,
        chain_id: str,
        block_number: int,
        block_hash: Optional[str] = None,
        confirmation_horizon: int = 12,
    ) -> dict[str, Any]:
        current = await self.get_checkpoint(tenant_id, chain_id)
        if current is not None and int(current["confirmed_block_number"]) >= block_number:
            raise ValueError(
                f"checkpoint regression: {chain_id} already at "
                f"{current['confirmed_block_number']}, refusing {block_number}"
            )
        now = utc_now_iso()
        if current is None:
            basis = f"{tenant_id}|{chain_id}"
            await self.checkpoints.insert({
                "tenant_id": tenant_id,
                "checkpoint_id": deterministic_id("sccp_", basis),
                "chain_id": chain_id,
                "confirmed_block_number": block_number,
                "confirmed_block_hash": block_hash,
                "confirmation_horizon": confirmation_horizon,
                "advanced_at": now,
                "idempotency_key": deterministic_idempotency_key(basis),
                "evidence": None,
                "execution_by_aether": False,
            })
        else:
            await self.checkpoints.update_by_key(
                {"tenant_id": tenant_id, "chain_id": chain_id},
                {
                    "confirmed_block_number": block_number,
                    "confirmed_block_hash": block_hash,
                    "confirmation_horizon": confirmation_horizon,
                    "advanced_at": now,
                },
            )
        emitted = [make_event("stablecoin_checkpoint_advanced", tenant_id, {
            "chain_id": chain_id,
            "confirmed_block_number": str(block_number),
            "confirmation_horizon": confirmation_horizon,
        })]
        return {"emitted_events": emitted}

    async def confirm_observations(
        self, tenant_id: str, chain_id: str, confirmed_block: int,
    ) -> dict[str, Any]:
        """Promote provisional/confirmed observations at or below the
        confirmed block to finalized."""
        emitted: list[dict] = []
        finalized = 0
        now = utc_now_iso()
        for state in _REORGABLE_STATES:
            rows = await self.observations.find_many(
                {"tenant_id": tenant_id, "chain_id": chain_id, "finality_status": state},
                limit=10_000,
            )
            for row in rows:
                block = row.get("block_number")
                if block is None or int(block) > confirmed_block:
                    continue
                await self.observations.update_by_key(
                    {"tenant_id": tenant_id, "observation_id": row["observation_id"]},
                    {"finality_status": "finalized", "finalized_at": now},
                )
                finalized += 1
                emitted.append(make_event("stablecoin_finality_confirmed", tenant_id, {
                    "observation_id": row["observation_id"],
                    "chain_id": chain_id,
                    "block_number": str(block),
                }))
        return {"finalized_count": finalized, "emitted_events": emitted}

    async def handle_reorg(
        self, tenant_id: str, chain_id: str, from_block: int,
    ) -> dict[str, Any]:
        """Demote non-finalized observations at or above the fork block and
        append a reconciliation record per affected observation."""
        emitted: list[dict] = []
        affected = 0
        for state in _REORGABLE_STATES:
            rows = await self.observations.find_many(
                {"tenant_id": tenant_id, "chain_id": chain_id, "finality_status": state},
                limit=10_000,
            )
            for row in rows:
                block = row.get("block_number")
                if block is None or int(block) < from_block:
                    continue
                await self.observations.update_by_key(
                    {"tenant_id": tenant_id, "observation_id": row["observation_id"]},
                    {"finality_status": "reorged"},
                )
                affected += 1
                basis = f"reorg|{row['observation_id']}|{from_block}"
                await self.reconciliations.insert({
                    "tenant_id": tenant_id,
                    "reconciliation_id": deterministic_id("screc_", basis),
                    "observation_id": row["observation_id"],
                    "transaction_hash": row.get("transaction_hash"),
                    "status": "reverted",
                    "expected_amount": None,
                    "observed_amount": None,
                    "difference": None,
                    "sources_compared": ["chain_reorg"],
                    "resolved_at": None,
                    "resolution_note": f"chain reorg from block {from_block}",
                    "idempotency_key": deterministic_idempotency_key(basis),
                    "evidence": None,
                    "execution_by_aether": False,
                })
                emitted.append(make_event("stablecoin_reorg_detected", tenant_id, {
                    "observation_id": row["observation_id"],
                    "chain_id": chain_id,
                    "from_block": str(from_block),
                }))
        return {"affected_count": affected, "emitted_events": emitted}
