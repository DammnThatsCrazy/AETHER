"""Noesis Derivatives Intelligence adapter — read-only exposure & reconciliation.

Answers `derivatives_exposure_lookup` (positions + P&L snapshots) and
`derivatives_reconciliation_lookup` (variances + unrecovered stream gaps).
Observation-only: Noesis never places, modifies, or recommends specific
orders — it reports observed state with provenance.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.derivatives")


def _stringify(row: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}


class DerivativesNoesisAdapter:
    """Deterministic lookups over derivatives positions, pnl snapshots,
    reconciliation variances, and stream gaps. Target may be a trading
    account id."""

    async def position_exposure(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        from repositories.derivatives_repos import PnlSnapshotRepo, PositionRepo

        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if target:
            filters["trading_account_id"] = target
        positions = await PositionRepo().find_many(filters, limit=limit)
        open_positions = [p for p in positions if p.get("status") == "open"]

        pnl_rows = await PnlSnapshotRepo().find_many(filters, limit=limit)

        parts = [
            f"{len(positions)} position(s) observed"
            + (f" for account {target}" if target else ""),
            f"{len(open_positions)} currently open",
        ]
        if pnl_rows:
            parts.append(f"{len(pnl_rows)} P&L snapshot(s) available")

        return {
            "answer": "Derivatives exposure: " + "; ".join(parts) + ".",
            "results": [_stringify(p) for p in positions[:limit]]
            + [_stringify(s) for s in pnl_rows[:limit]],
            "sources": ["derivatives_positions", "derivatives_pnl_snapshots"],
            "sufficient": bool(positions or pnl_rows),
        }

    async def reconciliation_status(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        from repositories.derivatives_repos import (
            ReconciliationVarianceRepo,
            StreamGapRepo,
        )

        # Variances are tenant-scoped without an account column; the
        # variance_type encodes the compared field (e.g. account_size).
        variances = await ReconciliationVarianceRepo().find_many(
            {"tenant_id": tenant_id}, limit=limit,
        )
        unresolved = [v for v in variances if v.get("status") == "variance_detected"]

        gaps = await StreamGapRepo().find_many({"tenant_id": tenant_id}, limit=limit)
        open_gaps = [g for g in gaps if g.get("status") == "open"]

        parts = [
            f"{len(variances)} reconciliation variance(s) recorded",
            f"{len(unresolved)} unresolved",
            f"{len(open_gaps)} open stream gap(s)",
        ]

        return {
            "answer": "Derivatives reconciliation: " + "; ".join(parts) + ".",
            "results": [_stringify(v) for v in variances[:limit]]
            + [_stringify(g) for g in open_gaps[:limit]],
            "sources": ["derivatives_reconciliation_variances", "derivatives_stream_gaps"],
            "sufficient": True,
        }
