"""Durable, tenant-scoped projection restatement orchestration.

Identity decisions enqueue ``identity.projection_restatement`` on the shared
jobs platform. The platform owns persistence, retries, and observable job events.
Only executors that perform work report completion; surfaces without an executor
remain explicitly unsupported in the job result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

from identity.identity.models import (
    DecisionType,
    IdentityDecisionRecord,
    ProjectionRestatementJobRecord,
    ProjectionType,
)
from replay.projections.syndicates_restatement_capability import (
    syndicates_restatement_evidence,
)

logger = get_logger("aether.projections.restatement")
PROJECTION_RESTATEMENT_JOB_TYPE = "identity.projection_restatement"

# Unsupported capabilities have stable machine-readable contract evidence.
_UNSUPPORTED_PROJECTION_REASONS: dict[str, dict[str, Any]] = {
    ProjectionType.SYNDICATES.value: syndicates_restatement_evidence(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_from_payload(payload: dict[str, Any]) -> ProjectionRestatementJobRecord:
    data = payload["restatement"]
    return ProjectionRestatementJobRecord(
        id=str(data["id"]),
        tenant_id=str(data["tenant_id"]),
        trigger_decision_id=str(data["trigger_decision_id"]),
        graph_version_before=str(data["graph_version_before"]),
        graph_version_after=str(data["graph_version_after"]),
        affected_canonical_entity_ids=list(data["affected_canonical_entity_ids"]),
        projections=[ProjectionType(value) for value in data["projections"]],
        status=str(data.get("status", "queued")),
        error=data.get("error"),
        created_at=str(data["created_at"]),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        resolution_revision_before=data.get("resolution_revision_before"),
        resolution_revision_after=data.get("resolution_revision_after"),
    )


def _record_payload(job: ProjectionRestatementJobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "trigger_decision_id": job.trigger_decision_id,
        "graph_version_before": job.graph_version_before,
        "graph_version_after": job.graph_version_after,
        "affected_canonical_entity_ids": list(job.affected_canonical_entity_ids),
        "projections": [p.value for p in job.projections],
        "status": job.status,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "resolution_revision_before": job.resolution_revision_before,
        "resolution_revision_after": job.resolution_revision_after,
        "projection_status": {},
    }


async def _recompute_campaign_360(
    tenant_id: str, entity_ids: list[str], restatement_key: str
) -> dict[str, int]:
    """Refresh Campaign 360 evidence and attribution gold for affected profiles.

    Campaign overview/population is composed from canonical tenant-scoped
    repositories. Attribution's existing Gold materializer writes the durable
    campaign performance rows after the Journey projection has rebuilt runs.
    """
    from datetime import date, datetime

    from journeys.campaign.exploration import CampaignPopulationExplorer
    from journeys.measurement.engine.gold_materializer import (
        materialize_campaign_performance_daily,
    )
    from journeys.measurement.repositories.attribution_run_repo import AttributionRunRepository
    from journeys.measurement.repositories.conversion_repo import ConversionRepository
    from journeys.measurement.repositories.journey_repo import JourneyRepository
    from journeys.measurement.repositories.spend_repo import SpendRepository
    from journeys.measurement.repositories.touchpoint_repo import TouchpointRepository

    touchpoints = TouchpointRepository()
    conversions = ConversionRepository()
    explorer = CampaignPopulationExplorer(
        touchpoints,
        conversions,
        AttributionRunRepository(),
        JourneyRepository(),
        SpendRepository(),
    )
    materialized_days: set[date] = set()
    campaigns: set[str] = set()
    for entity_id in entity_ids:
        profile_touchpoints = await touchpoints.list_by_profile(
            tenant_id, entity_id, identity_type="profile", limit=10000
        )
        campaigns.update(
            str(row["campaign_id"])
            for row in profile_touchpoints
            if row.get("campaign_id")
        )
        profile_conversions = await conversions.list_by_profile(
            tenant_id, entity_id, identity_type="profile",
            attribution_eligible_only=True, limit=10000,
        )
        for row in profile_conversions:
            campaign_id = row.get("campaign_id")
            if campaign_id:
                campaigns.add(str(campaign_id))
            occurred_at = row.get("occurred_at")
            if isinstance(occurred_at, datetime):
                materialized_days.add(occurred_at.date())
            elif occurred_at:
                try:
                    materialized_days.add(datetime.fromisoformat(
                        str(occurred_at).replace("Z", "+00:00")
                    ).date())
                except ValueError:
                    raise ValueError("campaign conversion has invalid occurred_at")

    # Exercise the canonical Campaign 360 reconciler for each affected campaign
    # so its population, conversion, spend, and active-credit views are refreshed.
    for campaign_id in sorted(campaigns):
        await explorer.get_overview(tenant_id, campaign_id)

    gold_rows = 0
    for target_day in sorted(materialized_days):
        gold_rows += await materialize_campaign_performance_daily(
            tenant_id,
            target_day,
            restatement_reason=f"identity_restatement:{restatement_key}",
        )
    return {"campaigns_recomputed": len(campaigns), "gold_rows_written": gold_rows}


async def _recompute_value_for_entity(
    tenant_id: str, entity_id: str, restatement_key: str
) -> int:
    """Rebuild a tenant-scoped profile value rollup and persist it idempotently."""
    import hashlib

    from identity.profile.aggregator import Profile360Aggregator
    from value.value.repositories import ValueSnapshotService

    financials_view = await Profile360Aggregator().financials(entity_id, tenant_id)
    financials = financials_view.get("summary")
    if not isinstance(financials, dict):
        raise RuntimeError("profile financial value materializer returned no financials")
    rollup_status = financials.get("rollup_status")
    if not rollup_status:
        raise RuntimeError("profile financial value materializer returned no rollup status")
    service = ValueSnapshotService()
    written = 0
    for metric, field in (
        ("identity_inflow", "inflow_usd"),
        ("identity_outflow", "outflow_usd"),
        ("identity_net_flow", "net_usd"),
    ):
        stable_key = hashlib.sha256(
            f"{restatement_key}:{tenant_id}:{entity_id}:{metric}".encode()
        ).hexdigest()
        await service.record_rollup(
            tenant_id,
            metric,
            {
                "total_usd": financials.get(field),
                "rollup_status": rollup_status,
                "unpriced_count": financials.get("unpriced_count", 0),
                "excluded_count": financials.get("excluded_count", 0),
            },
            snapshot_id=f"identity_restatement_{stable_key}",
            entity_id=entity_id,
            restatement_key=restatement_key,
        )
        written += 1
    return written


async def _recompute_agent_360_for_entity(tenant_id: str, entity_id: str) -> None:
    """Recompose the existing tenant-scoped Agent Profile 360 view.

    AgentProfile360Composer is the authoritative read composer for agent
    identity, ownership, delegations, task history, tools, and economic state.
    The surface is composed from durable repositories on demand; this refreshes
    that view without inventing a second snapshot store.
    """
    from identity.profile.agent import AgentProfile360Composer

    profile = await AgentProfile360Composer().compose(entity_id, tenant_id)
    if not isinstance(profile, dict):
        raise RuntimeError("agent profile composer returned no profile")
    if profile.get("tenant_id") != tenant_id or profile.get("agent_id") != entity_id:
        raise RuntimeError("agent profile composer returned a mismatched scope")


async def _recompute_execution_360_for_entity(
    tenant_id: str, entity_id: str
) -> None:
    """Refresh the canonical agent execution section through its existing composer.

    Execution 360 currently has no independent materialized projection. Its
    authoritative execution rollup is the ``task_history`` section produced by
    AgentProfile360Composer from tenant-filtered AgentExecutionRepository rows.
    Recompose and validate that section so this job does not claim an unrelated
    raw execution-table read as a completed projection.
    """
    from identity.profile.agent import AgentProfile360Composer

    profile = await AgentProfile360Composer().compose(entity_id, tenant_id)
    if not isinstance(profile, dict):
        raise RuntimeError("execution profile composer returned no profile")
    if profile.get("tenant_id") != tenant_id or profile.get("agent_id") != entity_id:
        raise RuntimeError("execution profile composer returned a mismatched scope")
    task_history = profile.get("task_history")
    if not isinstance(task_history, dict) or "execution_count" not in task_history:
        raise RuntimeError("agent profile composer returned no execution rollup")


class Account360ProjectionComposer:
    """Recompose Account 360 from the existing account authorities.

    Account ownership and people relationships are owned by
    ``OrganizationRepository``. Tenant suspension/deletion state is owned by
    ``AccountLifecycleService``. This read composer deliberately creates no
    duplicate account graph, relationship table, or snapshot store.
    """

    def __init__(
        self,
        organization_repository=None,
        lifecycle_service=None,
        identity_repository=None,
    ) -> None:
        self._organization_repository = organization_repository
        self._lifecycle_service = lifecycle_service
        self._identity_repository = identity_repository

    async def compose(
        self, tenant_id: str, affected_entity_ids: list[str]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not tenant_id:
            raise ValueError("tenant_id is required for Account 360 recomposition")
        from tenancy.account_lifecycle.service import account_lifecycle_service
        from tenancy.account_organization.repository import OrganizationRepository
        from identity.identity.hashing import hash_value
        from identity.identity.models import EntityType, IdentitySignalType, SubjectStatus
        from identity.identity.repository import IdentityResolutionRepository

        organizations = self._organization_repository or OrganizationRepository()
        lifecycle = self._lifecycle_service or account_lifecycle_service
        identities = self._identity_repository or IdentityResolutionRepository()
        organization = await organizations.get_profile(tenant_id)
        if organization is None:
            raise RuntimeError("Account 360 organization source is unavailable")
        if organization.get("tenant_id") != tenant_id:
            raise RuntimeError("Account 360 organization source returned a foreign tenant")

        members = []
        offset = 0
        while True:
            page = await organizations.list_members(tenant_id, limit=1000, offset=offset)
            members.extend(page)
            if len(page) < 1000:
                break
            offset += len(page)
        if any(row.get("tenant_id") != tenant_id for row in members):
            raise RuntimeError("Account 360 membership source returned a foreign tenant")
        active_members = [row for row in members if row.get("status") == "active"]
        owner_user_id = organization.get("owner_user_id")
        member_by_user_id = {
            str(row["user_id"]): row for row in active_members if row.get("user_id")
        }
        if owner_user_id:
            member_by_user_id.setdefault(str(owner_user_id), {"role": "owner"})
        person_relationships: dict[str, dict[str, str]] = {}
        for user_id, member in member_by_user_id.items():
            # Organization membership stores authentication principal IDs. They
            # are not canonical graph IDs, so bridge only through the active,
            # tenant-scoped USER_ID alias authority. Never equate the strings.
            user_id_hash = hash_value(user_id, scope=f"user:{tenant_id}")
            if not user_id_hash:
                continue
            candidates = await identities.find_entities_by_alias(
                tenant_id, IdentitySignalType.USER_ID, user_id_hash
            )
            surviving_people: set[str] = set()
            for candidate_id in candidates:
                survivor = await identities.resolve_surviving_canonical_entity_id(
                    tenant_id, candidate_id
                )
                if not survivor:
                    continue
                subject = await identities.get_subject_by_canonical_entity_id(
                    tenant_id, survivor
                )
                if (
                    subject is None
                    or subject.get("tenant_id") != tenant_id
                    or subject.get("status") != SubjectStatus.ACTIVE.value
                    or subject.get("entity_type") != EntityType.HUMAN.value
                ):
                    continue
                surviving_people.add(str(survivor))
            if len(surviving_people) > 1:
                raise RuntimeError(
                    "Account 360 user identity resolves to multiple canonical people"
                )
            if not surviving_people:
                continue
            canonical_person_id = next(iter(surviving_people))
            is_owner = user_id == str(owner_user_id)
            person_relationships[canonical_person_id] = {
                "canonical_entity_id": canonical_person_id,
                "relationship": "owner" if is_owner else "member",
                "role": "owner" if is_owner else str(member.get("role") or "unknown"),
            }
        if not person_relationships:
            raise RuntimeError("Account 360 has no canonical account/person relationships")
        owner_canonical_entity_id = next(
            (
                entity_id
                for entity_id, relationship in person_relationships.items()
                if relationship["relationship"] == "owner"
            ),
            None,
        )

        lifecycle_state = await lifecycle.get_projection_state(tenant_id)
        if lifecycle_state.get("tenant_id") != tenant_id:
            raise RuntimeError("Account 360 lifecycle source returned a foreign tenant")
        required_lifecycle = {"tenant_status", "deletion_status"}
        if not required_lifecycle.issubset(lifecycle_state):
            raise RuntimeError("Account 360 lifecycle source returned incomplete state")

        affected = {
            str(value)
            for value in affected_entity_ids
            if value
        }
        relationships = [person_relationships[key] for key in sorted(person_relationships)]
        matched = [
            row for row in relationships
            if row["canonical_entity_id"] in affected
        ]
        if not matched:
            raise RuntimeError("Account 360 has no affected canonical people linked to the account")
        view = {
            "tenant_id": tenant_id,
            "organization_id": str(organization.get("organization_id") or organization.get("id") or ""),
            "organization_status": str(organization.get("status") or "unknown"),
            "owner_canonical_entity_id": owner_canonical_entity_id,
            "people": relationships,
            "lifecycle": {
                "tenant_status": str(lifecycle_state["tenant_status"]),
                "deletion_status": str(lifecycle_state["deletion_status"]),
                "recovery_until": lifecycle_state.get("recovery_until"),
            },
        }
        evidence = {
            "status": "recomposed",
            "authority": "account_organization+account_lifecycle",
            "mode": "canonical_read",
            "organization_id": view["organization_id"],
            "person_relationship_count": len(relationships),
            "affected_people_matched": len(matched),
            "tenant_status": view["lifecycle"]["tenant_status"],
            "deletion_status": view["lifecycle"]["deletion_status"],
            "lifecycle_updated_at": lifecycle_state.get("lifecycle_updated_at"),
        }
        return view, evidence


class ProjectionRestatementOrchestrator:
    """Queue and inspect durable identity restatement jobs."""

    def __init__(self) -> None:
        # Convenience only for the legacy run_restatement(job_id) call. Durable
        # state and worker recovery always come from the jobs platform.
        self._tenant_by_job_id: dict[str, str] = {}

    async def queue_restatement(
        self, decision: IdentityDecisionRecord
    ) -> ProjectionRestatementJobRecord:
        from config.settings import settings

        if not settings.identity_continuity.projection_restatement_enabled:
            raise RuntimeError("projection restatement is disabled")
        if not decision.tenant_id:
            raise ValueError("tenant_id is required for projection restatement")
        projections = self._determine_projections(decision)
        if not decision.graph_version_after and decision.resolution_revision_after is None:
            raise ValueError(
                "restatement requires a persisted graph version or resolution revision"
            )
        version_key = (
            f"graph:{decision.graph_version_after}"
            if decision.graph_version_after
            else f"resolution-revision:{decision.resolution_revision_after}"
        )
        job = ProjectionRestatementJobRecord(
            id="pending",
            tenant_id=decision.tenant_id,
            trigger_decision_id=decision.id,
            graph_version_before=decision.graph_version_before or "",
            graph_version_after=decision.graph_version_after or "",
            affected_canonical_entity_ids=self._get_affected_entities(decision),
            projections=projections,
            status="queued",
            created_at=_now(),
            resolution_revision_before=decision.resolution_revision_before,
            resolution_revision_after=decision.resolution_revision_after,
        )
        if not job.affected_canonical_entity_ids:
            raise ValueError("at least one affected canonical entity is required")

        from workers.jobs.service import get_jobs_service

        identity_context = {
            "decision_type": decision.decision_type.value,
            "selected_canonical_entity_id": decision.selected_canonical_entity_id,
            "candidate_canonical_entity_ids": list(
                decision.candidate_canonical_entity_ids
            ),
        }
        if decision.decision_type in {
            DecisionType.MANUAL_SPLIT,
            DecisionType.AUTO_SPLIT,
        }:
            # Fragment-aware splits persist the evidence selectors and actual
            # moved IDs in the split-event ledger. Carry that immutable event
            # into the durable restatement job instead of reconstructing it
            # from a lossy list of affected entities.
            from identity.identity.repository import IdentityResolutionRepository

            split_event = await IdentityResolutionRepository().get_split_event_by_id(
                decision.tenant_id, decision.id
            )
            identity_context["split_event"] = split_event

        platform_job = await get_jobs_service().enqueue(
            decision.tenant_id,
            PROJECTION_RESTATEMENT_JOB_TYPE,
            {
                "restatement": _record_payload(job),
                "identity_context": identity_context,
            },
            idempotency_key=(
                f"identity-restatement:{decision.id}:{version_key}"
            ),
            correlation_id=decision.id,
            requested_by="identity_resolution",
            max_attempts=5,
        )
        job.id = str(platform_job["id"])
        self._tenant_by_job_id[job.id] = decision.tenant_id
        logger.info(
            "identity.projection_restatement.queued",
            extra={
                "tenant_id": job.tenant_id,
                "job_id": job.id,
                "trigger_decision_id": decision.id,
                "projection_count": len(projections),
                "affected_entity_count": len(job.affected_canonical_entity_ids),
            },
        )
        return job

    async def queue_restatement_from_event(self, event: Any) -> Optional[ProjectionRestatementJobRecord]:
        """Idempotent event-path fallback using persisted decision/version data.

        Event consumers may recover a decision whose inline enqueue failed, but
        they must not invent a decision ID, tenant, or graph/revision version.
        """
        from config.settings import settings

        if not settings.identity_continuity.projection_restatement_enabled:
            return None
        payload = dict(getattr(event, "payload", None) or {})
        tenant_id = str(getattr(event, "tenant_id", "") or "")
        payload_tenant = str(payload.get("tenant_id") or tenant_id)
        if not tenant_id or payload_tenant != tenant_id:
            logger.warning("identity.restatement.event_rejected reason=tenant_mismatch")
            return None
        decision_id = str(payload.get("decision_id") or "")
        if not decision_id:
            logger.warning("identity.restatement.event_rejected reason=missing_decision_id")
            return None
        graph_after = payload.get("graph_version_after") or payload.get("graph_version")
        revision_after = payload.get("resolution_revision_after")
        if not graph_after and revision_after is None:
            logger.warning(
                "identity.restatement.event_rejected reason=missing_persisted_version"
            )
            return None
        affected = payload.get("affected_canonical_entity_ids")
        if not affected:
            merged = [payload.get("primary_entity_id"), payload.get("secondary_entity_id")]
            split = [payload.get("original_entity_id"), payload.get("resulting_entity_id")]
            affected = [value for value in (merged if any(merged) else split) if value]
        affected = list(dict.fromkeys(str(value) for value in affected if value))
        if not affected:
            logger.warning("identity.restatement.event_rejected reason=missing_entities")
            return None

        from identity.identity.models import ConfidenceBand, DecisionType

        from shared.events.events import Topic

        topic = getattr(event, "topic", None)
        topic_value = getattr(topic, "value", topic)
        is_merge = bool(
            payload["is_merge"]
            if "is_merge" in payload
            else topic_value == Topic.IDENTITY_MERGED.value
        )
        decision = IdentityDecisionRecord(
            id=decision_id,
            tenant_id=tenant_id,
            decision_type=DecisionType.MANUAL_MERGE if is_merge else DecisionType.MANUAL_SPLIT,
            candidate_source_identity_ids=[],
            candidate_canonical_entity_ids=affected,
            selected_canonical_entity_id=str(payload.get("canonical_entity_id") or affected[0]),
            confidence=float(payload.get("confidence") or (1.0 if is_merge else 0.0)),
            confidence_band=(
                ConfidenceBand.VERY_HIGH if is_merge else ConfidenceBand.BLOCKED
            ),
            positive_evidence=[],
            negative_evidence=[],
            vetoes=[],
            policy_version="event_restatement",
            graph_version_before=(
                str(payload["graph_version_before"])
                if payload.get("graph_version_before") else None
            ),
            graph_version_after=str(graph_after) if graph_after else None,
            explanation="persisted identity event",
            decided_by="identity_event_consumer",
            decided_at=str(payload.get("decided_at") or _now()),
            resolution_revision_before=payload.get("resolution_revision_before"),
            resolution_revision_after=revision_after,
        )
        return await self.queue_restatement(decision)

    def _determine_projections(
        self, decision: IdentityDecisionRecord
    ) -> list[ProjectionType]:
        from config.settings import settings

        projections = [
            ProjectionType.PROFILE_360,
            ProjectionType.JOURNEY,
            ProjectionType.COMMUNICATIONS_360,
            ProjectionType.SIGNALS,
            ProjectionType.SYNDICATES,
            ProjectionType.AGENT_360,
            ProjectionType.EXECUTION_360,
            ProjectionType.ACCOUNT_360,
        ]
        if (
            settings.identity_continuity.campaign_restatement_enabled
            and decision.confidence_band.value in ("very_high", "high")
        ):
            projections.append(ProjectionType.CAMPAIGN_360)
        if (
            settings.identity_continuity.value_restatement_enabled
            and decision.decision_type in (DecisionType.AUTO_MERGE, DecisionType.MANUAL_MERGE)
        ):
            projections.append(ProjectionType.VALUE)
        return projections

    def _get_affected_entities(self, decision: IdentityDecisionRecord) -> list[str]:
        entities = []
        if decision.selected_canonical_entity_id:
            entities.append(decision.selected_canonical_entity_id)
        entities.extend(decision.candidate_canonical_entity_ids)
        return list(dict.fromkeys(entity for entity in entities if entity))

    async def get_job_status(
        self, tenant_id: str, job_id: str
    ) -> Optional[ProjectionRestatementJobRecord]:
        """Return a tenant-scoped durable job snapshot; foreign jobs are hidden."""
        from workers.jobs.service import get_jobs_service

        row = await get_jobs_service().get_job(tenant_id, job_id)
        if row is None or row.get("job_type") != PROJECTION_RESTATEMENT_JOB_TYPE:
            return None
        job = _record_from_payload(row.get("payload") or {})
        job.id = str(row["id"])
        job.status = {
            "accepted": "queued",
            "retrying": "queued",
            "running": "running",
            "succeeded": "completed",
            "partially_succeeded": "partially_completed",
            "failed": "failed",
            "cancelled": "failed",
        }.get(str(row.get("status")), str(row.get("status")))
        return job

    async def get_jobs_for_entity(
        self, tenant_id: str, entity_id: str
    ) -> list[ProjectionRestatementJobRecord]:
        """List durable restatement records scoped to the supplied tenant."""
        from workers.jobs.service import get_jobs_service

        service = get_jobs_service()
        results = []
        offset = 0
        while True:
            rows = await service.list_jobs(
                tenant_id,
                job_type=PROJECTION_RESTATEMENT_JOB_TYPE,
                limit=200,
                offset=offset,
            )
            for row in rows:
                payload = row.get("payload") or {}
                data = payload.get("restatement") or {}
                if entity_id in data.get("affected_canonical_entity_ids", []):
                    item = await self.get_job_status(tenant_id, str(row["id"]))
                    if item is not None:
                        results.append(item)
            if len(rows) < 200:
                break
            offset += len(rows)
        return results

    async def run_restatement(
        self, job_id: str, tenant_id: Optional[str] = None
    ) -> ProjectionRestatementJobRecord:
        """Compatibility entry point; execute only through the jobs worker."""
        tenant = tenant_id or self._tenant_by_job_id.get(job_id)
        if not tenant:
            raise ValueError("tenant_id is required to inspect a durable restatement job")
        status = await self.get_job_status(tenant, job_id)
        if status is None:
            raise ValueError("restatement job not found for tenant")
        return status


def register_projection_restatement_handler() -> None:
    """Register the internal worker handler at backend startup."""
    from workers.jobs.handlers import HANDLER_REGISTRY, JobOutcome, register_handler

    if PROJECTION_RESTATEMENT_JOB_TYPE in HANDLER_REGISTRY:
        return

    @register_handler(PROJECTION_RESTATEMENT_JOB_TYPE, tenant_invocable=False)
    async def _handle(payload: dict, ctx) -> JobOutcome:
        from repositories.jobs_repo import get_jobs_repository

        data = dict(payload.get("restatement") or {})
        identity_context = dict(payload.get("identity_context") or {})
        if data.get("tenant_id") != ctx.tenant_id:
            return JobOutcome(status="failed", result={}, error="tenant scope mismatch")
        job = _record_from_payload({"restatement": data})
        job.id = ctx.job_id
        job.status = "running"
        job.started_at = _now()
        projection_status = dict(data.get("projection_status") or {})
        projection_evidence = dict(data.get("projection_evidence") or {})
        data["status"] = job.status
        data["started_at"] = job.started_at

        async def checkpoint() -> bool:
            payload["restatement"] = {
                **data,
                "projection_status": projection_status,
                "projection_evidence": projection_evidence,
            }
            stored = await get_jobs_repository().update_payload(
                ctx.job_id, payload, worker_id=ctx.worker_id
            )
            return stored is not None

        errors: list[str] = []
        unsupported: list[str] = []
        for projection in job.projections:
            key = projection.value
            if projection_status.get(key) == "completed":
                continue
            try:
                if projection is ProjectionType.PROFILE_360:
                    from identity.profile.aggregator import Profile360Aggregator

                    aggregator = Profile360Aggregator()
                    # Profile 360 is composed from current tenant-scoped backing
                    # stores on read; invoking summary rebuilds that view, but does
                    # not claim a separately persisted snapshot was delivered.
                    for entity_id in job.affected_canonical_entity_ids:
                        await aggregator.summary(entity_id, ctx.tenant_id)
                    projection_status[key] = "completed"
                elif projection is ProjectionType.JOURNEY:
                    from journeys.measurement.identity_consumer import MeasurementIdentityConsumer

                    consumer = MeasurementIdentityConsumer(producer=None)
                    for entity_id in job.affected_canonical_entity_ids:
                        await consumer._rebuild_and_reattribute(
                            ctx.tenant_id,
                            entity_id,
                            reason="identity_restatement",
                            restatement_key=ctx.job_id,
                        )
                    projection_status[key] = "completed"
                elif projection is ProjectionType.COMMUNICATIONS_360:
                    from journeys.comms.repository import CommsFactsRepository

                    repository = CommsFactsRepository()
                    for entity_id in job.affected_canonical_entity_ids:
                        await repository.entity_summary(ctx.tenant_id, entity_id)
                    projection_status[key] = "completed"
                elif projection is ProjectionType.SIGNALS:
                    from intelligence.signals.recompute import recompute_signals_for_entity

                    for entity_id in job.affected_canonical_entity_ids:
                        await recompute_signals_for_entity(entity_id, ctx.tenant_id)
                    projection_status[key] = "completed"
                elif projection is ProjectionType.AGENT_360:
                    for entity_id in job.affected_canonical_entity_ids:
                        await _recompute_agent_360_for_entity(
                            ctx.tenant_id, entity_id
                        )
                    projection_status[key] = "completed"
                elif projection is ProjectionType.EXECUTION_360:
                    for entity_id in job.affected_canonical_entity_ids:
                        await _recompute_execution_360_for_entity(
                            ctx.tenant_id, entity_id
                        )
                    projection_status[key] = "completed"
                elif projection is ProjectionType.CAMPAIGN_360:
                    await _recompute_campaign_360(
                        ctx.tenant_id,
                        job.affected_canonical_entity_ids,
                        ctx.job_id,
                    )
                    projection_status[key] = "completed"
                elif projection is ProjectionType.VALUE:
                    for entity_id in job.affected_canonical_entity_ids:
                        await _recompute_value_for_entity(
                            ctx.tenant_id, entity_id, ctx.job_id
                        )
                    projection_status[key] = "completed"
                elif projection is ProjectionType.ACCOUNT_360:
                    _, evidence = await Account360ProjectionComposer().compose(
                        ctx.tenant_id, job.affected_canonical_entity_ids
                    )
                    projection_evidence[key] = evidence
                    projection_status[key] = "completed"
                elif projection is ProjectionType.SYNDICATES:
                    from identity.identity.models import DecisionType

                    decision_type = str(identity_context.get("decision_type") or "")
                    if decision_type in {
                        DecisionType.MANUAL_SPLIT.value,
                        DecisionType.AUTO_SPLIT.value,
                    }:
                        split_event = identity_context.get("split_event")
                        if not isinstance(split_event, dict):
                            projection_status[key] = "unsupported"
                            projection_evidence[key] = {
                                "status": "unsupported",
                                "reason_code": "syndicates_split_event_missing",
                                "detail": (
                                    "The durable split event was unavailable, so "
                                    "Syndicates memberships were left unchanged."
                                ),
                                "membership_unchanged": True,
                            }
                            unsupported.append(key)
                        else:
                            from replay.projections.syndicates_restatement import (
                                restate_syndicates_split,
                            )

                            evidence = await restate_syndicates_split(
                                tenant_id=ctx.tenant_id,
                                split_event=split_event,
                                decision_id=job.trigger_decision_id,
                            )
                            projection_evidence[key] = evidence
                            if evidence["status"] == "unsupported":
                                projection_status[key] = "unsupported"
                                unsupported.append(key)
                            else:
                                projection_status[key] = "completed"
                    elif decision_type in {
                        DecisionType.MANUAL_MERGE.value,
                        DecisionType.AUTO_MERGE.value,
                    }:
                        selected = str(
                            identity_context.get("selected_canonical_entity_id") or ""
                        )
                        candidates = [
                            str(value)
                            for value in identity_context.get(
                                "candidate_canonical_entity_ids", []
                            )
                            if value
                        ]
                        from replay.projections.syndicates_restatement import (
                            restate_syndicates_merge,
                        )

                        projection_evidence[key] = await restate_syndicates_merge(
                            tenant_id=ctx.tenant_id,
                            survivor_entity_id=selected,
                            consumed_entity_ids=[
                                entity_id for entity_id in candidates
                                if entity_id != selected
                            ],
                            decision_id=job.trigger_decision_id,
                        )
                        projection_status[key] = "completed"
                    else:
                        # Resolve/link/candidate decisions do not change an
                        # existing canonical entity's population membership.
                        projection_status[key] = "completed"
                        projection_evidence[key] = {
                            "status": "completed",
                            "reason_code": "identity_membership_unchanged",
                            "membership_unchanged": True,
                        }
                else:
                    projection_status[key] = "unsupported"
                    projection_evidence[key] = {
                        "status": "unsupported",
                        **_UNSUPPORTED_PROJECTION_REASONS.get(
                            key,
                            {
                                "reason_code": "projection_executor_missing",
                                "detail": "No canonical executor is registered for this projection.",
                            },
                        ),
                    }
                    unsupported.append(key)
            except Exception as exc:
                projection_status[key] = "retryable_failure"
                errors.append(f"{key}: {type(exc).__name__}")
            if not await checkpoint():
                return JobOutcome(status="failed", result={}, error="worker lease lost")
            await ctx.emit_event(
                "identity.projection_restatement.progress",
                {"projection": key, "status": projection_status[key]},
            )

        job.completed_at = _now() if not errors else None
        job.status = "retryable_failure" if errors else (
            "unsupported" if unsupported else "completed"
        )
        data["status"] = job.status
        data["completed_at"] = job.completed_at
        data["error"] = "; ".join(errors) if errors else (
            "Unsupported projections: " + "; ".join(
                f"{key} ({projection_evidence[key]['reason_code']}): "
                f"{projection_evidence[key]['detail']}"
                for key in unsupported
            ) if unsupported else None
        )
        data["projection_status"] = projection_status
        data["projection_evidence"] = projection_evidence
        if not await checkpoint():
            return JobOutcome(status="failed", result={}, error="worker lease lost")
        result = {
            "restatement_job_id": ctx.job_id,
            "projection_status": projection_status,
            "projection_evidence": projection_evidence,
            "unsupported_projections": unsupported,
        }
        if errors:
            return JobOutcome(status="failed", result=result, error="; ".join(errors))
        if unsupported:
            return JobOutcome(status="partially_succeeded", result=result)
        return JobOutcome(status="succeeded", result=result)
