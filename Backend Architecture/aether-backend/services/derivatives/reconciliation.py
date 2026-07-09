"""Derivatives reconciliation — venue-reported snapshots vs Aether-projected
state. Snapshot-to-snapshot comparison only: fills are never re-derived here,
so order/fill/position double counting is structurally impossible."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from repositories.derivatives_repos import ReconciliationVarianceRepo
from services.derivatives.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)

TOLERANCE = Decimal("0.000000000001")

_COMPARED_FIELDS = ("size", "realized_pnl", "unrealized_pnl", "balance")


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


class DerivativesReconciliation:
    def __init__(self, variance_repo: Optional[ReconciliationVarianceRepo] = None) -> None:
        self.variances = variance_repo or ReconciliationVarianceRepo()

    async def reconcile_account(
        self,
        tenant_id: str,
        trading_account_id: str,
        venue_snapshot: dict[str, Any],
        projected: dict[str, Any],
    ) -> dict[str, Any]:
        emitted: list[dict] = []
        variances: list[dict] = []
        run_at = utc_now_iso()

        for field in _COMPARED_FIELDS:
            expected = _decimal(projected.get(field))
            observed = _decimal(venue_snapshot.get(field))
            if expected is None and observed is None:
                continue
            if expected is None or observed is None:
                difference = None
                severity = "medium"
            else:
                difference = observed - expected
                if abs(difference) <= TOLERANCE:
                    continue
                severity = "high" if abs(difference) > abs(expected or Decimal(1)) * Decimal("0.01") else "low"

            basis = f"{trading_account_id}|{field}|{run_at}"
            record = {
                "tenant_id": tenant_id,
                "reconciliation_variance_id": deterministic_id("dvvar_", basis),
                "variance_type": f"account_{field}",
                "expected_value": expected,
                "observed_value": observed,
                "difference": difference,
                "severity": severity,
                "status": "variance_detected",
                "idempotency_key": deterministic_idempotency_key(basis),
                "execution_by_aether": False,
            }
            await self.variances.insert(record)
            variances.append(record)
            emitted.append(make_event(
                "derivatives_reconciliation_variance_detected", tenant_id, {
                    "reconciliation_variance_id": record["reconciliation_variance_id"],
                    "trading_account_id": trading_account_id,
                    "variance_type": record["variance_type"],
                    "difference": str(difference) if difference is not None else None,
                    "severity": severity,
                },
            ))

        emitted.insert(0, make_event(
            "derivatives_reconciliation_run_completed", tenant_id, {
                "trading_account_id": trading_account_id,
                "fields_compared": list(_COMPARED_FIELDS),
                "variance_count": len(variances),
            },
        ))
        return {
            "variance_count": len(variances),
            "variances": [v["reconciliation_variance_id"] for v in variances],
            "emitted_events": emitted,
        }
