"""
Aether Shared — CIS Mutation Gateway
Intercepts all graph write paths, computes mutation risk scores, and
enforces quarantine workflows before mutations reach the canonical graph.

Two intercept paths:
1. GraphStagingInterface.commit_mutation() — sync agent layer path
2. MutationGatewayMiddlewareMixin — async FastAPI route Depends() injection

Follows the ExtractionDefenseMesh architectural pattern.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from shared.logger.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("aether.cis.mutation_gateway")


def _cis_enabled() -> bool:
    return os.getenv("CIS_ENABLED", "false").lower() in ("true", "1")


# ─────────────────────────────────────────────────────────────────────────────
# Risk scoring
# ─────────────────────────────────────────────────────────────────────────────

# VertexType sensitivity tiers (high=1.0, medium=0.6, low=0.2)
_VERTEX_SENSITIVITY: dict[str, float] = {
    "USER": 1.0, "AGENT": 1.0, "AGENT_PROFILE360": 1.0,
    "IDENTITY_CLUSTER": 0.8, "DELEGATION": 0.8,
    "WALLET": 0.6, "PAYMENT_INTENT": 0.6,
    "ENTITY": 0.4, "ORGANIZATION": 0.4,
    "SESSION": 0.2, "PAGE_VIEW": 0.2, "EXTERNAL_DATA": 0.2,
}

# Mutation class base scores
_CLASS_SCORES = {1: 5.0, 2: 20.0, 3: 50.0, 4: 75.0, 5: 100.0}

_SIGNAL_WEIGHTS = {
    "mutation_class_risk": 0.25,
    "contamination_ancestry": 0.20,
    "synthetic_lineage_depth": 0.15,
    "agent_instability": 0.15,
    "provenance_depth": 0.10,
    "temporal_velocity": 0.10,
    "entity_sensitivity": 0.05,
}


@dataclass
class MutationRiskSignals:
    mutation_class: int = 1
    contamination_ancestry_ratio: float = 0.0  # % ancestors contaminated
    synthetic_lineage_ratio: float = 0.0        # synthetic nodes / depth
    agent_instability_score: float = 0.0        # from analytics history
    provenance_depth: int = 0                   # hops in lineage
    mutations_last_5min: int = 0                # temporal velocity
    baseline_mutations_per_5min: float = 1.0
    entity_type: str = "ENTITY"


@dataclass
class MutationRiskResult:
    score: float               # 0–100
    band: str                  # allow | log | alert | quarantine
    signals: MutationRiskSignals
    quarantined: bool = False
    quarantine_id: Optional[str] = None


class MutationRiskScorer:
    """7-signal weighted risk scorer for graph mutations."""

    def score(self, signals: MutationRiskSignals) -> float:
        class_score = _CLASS_SCORES.get(max(1, min(5, signals.mutation_class)), 20.0)
        provenance_score = max(0.0, 1.0 - signals.provenance_depth / 5.0) * 100.0
        velocity_ratio = min(1.0, signals.mutations_last_5min / max(1, signals.baseline_mutations_per_5min * 3))
        entity_sens = _VERTEX_SENSITIVITY.get(signals.entity_type.upper(), 0.4) * 100.0

        raw = (
            _SIGNAL_WEIGHTS["mutation_class_risk"]     * class_score +
            _SIGNAL_WEIGHTS["contamination_ancestry"]  * signals.contamination_ancestry_ratio * 100.0 +
            _SIGNAL_WEIGHTS["synthetic_lineage_depth"] * signals.synthetic_lineage_ratio * 100.0 +
            _SIGNAL_WEIGHTS["agent_instability"]       * signals.agent_instability_score * 100.0 +
            _SIGNAL_WEIGHTS["provenance_depth"]        * provenance_score +
            _SIGNAL_WEIGHTS["temporal_velocity"]       * velocity_ratio * 100.0 +
            _SIGNAL_WEIGHTS["entity_sensitivity"]      * entity_sens
        )
        return min(100.0, max(0.0, raw))

    @staticmethod
    def band(score: float) -> str:
        if score <= 30:
            return "allow"
        if score <= 60:
            return "log"
        if score <= 80:
            return "alert"
        return "quarantine"


# ─────────────────────────────────────────────────────────────────────────────
# Quarantine service
# ─────────────────────────────────────────────────────────────────────────────

class QuarantineService:
    """Persists quarantine records and emits CIS events."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []  # in-memory fallback
        self._pool: Optional[Any] = None

    async def _get_pool(self) -> Optional[Any]:
        if self._pool is not None:
            return self._pool
        try:
            from repositories.repos import get_pool
            self._pool = await get_pool()
        except Exception:
            pass
        return self._pool

    async def initiate(
        self,
        mutation_id: str,
        tenant_id: str,
        risk_score: float,
        risk_band: str,
        entity_id: str,
        entity_type: str,
        proposed_changes: dict[str, Any],
        originating_agent_id: Optional[str] = None,
    ) -> str:
        quarantine_id = str(uuid.uuid4())
        record = {
            "quarantine_id": quarantine_id,
            "mutation_id": mutation_id,
            "tenant_id": tenant_id,
            "risk_score": risk_score,
            "risk_band": risk_band,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "proposed_changes": proposed_changes,
            "originating_agent_id": originating_agent_id,
            "status": "quarantined",
            "initiated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._records.append(record)

        # Persist to Postgres if available
        pool = await self._get_pool()
        if pool is not None:
            try:
                import json
                await pool.execute(
                    """
                    INSERT INTO cis_quarantine_records (
                        quarantine_id, mutation_id, tenant_id, risk_score, risk_band,
                        originating_agent_id, entity_id, entity_type, proposed_changes,
                        status, initiated_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,now())
                    """,
                    quarantine_id, mutation_id, tenant_id, risk_score, risk_band,
                    originating_agent_id, entity_id, entity_type,
                    json.dumps(proposed_changes), "quarantined",
                )
            except Exception as e:
                logger.error(f"QuarantineService.initiate DB write failed: {e}")

        # Emit Kafka event
        try:
            from dependencies.providers import get_producer
            from shared.events.events import Event, Topic
            await get_producer().publish(Event(
                topic=Topic.CIS_QUARANTINE_INITIATED,
                tenant_id=tenant_id,
                source_service="cis.mutation_gateway",
                payload={
                    "quarantine_id": quarantine_id,
                    "mutation_id": mutation_id,
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "risk_score": risk_score,
                    "risk_band": risk_band,
                },
            ))
        except Exception as e:
            logger.debug(f"QuarantineService event emit skipped: {e}")

        logger.warning(
            f"Mutation quarantined: mutation_id={mutation_id[:8]} "
            f"risk={risk_score:.1f} tenant={tenant_id}"
        )
        return quarantine_id

    def list_quarantined(self) -> list[dict[str, Any]]:
        """Test helper."""
        return [r for r in self._records if r["status"] == "quarantined"]


# ─────────────────────────────────────────────────────────────────────────────
# Mutation Gateway
# ─────────────────────────────────────────────────────────────────────────────

class MutationGateway:
    """
    Orchestrates: risk scoring → policy → quarantine → event emission.
    Entry point for both the sync agent path and async HTTP path.
    """

    def __init__(self) -> None:
        self._scorer = MutationRiskScorer()
        self._quarantine = QuarantineService()

    async def evaluate_mutation(
        self,
        mutation_id: str,
        tenant_id: str,
        mutation_class: int,
        entity_id: str,
        entity_type: str,
        proposed_changes: dict[str, Any],
        originating_agent_id: Optional[str] = None,
        provenance_depth: int = 0,
        contamination_ancestry_ratio: float = 0.0,
        synthetic_lineage_ratio: float = 0.0,
        agent_instability_score: float = 0.0,
        mutations_last_5min: int = 0,
        baseline_mutations_per_5min: float = 1.0,
    ) -> MutationRiskResult:
        signals = MutationRiskSignals(
            mutation_class=mutation_class,
            contamination_ancestry_ratio=contamination_ancestry_ratio,
            synthetic_lineage_ratio=synthetic_lineage_ratio,
            agent_instability_score=agent_instability_score,
            provenance_depth=provenance_depth,
            mutations_last_5min=mutations_last_5min,
            baseline_mutations_per_5min=baseline_mutations_per_5min,
            entity_type=entity_type,
        )
        score = self._scorer.score(signals)
        band = MutationRiskScorer.band(score)
        result = MutationRiskResult(score=score, band=band, signals=signals)

        # Emit creation event
        await self._emit_mutation_event(
            topic_name="CIS_GRAPH_MUTATION_CREATED",
            mutation_id=mutation_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            entity_type=entity_type,
            score=score,
            band=band,
        )

        quarantine_on_high = os.getenv("CIS_QUARANTINE_HIGH_RISK", "true").lower() in ("true", "1")
        if band == "quarantine" and quarantine_on_high:
            q_id = await self._quarantine.initiate(
                mutation_id=mutation_id,
                tenant_id=tenant_id,
                risk_score=score,
                risk_band=band,
                entity_id=entity_id,
                entity_type=entity_type,
                proposed_changes=proposed_changes,
                originating_agent_id=originating_agent_id,
            )
            result.quarantined = True
            result.quarantine_id = q_id
        else:
            accepted_topic = "CIS_GRAPH_MUTATION_ACCEPTED" if band != "quarantine" else "CIS_GRAPH_MUTATION_REJECTED"
            await self._emit_mutation_event(
                topic_name=accepted_topic,
                mutation_id=mutation_id,
                tenant_id=tenant_id,
                entity_id=entity_id,
                entity_type=entity_type,
                score=score,
                band=band,
            )

        return result

    async def _emit_mutation_event(
        self,
        topic_name: str,
        mutation_id: str,
        tenant_id: str,
        entity_id: str,
        entity_type: str,
        score: float,
        band: str,
    ) -> None:
        try:
            from dependencies.providers import get_producer
            from shared.events.events import Event, Topic
            topic = getattr(Topic, topic_name)
            await get_producer().publish(Event(
                topic=topic,
                tenant_id=tenant_id,
                source_service="cis.mutation_gateway",
                payload={
                    "mutation_id": mutation_id,
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "risk_score": score,
                    "risk_band": band,
                },
            ))
        except Exception as e:
            logger.debug(f"MutationGateway event emit skipped: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton + lazy init
# ─────────────────────────────────────────────────────────────────────────────

_gateway: Optional[MutationGateway] = None


def get_gateway() -> MutationGateway:
    global _gateway
    if _gateway is None:
        _gateway = MutationGateway()
    return _gateway


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI route dependency mixin
# ─────────────────────────────────────────────────────────────────────────────

async def check_mutation_gateway(
    mutation_class: int = 1,
    entity_id: str = "",
    entity_type: str = "ENTITY",
    proposed_changes: Optional[dict[str, Any]] = None,
    tenant_id: str = "",
    originating_agent_id: Optional[str] = None,
) -> MutationRiskResult:
    """
    FastAPI Depends()-compatible entry point for HTTP route mutation checks.
    Routes inject this via Depends() to run the gateway before executing writes.
    Returns the risk result; callers decide whether to proceed based on .quarantined.
    """
    if not _cis_enabled():
        return MutationRiskResult(
            score=0.0, band="allow",
            signals=MutationRiskSignals(), quarantined=False
        )
    mutation_id = str(uuid.uuid4())
    return await get_gateway().evaluate_mutation(
        mutation_id=mutation_id,
        tenant_id=tenant_id,
        mutation_class=mutation_class,
        entity_id=entity_id,
        entity_type=entity_type,
        proposed_changes=proposed_changes or {},
        originating_agent_id=originating_agent_id,
    )
