"""The Agent360 communications slot composes both tenant-scoped providers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from actions.agent import agent360_provider as agent360_provider_module  # noqa: E402
from actions.agent.agent360_provider import Agent360Provider, Agent360ReadBatch  # noqa: E402
from journeys.communication360.contracts import CommunicationMessage  # noqa: E402
from journeys.communication360.provider import Communication360Provider  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import (  # noqa: E402
    build_experience360_frame,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402
from shared.projection_engine.executor import ProjectionExecutor  # noqa: E402
from shared.projection_engine.runtime import ProjectionRuntime  # noqa: E402


TENANT = "tenant-agent-communications-frame"
AGENT_ID = "agent-communications-frame-1"
GENERATED_AT = "2026-10-18T16:30:00Z"
AS_OF = "2026-10-18T16:25:00Z"
SOURCE_AGENT_ID = "provider-agent-communications-1"
CANONICAL_AGENT_ID = "canonical-agent-communications-1"


@pytest.mark.asyncio
async def test_agent360_communications_composes_evidenced_primary_and_supporting_providers():
    calls: list[tuple[str, str, str, str, tuple[str, ...]]] = []
    evidence_by_projection = {
        "agent360": EvidenceRef(
            id="agent-mailbox-observation-1",
            type="event",
            source="obs_agent_messages",
            observedAt=AS_OF,
        ),
        "communication360": EvidenceRef(
            id="communication-message-fact-1",
            type="event",
            source="communication_messages",
            observedAt=AS_OF,
        ),
    }

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            assert request.surfaceId == "agent360"
            assert request.tenantId == TENANT
            assert request.subject == ProjectionSubject(kind="agent", id=AGENT_ID)
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt=GENERATED_AT,
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "communications": Experience360PolicyDisposition(state="allowed")
                },
            )

    class TenantScopedProjectionRuntime:
        async def execute_projection(self, request, **_kwargs):
            assert request.tenantId == TENANT
            assert request.subject == ProjectionSubject(kind="agent", id=AGENT_ID)
            section_ids = tuple(request.includeSections or ())
            calls.append(
                (
                    request.projectionId,
                    request.tenantId,
                    request.subject.kind,
                    request.subject.id,
                    section_ids,
                )
            )
            evidence = evidence_by_projection[request.projectionId]
            return ProjectionResult(
                projectionId=request.projectionId,
                tenantId=request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"evidenceRefs": [evidence]},
                    )
                    for section_id in section_ids
                ],
                claims=[],
                dependencyState=[],
                generatedAt=GENERATED_AT,
                asOf=AS_OF,
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT_ID),
        requestedSlotIds=["communications"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=TenantScopedProjectionRuntime(),
        generated_at=GENERATED_AT,
    )

    assert sorted(calls, key=lambda call: call[0]) == [
        ("agent360", TENANT, "agent", AGENT_ID, ("interactions",)),
        (
            "communication360",
            TENANT,
            "agent",
            AGENT_ID,
            ("evidence", "interactions", "timeline"),
        ),
    ]
    assert len(frame.slots) == 1
    slot = frame.slots[0]
    assert slot.id == "communications"
    assert slot.state == "available"
    assert {reference.id for reference in slot.evidenceRefs} == {
        "agent-mailbox-observation-1",
        "communication-message-fact-1",
    }

    section_provenance = [item for item in slot.provenance if item.sourceKind == "section"]
    provenance_by_projection = {
        projection_id: [
            item for item in section_provenance if item.projectionId == projection_id
        ]
        for projection_id in ("agent360", "communication360")
    }
    assert all(provenance_by_projection.values())
    assert all(
        item.tenantId == TENANT
        for items in provenance_by_projection.values()
        for item in items
    )
    assert {
        projection_id: {
            reference.id
            for item in items
            for reference in item.evidenceRefs
        }
        for projection_id, items in provenance_by_projection.items()
    } == {
        "agent360": {"agent-mailbox-observation-1"},
        "communication360": {"communication-message-fact-1"},
    }
    assert {
        projection_id: set(items[0].canonicalAuthorityRefs)
        for projection_id, items in provenance_by_projection.items()
    } == {
        "agent360": {"observations"},
        "communication360": {"communication_facts"},
    }


@pytest.mark.asyncio
async def test_agent360_communications_composes_real_providers_over_scoped_sources(
    monkeypatch: pytest.MonkeyPatch,
):
    binding_evidence = EvidenceRef(
        id="agent-identity-binding-1",
        type="entity",
        source="agent_deployment_identity_bindings",
        observedAt=AS_OF,
    )
    agent_message_evidence = EvidenceRef(
        id="agent-message-observation-1",
        type="event",
        source="obs_agent_messages",
        observedAt=AS_OF,
    )
    agent_inbox_evidence = EvidenceRef(
        id="agent-inbox-observation-1",
        type="event",
        source="obs_agent_inboxes",
        observedAt=AS_OF,
    )
    communication_message_evidence = EvidenceRef(
        id="communication-message-fact-1",
        type="event",
        source="silver_comms_facts",
        observedAt=AS_OF,
    )
    communication_interaction_fact_id = "communication-participant-binding-1"
    identity_row = {
        "tenant_id": TENANT,
        "agent_id": SOURCE_AGENT_ID,
        "canonical_agent_entity_id": CANONICAL_AGENT_ID,
        "identity_evidence_id": binding_evidence.id,
        "identity_evidence_source": binding_evidence.source,
        "identity_binding_authority": "tenant_admin_explicit",
        "identity_bound_at": AS_OF,
    }

    class ScopedAgentIdentityRepository:
        async def actor_identity(self, tenant_id, source_agent_ref):
            assert (tenant_id, source_agent_ref) == (TENANT, SOURCE_AGENT_ID)
            return Agent360ReadBatch(rows=[identity_row])

    monkeypatch.setattr(
        agent360_provider_module,
        "RepositoryAgent360Source",
        lambda: ScopedAgentIdentityRepository(),
    )

    class ScopedAgent360Source:
        def __init__(self):
            self.calls: list[tuple[str, str, str | None]] = []

        async def agent_configs(self, tenant_id, agent_id):
            self.calls.append(("agent_configs", tenant_id, agent_id))
            assert tenant_id == TENANT
            return []

        async def actor_identity(self, tenant_id, agent_id):
            self.calls.append(("actor_identity", tenant_id, agent_id))
            assert (tenant_id, agent_id) == (TENANT, SOURCE_AGENT_ID)
            return Agent360ReadBatch(rows=[identity_row])

        async def principal_identities(self, tenant_id, principal_user_ids, limit):
            self.calls.append(("principal_identities", tenant_id, None))
            assert tenant_id == TENANT
            return Agent360ReadBatch(rows=[])

        async def executions(self, tenant_id, agent_id, limit):
            self.calls.append(("executions", tenant_id, agent_id))
            assert tenant_id == TENANT
            return []

        async def incoming_delegations(self, tenant_id, agent_id, limit):
            self.calls.append(("incoming_delegations", tenant_id, agent_id))
            assert (tenant_id, agent_id) == (TENANT, CANONICAL_AGENT_ID)
            return []

        async def outgoing_delegations(self, tenant_id, agent_id, limit):
            self.calls.append(("outgoing_delegations", tenant_id, agent_id))
            assert (tenant_id, agent_id) == (TENANT, CANONICAL_AGENT_ID)
            return []

        async def active_incoming_delegations(self, tenant_id, agent_id):
            self.calls.append(("active_incoming_delegations", tenant_id, agent_id))
            assert (tenant_id, agent_id) == (TENANT, CANONICAL_AGENT_ID)
            return []

        async def activities(self, tenant_id, agent_id, limit):
            self.calls.append(("activities", tenant_id, agent_id))
            assert tenant_id == TENANT
            return []

        async def tools(self, tenant_id, agent_id, limit):
            self.calls.append(("tools", tenant_id, agent_id))
            assert tenant_id == TENANT
            return []

        async def capability_access_profile(self, tenant_id, agent_id):
            self.calls.append(("capability_access_profile", tenant_id, agent_id))
            assert (tenant_id, agent_id) == (TENANT, SOURCE_AGENT_ID)
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "profile": {
                            "subject": {"kind": "agent", "id": agent_id},
                            "profile_known": True,
                            "missing_inputs": [],
                            "identity": {"installation_ids": ["capability-installation-1"]},
                            "observation": {"last_seen_at": AS_OF},
                            "counts": {
                                "capabilities_reachable": 0,
                                "capabilities_invoked": 0,
                                "capabilities_authorized": 0,
                                "capabilities_unauthorized": 0,
                                "authorizations_active": 0,
                            },
                            "reach": {"capabilities": []},
                            "authorization": {
                                "known": True,
                                "authorizations_active": 0,
                                "activeRecordIds": [],
                                "activeRecordIdsTruncated": False,
                            },
                        },
                    }
                ]
            )

        async def risk_signals(self, tenant_id, agent_id, limit):
            self.calls.append(("risk_signals", tenant_id, agent_id))
            assert tenant_id == TENANT
            return []

        async def communications(self, tenant_id, agent_id, limit):
            self.calls.append(("communications", tenant_id, agent_id))
            assert (tenant_id, agent_id) == (TENANT, SOURCE_AGENT_ID)
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": TENANT,
                        "agent_id": SOURCE_AGENT_ID,
                        "subject_binding_basis": "exact_tenant_inbox_agent_id",
                        "inbox_obs_id": "agent-inbox-observation-1",
                        "inbox_evidence_ref": agent_inbox_evidence.model_dump(mode="json"),
                        "message_obs_id": agent_message_evidence.id,
                        "thread_obs_id": "agent-thread-observation-1",
                        "direction": "outbound",
                        "has_attachments": False,
                        "observed_at": AS_OF,
                        "received_at": AS_OF,
                        "subject": "private subject omitted",
                        "body": "private body omitted",
                    }
                ]
            )

    class ScopedCommunicationSource:
        def __init__(self):
            self.message_reads: list[tuple[str, str | None]] = []
            self.fact_reads: list[str] = []

        async def messages(
            self,
            tenant_id,
            *,
            campaign_id=None,
            participant_entity_id=None,
            since=None,
            limit=None,
        ):
            self.message_reads.append((tenant_id, participant_entity_id))
            assert tenant_id == TENANT
            assert participant_entity_id == CANONICAL_AGENT_ID
            return [
                CommunicationMessage(
                    message_id="communication-message-1",
                    tenant_id=TENANT,
                    fact_id=communication_message_evidence.id,
                    direction="outbound",
                    sender_entity_id=CANONICAL_AGENT_ID,
                    sender_identity_binding_id=binding_evidence.id,
                    recipient_entity_id="person-recipient-1",
                    occurred_at=AS_OF,
                    received_at=AS_OF,
                    evidence_refs=[communication_message_evidence],
                )
            ]

        async def facts(self, tenant_id, *, kind=None, since=None, limit=None):
            self.fact_reads.append(tenant_id)
            assert tenant_id == TENANT
            return [
                {
                    "fact_id": communication_interaction_fact_id,
                    "tenant_id": TENANT,
                    "kind": "participant_binding",
                    "source_event_id": "communication-participant-event-1",
                    "actor_id": CANONICAL_AGENT_ID,
                    "agent_id": CANONICAL_AGENT_ID,
                    "occurred_at": AS_OF,
                    "received_at": AS_OF,
                    "payload": {
                        "entity_id": CANONICAL_AGENT_ID,
                        "role": "sender",
                        "communication_scope": "message",
                    },
                }
            ]

        async def available(self, tenant_id):
            assert tenant_id == TENANT
            return True

    agent_source = ScopedAgent360Source()
    communication_source = ScopedCommunicationSource()
    agent_provider = Agent360Provider(source=agent_source)
    communication_provider = Communication360Provider(sources=communication_source)

    class RecordingProviderRegistry(ProviderRegistry):
        def __init__(self):
            super().__init__()
            self.project_calls: list[tuple[str, str]] = []

        async def project(self, projection_id, request):
            self.project_calls.append((projection_id, request.tenantId))
            return await super().project(projection_id, request)

    provider_registry = RecordingProviderRegistry()
    provider_registry.register(agent_provider, source="test:real-agent360-provider")
    provider_registry.register(
        communication_provider, source="test:real-communication360-provider"
    )
    executor = ProjectionExecutor(registry=provider_registry)
    projection_runtime = ProjectionRuntime(executor=executor)

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            assert (request.surfaceId, request.tenantId) == ("agent360", TENANT)
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt=GENERATED_AT,
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "communications": Experience360PolicyDisposition(state="allowed")
                },
            )

    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=SOURCE_AGENT_ID),
        requestedSlotIds=["communications"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=projection_runtime,
        generated_at=GENERATED_AT,
    )

    assert sorted(provider_registry.project_calls) == [
        ("agent360", TENANT),
        ("communication360", TENANT),
    ]
    assert (TENANT, SOURCE_AGENT_ID) in [
        (tenant_id, agent_id)
        for operation, tenant_id, agent_id in agent_source.calls
        if operation == "actor_identity"
    ]
    assert ("communications", TENANT, SOURCE_AGENT_ID) in [
        call for call in agent_source.calls if call[0] == "communications"
    ]
    assert (TENANT, CANONICAL_AGENT_ID) in communication_source.message_reads
    assert communication_source.fact_reads

    slot = next(item for item in frame.slots if item.id == "communications")
    assert slot.state == "available", {
        "reasons": slot.reasonCodes,
        "bound_sections": sorted(
            (item.projectionId, item.sectionId, item.sourceState)
            for item in slot.provenance
            if item.sourceKind == "section"
        ),
    }
    assert {reference.id for reference in slot.evidenceRefs} >= {
        binding_evidence.id,
        agent_message_evidence.id,
        communication_message_evidence.id,
        communication_interaction_fact_id,
    }
    section_provenance = [item for item in slot.provenance if item.sourceKind == "section"]
    assert {item.projectionId for item in section_provenance} == {
        "agent360",
        "communication360",
    }
    provenance_evidence_by_projection = {
        projection_id: {
            reference.id
            for item in section_provenance
            if item.projectionId == projection_id
            for reference in item.evidenceRefs
        }
        for projection_id in ("agent360", "communication360")
    }
    assert agent_message_evidence.id in provenance_evidence_by_projection["agent360"]
    assert communication_message_evidence.id in provenance_evidence_by_projection[
        "communication360"
    ]
