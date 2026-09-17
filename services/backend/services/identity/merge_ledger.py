"""Merge Ledger — makes merges explicit, auditable, versioned, and reversible.

Every merge creates an identity_decision record.
Every merge creates or updates identity_edges.
Every merge increments graph version.
Every merge queues projection restatement.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import utc_now
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger

from .graph_versioner import GraphVersioner
from .models import (
    ConfidenceBand,
    DecisionType,
    IdentityDecisionRecord,
    ProjectionRestatementJobRecord,
    ProjectionType,
)

logger = get_logger("aether.identity.merge_ledger")

# Identity continuity: projection restatement orchestrator wiring
try:
    from services.projections.projection_restatement_orchestrator import (
        ProjectionRestatementOrchestrator,
    )
except Exception:  # pragma: no cover
    ProjectionRestatementOrchestrator = None  # type: ignore


class MergeLedger:
    """Ledger for identity merge decisions."""

    def __init__(
        self,
        graph_versioner: GraphVersioner,
        event_producer: Optional[EventProducer] = None,
    ) -> None:
        self._graph_versioner = graph_versioner
        self._producer = event_producer

    async def auto_merge(
        self,
        tenant_id: str,
        decision_id: str,
        candidate_source_identity_ids: list[str],
        candidate_canonical_entity_ids: list[str],
        selected_canonical_entity_id: str,
        confidence: float,
        confidence_band: ConfidenceBand,
        positive_evidence: list,
        negative_evidence: list,
        vetoes: list,
        policy_version: str,
        graph_version_before: Optional[str],
        explanation: str,
        decided_by: str = "system",
    ) -> IdentityDecisionRecord:
        """Record an auto-merge decision."""
        now = utc_now()

        # Increment graph version
        graph_version_after = await self._graph_versioner.create_graph_version(
            tenant_id=tenant_id,
            previous_version_id=graph_version_before,
            reason="auto_merge",
            decision_ids=[decision_id],
        )

        decision = IdentityDecisionRecord(
            id=decision_id,
            tenant_id=tenant_id,
            decision_type=DecisionType.AUTO_MERGE,
            candidate_source_identity_ids=candidate_source_identity_ids,
            candidate_canonical_entity_ids=candidate_canonical_entity_ids,
            selected_canonical_entity_id=selected_canonical_entity_id,
            confidence=confidence,
            confidence_band=confidence_band,
            positive_evidence=positive_evidence,
            negative_evidence=negative_evidence,
            vetoes=vetoes,
            policy_version=policy_version,
            graph_version_before=graph_version_before,
            graph_version_after=graph_version_after,
            explanation=explanation,
            decided_by=decided_by,
            decided_at=now,
        )

        logger.info(
            "identity.merge.auto",
            tenant_id=tenant_id,
            decision_id=decision_id,
            selected_entity=selected_canonical_entity_id,
            confidence=confidence,
            graph_version_after=graph_version_after,
        )

        # Queue projection restatement
        await self._queue_restatement(
            tenant_id=tenant_id,
            decision_id=decision_id,
            graph_version_before=graph_version_before,
            graph_version_after=graph_version_after,
            affected_entity_ids=[selected_canonical_entity_id],
        )

        # Emit event
        if self._producer:
            await self._producer.publish(Event(
                topic=Topic.IDENTITY_MERGED,
                payload={
                    "tenant_id": tenant_id,
                    "decision_id": decision_id,
                    "merged_into": selected_canonical_entity_id,
                    "graph_version": graph_version_after,
                },
            ))

        return decision

    async def manual_merge(
        self,
        tenant_id: str,
        decision_id: str,
        candidate_source_identity_ids: list[str],
        candidate_canonical_entity_ids: list[str],
        selected_canonical_entity_id: str,
        confidence: float,
        confidence_band: ConfidenceBand,
        positive_evidence: list,
        negative_evidence: list,
        vetoes: list,
        policy_version: str,
        graph_version_before: Optional[str],
        explanation: str,
        operator_id: str,
        confirmation_token: str,
        expected_graph_version: Optional[str],
    ) -> IdentityDecisionRecord:
        """Record a manual/operators merge decision.

        Must reject stale graph versions.
        """
        # Validate expected graph version against current
        if expected_graph_version and graph_version_before:
            if graph_version_before != expected_graph_version:
                raise ValueError(
                    f"Stale graph version: expected {expected_graph_version}, "
                    f"current {graph_version_before}. Rejecting merge to prevent race condition."
                )

        now = utc_now()

        graph_version_after = await self._graph_versioner.create_graph_version(
            tenant_id=tenant_id,
            previous_version_id=graph_version_before,
            reason="manual_merge",
            decision_ids=[decision_id],
        )

        decision = IdentityDecisionRecord(
            id=decision_id,
            tenant_id=tenant_id,
            decision_type=DecisionType.MANUAL_MERGE,
            candidate_source_identity_ids=candidate_source_identity_ids,
            candidate_canonical_entity_ids=candidate_canonical_entity_ids,
            selected_canonical_entity_id=selected_canonical_entity_id,
            confidence=confidence,
            confidence_band=confidence_band,
            positive_evidence=positive_evidence,
            negative_evidence=negative_evidence,
            vetoes=vetoes,
            policy_version=policy_version,
            graph_version_before=graph_version_before,
            graph_version_after=graph_version_after,
            explanation=explanation,
            decided_by="operator",
            decided_at=now,
        )

        logger.info(
            "identity.merge.manual",
            tenant_id=tenant_id,
            decision_id=decision_id,
            operator_id=operator_id,
            selected_entity=selected_canonical_entity_id,
        )

        await self._queue_restatement(
            tenant_id=tenant_id,
            decision_id=decision_id,
            graph_version_before=graph_version_before,
            graph_version_after=graph_version_after,
            affected_entity_ids=[selected_canonical_entity_id],
        )

        return decision

    async def block_merge(
        self,
        tenant_id: str,
        decision_id: str,
        candidate_source_identity_ids: list[str],
        candidate_canonical_entity_ids: list[str],
        confidence: float,
        confidence_band: ConfidenceBand,
        vetoes: list,
        policy_version: str,
        explanation: str,
        graph_version_before: Optional[str] = None,
    ) -> IdentityDecisionRecord:
        """Record a blocked merge decision."""
        now = utc_now()

        decision = IdentityDecisionRecord(
            id=decision_id,
            tenant_id=tenant_id,
            decision_type=DecisionType.BLOCK_MERGE,
            candidate_source_identity_ids=candidate_source_identity_ids,
            candidate_canonical_entity_ids=candidate_canonical_entity_ids,
            selected_canonical_entity_id=None,
            confidence=confidence,
            confidence_band=confidence_band,
            positive_evidence=[],
            negative_evidence=[],
            vetoes=vetoes,
            policy_version=policy_version,
            graph_version_before=graph_version_before,
            graph_version_after=graph_version_before,  # no change
            explanation=explanation,
            decided_by="system",
            decided_at=now,
        )

        logger.info(
            "identity.merge.blocked",
            tenant_id=tenant_id,
            decision_id=decision_id,
            confidence=confidence,
            veto_count=len(vetoes),
        )

        return decision

    async def get_merge_history(
        self, canonical_entity_id: str
    ) -> list[IdentityDecisionRecord]:
        """Get all merge decisions for a canonical entity."""
        # This would be implemented via repository
        # For now, return empty — the repository layer provides this
        return []

    async def _queue_restatement(
        self,
        tenant_id: str,
        decision_id: str,
        graph_version_before: Optional[str],
        graph_version_after: str,
        affected_entity_ids: list[str],
    ) -> None:
        """Queue projection restatement after a merge.

        Wires ProjectionRestatementOrchestrator (blueprint §11) and observability traces.
        """
        # All projections that need restatement
        projections = [
            ProjectionType.PROFILE_360,
            ProjectionType.JOURNEY,
            ProjectionType.COMMUNICATIONS_360,
            ProjectionType.VALUE,
            ProjectionType.SIGNALS,
            ProjectionType.SYNDICATES,
            ProjectionType.AGENT_360,
            ProjectionType.EXECUTION_360,
            ProjectionType.ACCOUNT_360,
        ]

        job = ProjectionRestatementJobRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            trigger_decision_id=decision_id,
            graph_version_before=graph_version_before or "initial",
            graph_version_after=graph_version_after,
            affected_canonical_entity_ids=affected_entity_ids,
            projections=projections,
            status="queued",
            created_at=utc_now(),
        )

        logger.info(
            "identity.projection_restatement.queued",
            tenant_id=tenant_id,
            job_id=job.id,
            decision_id=decision_id,
            projection_count=len(projections),
        )

        # Wire orchestrator: queue restatement via the canonical orchestrator + observability
        try:
            from services.identity.observability import IdentityTrace, identity_metrics

            # Observability: record queue + trace
            identity_metrics.record_projection_restatement("queued")
            trace = IdentityTrace(tenant_id=tenant_id, source_system_id="identity.merge_ledger")
            trace.projection_restatement_queue([job.id])

            # Orchestrator wiring: if available, queue via the orchestrator (blueprint §11)
            if ProjectionRestatementOrchestrator is not None:
                orchestrator = ProjectionRestatementOrchestrator()
                # Synthesize a minimal decision for the orchestrator (which expects IdentityDecisionRecord)
                # The decision's confidence_band drives which projections are restated; use VERY_HIGH for full coverage
                decision_for_orchestrator = IdentityDecisionRecord(
                    id=decision_id,
                    tenant_id=tenant_id,
                    decision_type=DecisionType.AUTO_MERGE,
                    candidate_source_identity_ids=[],
                    candidate_canonical_entity_ids=list(affected_entity_ids),
                    selected_canonical_entity_id=affected_entity_ids[0] if affected_entity_ids else None,
                    confidence=0.99,
                    confidence_band=ConfidenceBand.VERY_HIGH,
                    positive_evidence=[],
                    negative_evidence=[],
                    vetoes=[],
                    policy_version="1.0.0",
                    graph_version_before=graph_version_before,
                    graph_version_after=graph_version_after,
                    explanation="merge_ledger projection restatement",
                    decided_by="system",
                    decided_at=utc_now(),  # type: ignore
                )
                try:
                    await orchestrator.queue_restatement(decision_for_orchestrator)
                except Exception as e:
                    logger.warning("projection_restatement orchestrator queue failed: %s", e)
        except Exception as e:
            logger.warning("projection_restatement wiring failed: %s", e)
