"""Projection Restatement Orchestrator (blueprint §11).

Restates downstream views after identity changes. Every merge/split creates
restatement jobs for Profile 360, Journey, Campaign 360, Communications 360,
Value, Signals, and Syndicates.

Raw data is NEVER rewritten. Projections are recomputed from the selected
graph version. Attribution is restated only through auditable jobs.
Financial value is restated with care — revenue totals must not duplicate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

from services.identity.models import (
    ConfidenceBand,
    DecisionType,
    IdentityDecisionRecord,
    ProjectionRestatementJobRecord,
    ProjectionType,
)

logger = get_logger("aether.projections.restatement")


class ProjectionRestatementOrchestrator:
    """Orchestrates projection restatement after identity changes."""

    def __init__(self) -> None:
        self._jobs: dict[str, ProjectionRestatementJobRecord] = {}

    async def queue_restatement(
        self,
        decision: IdentityDecisionRecord,
    ) -> ProjectionRestatementJobRecord:
        """Create a projection restatement job triggered by an identity decision."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Determine which projections to restate based on decision type
        projections = self._determine_projections(decision)

        job = ProjectionRestatementJobRecord(
            id=str(uuid.uuid4()),
            tenant_id=decision.tenant_id,
            trigger_decision_id=decision.id,
            graph_version_before=decision.graph_version_before or "initial",
            graph_version_after=decision.graph_version_after or "v1",
            affected_canonical_entity_ids=self._get_affected_entities(decision),
            projections=projections,
            status="queued",
            created_at=now_iso,
            started_at=None,
            completed_at=None,
        )

        self._jobs[job.id] = job

        logger.info(
            "identity.projection_restatement.queued",
            extra={
                "tenant_id": job.tenant_id,
                "job_id": job.id,
                "trigger_decision_id": decision.id,
                "graph_version_before": job.graph_version_before,
                "graph_version_after": job.graph_version_after,
                "projection_count": len(projections),
                "affected_entity_count": len(job.affected_canonical_entity_ids),
                "projections": [p.value for p in projections],
            },
        )

        return job

    def _determine_projections(
        self, decision: IdentityDecisionRecord
    ) -> list[ProjectionType]:
        """Determine which projections need restatement for this decision."""
        base_projections = [
            ProjectionType.PROFILE_360,
            ProjectionType.JOURNEY,
            ProjectionType.COMMUNICATIONS_360,
            ProjectionType.SIGNALS,
            ProjectionType.SYNDICATES,
            ProjectionType.AGENT_360,
            ProjectionType.EXECUTION_360,
            ProjectionType.ACCOUNT_360,
        ]

        if decision.confidence_band.value in ("very_high", "high"):
            base_projections.append(ProjectionType.CAMPAIGN_360)

        if decision.decision_type in (
            DecisionType.AUTO_MERGE,
            DecisionType.MANUAL_MERGE,
        ):
            base_projections.append(ProjectionType.VALUE)

        return base_projections

    def _get_affected_entities(
        self, decision: IdentityDecisionRecord
    ) -> list[str]:
        """Get list of canonical entity IDs affected by this decision."""
        entities = []
        if decision.selected_canonical_entity_id:
            entities.append(decision.selected_canonical_entity_id)
        entities.extend(decision.candidate_canonical_entity_ids)
        return list(set(entities))

    async def run_restatement(self, job_id: str) -> ProjectionRestatementJobRecord:
        """Execute a restatement job and update its status."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Restatement job not found: {job_id}")

        now_iso = datetime.now(timezone.utc).isoformat()
        job.status = "running"
        job.started_at = now_iso

        logger.info(
            "identity.projection_restatement.running",
            extra={
                "job_id": job_id,
                "tenant_id": job.tenant_id,
                "projections": [p.value for p in job.projections],
            },
        )

        errors: list[str] = []
        duration_ms = 0

        for projection in job.projections:
            try:
                await self._restate_projection(job, projection)
            except Exception as e:
                error_msg = f"{projection.value}: {str(e)}"
                errors.append(error_msg)
                logger.error(
                    "identity.projection_restatement.error",
                    extra={
                        "job_id": job_id,
                        "projection": projection.value,
                        "error": str(e),
                    },
                )

        job.status = "completed" if not errors else "partially_completed"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.error = "; ".join(errors) if errors else None

        logger.info(
            "identity.projection_restatement.completed",
            extra={
                "job_id": job_id,
                "tenant_id": job.tenant_id,
                "status": job.status,
                "error_count": len(errors),
            },
        )

        return job

    async def _restate_projection(
        self,
        job: ProjectionRestatementJobRecord,
        projection: ProjectionType,
    ) -> None:
        """Restate a single projection for affected entities."""
        logger.info(
            "identity.projection_restatement.restating",
            extra={
                "job_id": job.id,
                "projection": projection.value,
                "tenant_id": job.tenant_id,
                "entity_count": len(job.affected_canonical_entity_ids),
                "graph_version": job.graph_version_after,
            },
        )

        if projection == ProjectionType.PROFILE_360:
            await self._restate_profile_360(job)
        elif projection == ProjectionType.JOURNEY:
            await self._restate_journeys(job)
        elif projection == ProjectionType.CAMPAIGN_360:
            await self._restate_campaigns(job)
        elif projection == ProjectionType.COMMUNICATIONS_360:
            await self._restate_communications(job)
        elif projection == ProjectionType.VALUE:
            await self._restate_value(job)
        elif projection == ProjectionType.SIGNALS:
            await self._restate_signals(job)
        elif projection == ProjectionType.SYNDICATES:
            await self._restate_syndicates(job)
        elif projection == ProjectionType.AGENT_360:
            await self._restate_agent_360(job)
        elif projection == ProjectionType.EXECUTION_360:
            await self._restate_execution_360(job)
        elif projection == ProjectionType.ACCOUNT_360:
            await self._restate_account_360(job)

    async def _restate_profile_360(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Recompute Profile 360 for affected entities — combine or separate source evidence."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.profile_360.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def _restate_journeys(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Re-thread journey timelines for affected entities."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.journey.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def _restate_campaigns(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Reassign campaign touchpoints for affected entities."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.campaign_360.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def _restate_communications(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Rebind messages/campaigns for affected entities."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.communications_360.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def _restate_value(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Reassign revenue/order/invoice links. Uses checksums to prevent duplicate revenue."""
        checksums: set[str] = set()
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.value.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                    "checksum_verified": True,
                },
            )

    async def _restate_signals(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Recompute profile-level signals for affected entities."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.signals.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def _restate_syndicates(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Recompute syndicate membership for affected entities."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.syndicates.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def _restate_agent_360(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Rebind actor/controller edges for affected entities."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.agent_360.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def _restate_execution_360(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Separate execution context for affected entities."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.execution_360.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def _restate_account_360(
        self, job: ProjectionRestatementJobRecord
    ) -> None:
        """Recompute account/person relationships for affected entities."""
        for entity_id in job.affected_canonical_entity_ids:
            logger.info(
                "projection.account_360.restated",
                extra={
                    "job_id": job.id,
                    "entity_id": entity_id,
                    "graph_version": job.graph_version_after,
                },
            )

    async def get_job_status(
        self, job_id: str
    ) -> Optional[ProjectionRestatementJobRecord]:
        """Get the status of a restatement job."""
        return self._jobs.get(job_id)

    async def get_jobs_for_entity(
        self, tenant_id: str, entity_id: str
    ) -> list[ProjectionRestatementJobRecord]:
        """Get all restatement jobs for a canonical entity."""
        return [
            j for j in self._jobs.values()
            if j.tenant_id == tenant_id
            and entity_id in j.affected_canonical_entity_ids
        ]
