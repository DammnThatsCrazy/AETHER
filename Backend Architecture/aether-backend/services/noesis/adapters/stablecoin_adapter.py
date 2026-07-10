"""Noesis Stablecoin Intelligence adapter — read-only flow & peg summaries.

Answers `stablecoin_flow_lookup` from stablecoin flow aggregates and
valuation snapshots. Observation-only: no repository writes, no mutation
of domain state, Decimals serialized as strings.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.stablecoin")


def _stringify(row: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}


class StablecoinNoesisAdapter:
    """Deterministic lookups over stablecoin_flow_aggregates and
    stablecoin_valuation_snapshots. Target may be a canonical asset id."""

    async def flow_summary(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        from repositories.stablecoin_repos import (
            FlowAggregateRepo,
            ValuationSnapshotRepo,
        )

        flow_filters: dict[str, Any] = {"tenant_id": tenant_id}
        if target:
            flow_filters["canonical_asset_id"] = target
        flows = await FlowAggregateRepo().find_many(flow_filters, limit=limit)

        valuations = await ValuationSnapshotRepo().find_many(
            {"tenant_id": tenant_id}, limit=200,
        )
        if target:
            # Valuations key on deployment_id; keep tenant-wide peg view when
            # the target is an asset id rather than a deployment id.
            scoped = [v for v in valuations if v.get("deployment_id") == target]
            valuations = scoped or valuations
        depegged = [v for v in valuations if v.get("peg_status") in ("depegged", "minor_deviation")]

        parts = [f"{len(flows)} flow aggregate(s) observed"]
        if target:
            parts.append(f"for asset {target}")
        if depegged:
            deployments = sorted({str(d.get("deployment_id") or "?") for d in depegged})
            parts.append(
                f"{len(depegged)} valuation snapshot(s) show peg deviation ({', '.join(deployments)})"
            )
        elif valuations:
            parts.append("all observed valuations are on peg")

        return {
            "answer": "Stablecoin flows: " + "; ".join(parts) + ".",
            "results": [_stringify(r) for r in flows[:limit]]
            + [_stringify(v) for v in depegged[:limit]],
            "sources": ["stablecoin_flow_aggregates", "stablecoin_valuation_snapshots"],
            "sufficient": bool(flows or valuations),
        }
