"""Exact canonical action associations remain observed lifecycle requests."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from actions.agent.action_associations import (  # noqa: E402
    JourneyActionReference, RiskActionReference, action_association_read_authorized, read_associated_executions,
    validate_action_association,
)
from journeys.measurement.episodes.related_authorities import (  # noqa: E402
    AuthorityFactRead, JourneyActionIntentRecord,
)
from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from repositories.repos import AgentExecutionRepository  # noqa: E402


NOW = datetime.now(timezone.utc)
TENANT = "tenant-action-association-tests"


def test_action_association_requires_exact_slot_policy():
    from shared.intelligence_projections.contracts import (
        ProjectionContext, ProjectionReadAuthorization, ProjectionRequest, ProjectionSubject,
    )

    subject = ProjectionSubject(kind="journey", id="journey-1")
    request = ProjectionRequest(projectionId="episode360", tenantId=TENANT, subject=subject)
    context = ProjectionContext(projectionId="episode360", tenantId=TENANT, registryState="in_flight", dependencyState=[], warnings=[])
    assert not action_association_read_authorized(
        request, context, surface="journey360", slot="recommended_actions", consumer="episode360"
    )
    auth = ProjectionReadAuthorization(
        tenantId=TENANT, sourceSurfaceId="journey360", sourceSubject=subject,
        sourceSlotId="recommended_actions", consumerProjectionId="episode360",
        targetProjectionId="agent360", capabilityKey="agent360.read", policyState="allowed",
        policyIds=["policy-1"], policyEvaluatedAt=NOW.isoformat(),
    )
    context.experience360ReadAuthorizations = [auth]
    assert action_association_read_authorized(
        request, context, surface="journey360", slot="recommended_actions", consumer="episode360"
    )
    context.experience360ReadAuthorizations = [auth.model_copy(update={"tenantId": "other"})]
    assert not action_association_read_authorized(
        request, context, surface="journey360", slot="recommended_actions", consumer="episode360"
    )


def _journey_intent():
    return JourneyActionIntentRecord(
        record_id="intent-record-1", tenant_id=TENANT, journey_id="journey-1",
        journey_version_id="version-1", action_intent_id="intent-1", recommendation_id="rec-1",
        action_key="send_notice", action_type="notice", label="Notice", actor_ref="operator",
        occurred_at=NOW - timedelta(minutes=2), recorded_at=NOW - timedelta(minutes=1),
        evidence_refs=[EvidenceRef(id="version-1", type="event", source="journey_versions"),
                       EvidenceRef(id="step-1", type="event", source="journey_steps")],
    )


class Journeys:
    async def get_current(self, tenant_id, journey_id):
        return {"tenant_id": tenant_id, "journey_id": journey_id,
                "journey_version_id": "version-1", "is_current": True}


class Intents:
    def __init__(self, intent):
        self.intent = intent

    async def list_for_subject(self, tenant_id, kind, subject_id, record_type, *, limit):
        assert (tenant_id, kind, subject_id, record_type, limit) == (
            TENANT, "journey", "journey-1", "journey_action_intent", 201)
        return AuthorityFactRead(records=(self.intent.model_dump(mode="json"),), available=True, complete=True)


@pytest.mark.asyncio
async def test_journey_association_validates_authority_and_reads_server_lifecycle():
    intent = _journey_intent()
    ref = JourneyActionReference(journey_id="journey-1", journey_version_id="version-1", record_id=intent.record_id)
    association = await validate_action_association(
        tenant_id=TENANT, action="send_notice", resource="journey-1", journey=ref,
        journey_authority=Intents(intent), journey_repository=Journeys(), now=NOW,
    )
    repo = AgentExecutionRepository()
    execution_id = f"association-{uuid4()}"
    await repo.record(
        execution_id=execution_id, tenant_id=TENANT, agent_id="agent-1", delegation_id=None,
        triggered_by_event_id=None, status="running", action_association=association,
        input_snapshot={"action": "send_notice", "resource": "journey-1"}, create_only=True,
    )
    rows, complete = await read_associated_executions(
        tenant_id=TENANT, kind="journey_action_intent", record_id=intent.record_id,
        subject_id="journey-1", version_id="version-1", action="send_notice",
        recorded_at=intent.recorded_at, as_of=datetime.now(timezone.utc), repository=repo,
    )
    assert complete and [row["executionId"] for row in rows] == [execution_id]
    assert rows[0]["dispatchState"] == "not_established"
    assert rows[0]["externalEffectState"] == "unknown"
    rows, complete = await read_associated_executions(
        tenant_id="other", kind="journey_action_intent", record_id=intent.record_id,
        subject_id="journey-1", version_id="version-1", action="send_notice",
        recorded_at=intent.recorded_at, as_of=datetime.now(timezone.utc), repository=repo,
    )
    assert complete and rows == []
    with pytest.raises(ValueError):
        await validate_action_association(
            tenant_id=TENANT, action="other", resource="journey-1", journey=ref,
            journey_authority=Intents(intent), journey_repository=Journeys(), now=NOW,
        )


@pytest.mark.asyncio
async def test_risk_association_requires_exact_approved_decision_and_resource():
    decision = SimpleNamespace(
        tenant_id=TENANT, record_id="risk-1", record_kind="decision", decision_state="approved",
        subject_kind="entity", subject_id="entity-1", intervention_id="intervention-1",
        intervention_type="disable_agent_action", effective_at=NOW - timedelta(minutes=2),
        recorded_at=NOW - timedelta(minutes=1),
    )

    class Risks:
        async def get(self, tenant, record_id):
            return decision if (tenant, record_id) == (TENANT, "risk-1") else None

    ref = RiskActionReference(record_id="risk-1", subject_kind="entity", subject_id="entity-1")
    association = await validate_action_association(
        tenant_id=TENANT, action="disable_agent_action", resource="entity-1", risk=ref,
        risk_repository=Risks(), now=NOW,
    )
    assert association["intervention_id"] == "intervention-1"
    repo = AgentExecutionRepository()
    execution_id = f"risk-association-{uuid4()}"
    await repo.record(
        execution_id=execution_id, tenant_id=TENANT, agent_id="agent-1", delegation_id=None,
        triggered_by_event_id=None, status="running", action_association=association,
        input_snapshot={"action": "disable_agent_action", "resource": "entity-1"}, create_only=True,
    )
    rows, complete = await read_associated_executions(
        tenant_id=TENANT, kind="risk_intervention", record_id="risk-1", subject_id="entity-1",
        subject_kind="entity", intervention_id="intervention-1", action="disable_agent_action",
        recorded_at=decision.recorded_at, as_of=datetime.now(timezone.utc), repository=repo,
    )
    assert complete and [row["executionId"] for row in rows] == [execution_id]
    assert rows[0]["dispatchState"] == "not_established"
    rows, complete = await read_associated_executions(
        tenant_id=TENANT, kind="risk_intervention", record_id="risk-1", subject_id="entity-1",
        subject_kind="entity", intervention_id="other", action="disable_agent_action",
        recorded_at=decision.recorded_at, as_of=datetime.now(timezone.utc), repository=repo,
    )
    assert not complete and rows == []
    decision.decision_state = "rejected"
    with pytest.raises(ValueError):
        await validate_action_association(
            tenant_id=TENANT, action="disable_agent_action", resource="entity-1", risk=ref,
            risk_repository=Risks(), now=NOW,
        )
