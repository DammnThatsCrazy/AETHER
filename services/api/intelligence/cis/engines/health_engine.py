"""
CIS Graph Health Scoring Engine
Aggregates sub-scores from all CIS engines into a composite health index (0–100).

Weights (configurable via CISConfig):
  structural_integrity  0.20
  semantic_stability    0.20
  retrieval_integrity   0.15
  provenance_quality    0.20
  contamination_risk    0.15
  temporal_volatility   0.10
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from shared.logger.logger import get_logger

if TYPE_CHECKING:
    from shared.cis.clickhouse import ClickHouseClient

logger = get_logger("aether.cis.health_engine")


@dataclass
class GraphHealthIndex:
    tenant_id: str
    composite_score: float          # 0–100
    structural_integrity: float     # 0–1
    semantic_stability: float       # 0–1 (higher = more stable)
    retrieval_integrity: float      # 0–1
    provenance_quality: float       # 0–1
    contamination_risk: float       # 0–1 (higher = more risk)
    temporal_volatility: float      # 0–1 (higher = more volatile)
    computed_at: str = ""

    def __post_init__(self) -> None:
        if not self.computed_at:
            self.computed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "composite_score": round(self.composite_score, 2),
            "structural_integrity": round(self.structural_integrity, 4),
            "semantic_stability": round(self.semantic_stability, 4),
            "retrieval_integrity": round(self.retrieval_integrity, 4),
            "provenance_quality": round(self.provenance_quality, 4),
            "contamination_risk": round(self.contamination_risk, 4),
            "temporal_volatility": round(self.temporal_volatility, 4),
            "computed_at": self.computed_at,
        }


class GraphHealthEngine:
    """
    Aggregates CIS sub-scores into a composite health index.

    composite = 100 × (
      w_structural × structural_integrity +
      w_semantic   × (1 − semantic_drift)        ← inverted
      w_retrieval  × retrieval_integrity +
      w_provenance × provenance_quality +
      w_contam     × (1 − contamination_risk)    ← inverted
      w_volatility × (1 − temporal_volatility)   ← inverted
    )
    """

    def __init__(
        self,
        ch_client: "ClickHouseClient",
        *,
        w_structural: float = 0.20,
        w_semantic: float = 0.20,
        w_retrieval: float = 0.15,
        w_provenance: float = 0.20,
        w_contamination: float = 0.15,
        w_volatility: float = 0.10,
    ) -> None:
        self._ch = ch_client
        self._weights = {
            "structural": w_structural,
            "semantic": w_semantic,
            "retrieval": w_retrieval,
            "provenance": w_provenance,
            "contamination": w_contamination,
            "volatility": w_volatility,
        }

    def _compute_composite(
        self,
        structural: float,
        semantic_stability: float,
        retrieval: float,
        provenance: float,
        contamination: float,
        volatility: float,
    ) -> float:
        w = self._weights
        raw = (
            w["structural"]    * structural +
            w["semantic"]      * semantic_stability +
            w["retrieval"]     * retrieval +
            w["provenance"]    * provenance +
            w["contamination"] * (1.0 - contamination) +
            w["volatility"]    * (1.0 - volatility)
        )
        return round(min(100.0, max(0.0, raw * 100.0)), 2)

    async def compute(self, tenant_id: str) -> GraphHealthIndex:
        # Query recent ClickHouse data for each sub-score
        structural = await self._structural_integrity(tenant_id)
        semantic_stability = await self._semantic_stability(tenant_id)
        retrieval = await self._retrieval_integrity(tenant_id)
        provenance = await self._provenance_quality(tenant_id)
        contamination = await self._contamination_risk(tenant_id)
        volatility = await self._temporal_volatility(tenant_id)

        composite = self._compute_composite(
            structural, semantic_stability, retrieval,
            provenance, contamination, volatility,
        )
        index = GraphHealthIndex(
            tenant_id=tenant_id,
            composite_score=composite,
            structural_integrity=structural,
            semantic_stability=semantic_stability,
            retrieval_integrity=retrieval,
            provenance_quality=provenance,
            contamination_risk=contamination,
            temporal_volatility=volatility,
        )

        # Write to ClickHouse
        row = {
            "event_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "timestamp": index.computed_at,
            "composite_score": composite,
            "structural_integrity": structural,
            "semantic_stability": semantic_stability,
            "retrieval_integrity": retrieval,
            "provenance_quality": provenance,
            "contamination_risk": contamination,
            "temporal_volatility": volatility,
            "source_service": "cis.health_engine",
        }
        await self._ch.insert("cis_graph_health_telemetry", [row])

        # Update Postgres governance state
        await self._update_governance_state(index)
        return index

    async def _structural_integrity(self, tenant_id: str) -> float:
        try:
            rows = await self._ch.query(
                """
                SELECT countIf(risk_band = 'quarantine') AS quar,
                       count() AS total
                FROM cis_mutation_analytics
                WHERE tenant_id = {t:String}
                  AND timestamp >= now() - INTERVAL 7 DAY
                """,
                {"t": tenant_id},
            )
            if rows and rows[0].get("total", 0) > 0:
                return 1.0 - rows[0]["quar"] / rows[0]["total"]
        except Exception:
            pass
        return 1.0

    async def _semantic_stability(self, tenant_id: str) -> float:
        try:
            rows = await self._ch.query(
                """
                SELECT avg(composite_drift_score) AS avg_drift
                FROM cis_semantic_drift_metrics
                WHERE tenant_id = {t:String}
                  AND timestamp >= now() - INTERVAL 7 DAY
                """,
                {"t": tenant_id},
            )
            if rows and rows[0].get("avg_drift") is not None:
                return max(0.0, 1.0 - float(rows[0]["avg_drift"]))
        except Exception:
            pass
        return 1.0

    async def _retrieval_integrity(self, tenant_id: str) -> float:
        try:
            rows = await self._ch.query(
                """
                SELECT avg(grounded) AS avg_grounded
                FROM cis_retrieval_traces
                WHERE tenant_id = {t:String}
                  AND timestamp >= now() - INTERVAL 7 DAY
                """,
                {"t": tenant_id},
            )
            if rows and rows[0].get("avg_grounded") is not None:
                return float(rows[0]["avg_grounded"])
        except Exception:
            pass
        return 1.0

    async def _provenance_quality(self, tenant_id: str) -> float:
        try:
            from repositories.repos import get_pool
            pool = await get_pool()
            if pool:
                row = await pool.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE lineage_hash != '' AND array_length(parent_provenance_ids, 1) > 0)
                            AS with_lineage,
                        COUNT(*) AS total
                    FROM cis_provenance_records WHERE tenant_id = $1
                    """,
                    tenant_id,
                )
                if row and row["total"] > 0:
                    return row["with_lineage"] / row["total"]
        except Exception:
            pass
        return 0.5

    async def _contamination_risk(self, tenant_id: str) -> float:
        try:
            rows = await self._ch.query(
                """
                SELECT max(contamination_score) AS max_contam
                FROM cis_contamination_propagation
                WHERE tenant_id = {t:String}
                  AND timestamp >= now() - INTERVAL 7 DAY
                """,
                {"t": tenant_id},
            )
            if rows and rows[0].get("max_contam") is not None:
                return float(rows[0]["max_contam"])
        except Exception:
            pass
        return 0.0

    async def _temporal_volatility(self, tenant_id: str) -> float:
        try:
            rows = await self._ch.query(
                """
                SELECT
                    countIf(timestamp >= now() - INTERVAL 7 DAY)  AS week_count,
                    countIf(timestamp >= now() - INTERVAL 30 DAY) AS month_count
                FROM cis_mutation_analytics
                WHERE tenant_id = {t:String}
                """,
                {"t": tenant_id},
            )
            if rows:
                week = rows[0].get("week_count", 0)
                month = rows[0].get("month_count", 1)
                # Annualize: 7-day rate vs 30-day baseline rate
                if month > 0:
                    baseline = month / 30.0 * 7
                    volatility = min(1.0, week / max(1, baseline) - 1.0) if week > baseline else 0.0
                    return max(0.0, volatility)
        except Exception:
            pass
        return 0.0

    async def _update_governance_state(self, index: GraphHealthIndex) -> None:
        try:
            from repositories.repos import get_pool
            pool = await get_pool()
            if pool is None:
                return
            await pool.execute(
                """
                INSERT INTO cis_tenant_governance_state (
                    tenant_id, health_score, drift_score, contamination_index,
                    retrieval_integrity, provenance_coverage, last_computed_at
                ) VALUES ($1, $2, $3, $4, $5, $6, now())
                ON CONFLICT (tenant_id) DO UPDATE SET
                    health_score = EXCLUDED.health_score,
                    drift_score = EXCLUDED.drift_score,
                    contamination_index = EXCLUDED.contamination_index,
                    retrieval_integrity = EXCLUDED.retrieval_integrity,
                    provenance_coverage = EXCLUDED.provenance_coverage,
                    last_computed_at = now()
                """,
                index.tenant_id,
                index.composite_score,
                1.0 - index.semantic_stability,
                index.contamination_risk,
                index.retrieval_integrity,
                index.provenance_quality,
            )
        except Exception as e:
            logger.debug(f"Governance state update skipped: {e}")


class GlobalHealthAggregator:
    """Admin-only: aggregates health across all tenants."""

    def __init__(self, ch_client: "ClickHouseClient") -> None:
        self._ch = ch_client

    async def get_distribution(self) -> list[dict[str, Any]]:
        try:
            from repositories.repos import get_pool
            pool = await get_pool()
            if pool:
                rows = await pool.fetch(
                    "SELECT tenant_id, health_score, drift_score, contamination_index, "
                    "last_computed_at FROM cis_tenant_governance_state ORDER BY health_score ASC"
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.debug(f"GlobalHealthAggregator failed: {e}")
        return []
