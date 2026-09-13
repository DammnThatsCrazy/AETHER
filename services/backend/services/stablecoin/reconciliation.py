"""Stablecoin reconciliation — compares independently sourced amounts for
one observation (tenant-reported vs on-chain vs provider) and appends a
durable, explainable reconciliation record. Never mutates observations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from repositories.stablecoin_repos import ReconciliationRepo, StablecoinObservationRepo
from services.stablecoin.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)

# Amounts within this tolerance are considered equal (dust / rounding at the
# provider boundary). Canonical comparisons are Decimal-exact beyond it.
TOLERANCE = Decimal("0.000001")


class ReconciliationService:
    def __init__(
        self,
        reconciliation_repo: Optional[ReconciliationRepo] = None,
        observation_repo: Optional[StablecoinObservationRepo] = None,
    ) -> None:
        self.reconciliations = reconciliation_repo or ReconciliationRepo()
        self.observations = observation_repo or StablecoinObservationRepo()

    async def reconcile_observation(
        self, tenant_id: str, observation_id: str, sources: dict[str, Any],
    ) -> dict[str, Any]:
        """`sources` maps source name -> decimal amount (or None when the
        source has no record). Classification:
        - onchain source absent            -> missing_onchain
        - all present, all within tolerance -> matched
        - some absent, present ones agree   -> partial
        - any pairwise diff > tolerance     -> mismatched
        """
        observation = await self.observations.find_one(
            {"tenant_id": tenant_id, "observation_id": observation_id}
        )
        amounts: dict[str, Optional[Decimal]] = {}
        for name, value in sources.items():
            if value is None:
                amounts[name] = None
            else:
                amounts[name] = value if isinstance(value, Decimal) else Decimal(str(value))

        present = {k: v for k, v in amounts.items() if v is not None}
        missing = [k for k, v in amounts.items() if v is None]

        if "onchain" in missing:
            status = "missing_onchain"
        elif not present:
            status = "unresolved"
        else:
            values = list(present.values())
            max_diff = max(values) - min(values)
            if max_diff > TOLERANCE:
                status = "mismatched"
            elif missing:
                status = "partial"
            else:
                status = "matched"

        expected = present.get("tenant_reported") or (next(iter(present.values())) if present else None)
        observed = present.get("onchain")
        difference = (
            (observed - expected) if (observed is not None and expected is not None) else None
        )

        basis = f"{observation_id}|{'|'.join(sorted(sources))}|{utc_now_iso()[:19]}"
        record = {
            "tenant_id": tenant_id,
            "reconciliation_id": deterministic_id("screc_", basis),
            "observation_id": observation_id,
            "transaction_hash": (observation or {}).get("transaction_hash"),
            "status": status,
            "expected_amount": expected,
            "observed_amount": observed,
            "difference": difference,
            "sources_compared": sorted(sources),
            "resolved_at": utc_now_iso() if status == "matched" else None,
            "resolution_note": None,
            "idempotency_key": deterministic_idempotency_key(basis),
            "evidence": None,
            "execution_by_aether": False,
        }
        await self.reconciliations.insert(record)

        emitted = [make_event("stablecoin_reconciliation_run_completed", tenant_id, {
            "reconciliation_id": record["reconciliation_id"],
            "observation_id": observation_id,
            "status": status,
        })]
        if status in ("mismatched", "missing_onchain"):
            emitted.append(make_event(
                "stablecoin_reconciliation_variance_detected", tenant_id, {
                    "reconciliation_id": record["reconciliation_id"],
                    "observation_id": observation_id,
                    "status": status,
                    "difference": str(difference) if difference is not None else None,
                },
            ))
        return {
            "reconciliation_id": record["reconciliation_id"],
            "status": status,
            "difference": str(difference) if difference is not None else None,
            "emitted_events": emitted,
        }
