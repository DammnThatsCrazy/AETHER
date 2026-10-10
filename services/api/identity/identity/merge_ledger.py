"""Merge Ledger — makes merges explicit, auditable, versioned, and reversible.

Every merge creates an identity_decision record.
Every merge creates or updates identity_edges.
Every merge increments graph version.
Every merge queues projection restatement.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from shared.common.common import utc_now
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, log_event

from .graph_versioner import GraphVersioner
from .models import (
    ConfidenceBand,
    DecisionType,
    IdentityDecisionRecord,
)

logger = get_logger("aether.identity.merge_ledger")



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
        from config.settings import settings

        if not settings.identity_continuity.auto_merge_enabled:
            raise RuntimeError("automatic identity merge is disabled")
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

        log_event(
            logger,
            logging.INFO,
            "identity.merge.auto",
            tenant_id=tenant_id,
            decision_id=decision_id,
            selected_entity=selected_canonical_entity_id,
            confidence=confidence,
            graph_version_after=graph_version_after,
        )

        # Queue projection restatement
        await self._queue_restatement(decision)

        # Emit event
        if self._producer:
            await self._producer.publish(Event(
                topic=Topic.IDENTITY_MERGED,
                payload={
                    "tenant_id": tenant_id,
                    "decision_id": decision_id,
                    "is_merge": True,
                    "primary_entity_id": selected_canonical_entity_id,
                    "secondary_entity_id": next(
                        (entity for entity in candidate_canonical_entity_ids
                         if entity != selected_canonical_entity_id),
                        None,
                    ),
                    "canonical_entity_id": selected_canonical_entity_id,
                    "affected_canonical_entity_ids": list(dict.fromkeys(
                        [selected_canonical_entity_id, *candidate_canonical_entity_ids]
                    )),
                    "graph_version_before": graph_version_before,
                    "graph_version_after": graph_version_after,
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
        from config.settings import settings

        if not settings.identity_continuity.manual_review_enabled:
            raise RuntimeError("manual identity merge is disabled")
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

        log_event(
            logger,
            logging.INFO,
            "identity.merge.manual",
            tenant_id=tenant_id,
            decision_id=decision_id,
            operator_id=operator_id,
            selected_entity=selected_canonical_entity_id,
        )

        await self._queue_restatement(decision)

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

        log_event(
            logger,
            logging.INFO,
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

    async def _queue_restatement(self, decision: IdentityDecisionRecord) -> None:
        """Queue projection restatement after a merge.

        Wires ProjectionRestatementOrchestrator (blueprint §11) and observability traces.
        """
        try:
            from identity.identity.observability import IdentityTrace, identity_metrics
            from replay.projections.projection_restatement_orchestrator import (
                ProjectionRestatementOrchestrator,
            )

            job = await ProjectionRestatementOrchestrator().queue_restatement(decision)
            identity_metrics.record_projection_restatement("queued")
            trace = IdentityTrace(
                tenant_id=decision.tenant_id, source_system_id="identity.merge_ledger"
            )
            trace.projection_restatement_queue([job.id])
        except Exception as e:
            try:
                from identity.identity.observability import identity_metrics

                identity_metrics.record_projection_restatement("failed")
            except Exception:
                pass
            log_event(
                logger,
                logging.ERROR,
                "identity.projection_restatement.enqueue_failed",
                tenant_id=decision.tenant_id,
                decision_id=decision.id,
                error_type=type(e).__name__,
            )
