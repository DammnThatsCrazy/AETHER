"""Focused contract tests for the read-only Agent360 projection provider."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from actions.agent.agent360_provider import (  # noqa: E402
    Agent360Provider,
    Agent360ReadBatch,
    OUTPUT_SECTIONS,
    RepositoryAgent360Source,
)
from actions.agent_access_intelligence.models import capability_id_for  # noqa: E402
from actions.agentic_observability.provenance import (  # noqa: E402
    AgenticProvenanceQuery,
    build_agentic_provenance_record,
)
from ingestion.ingestion.validation import SCHEMA_VERSION  # noqa: E402
from identity.identity.hashing import hash_value  # noqa: E402
from identity.identity.models import IdentitySignalType  # noqa: E402
from repositories.repos import EntityRepository  # noqa: E402
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    ProjectionReadAuthorization,
    ProjectionSection,
)
from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.intelligence_projections.composition import compose_experience360_frame  # noqa: E402
from shared.intelligence_projections.frame_runtime import build_experience360_frame  # noqa: E402
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402
from shared.projection_engine.executor import ProjectionExecutor  # noqa: E402
from shared.projection_engine.runtime import ProjectionRuntime  # noqa: E402


TENANT = "tenant-a"
AGENT = "agent-a"


def _context() -> ProjectionContext:
    return ProjectionContext(
        projectionId="agent360",
        tenantId=TENANT,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


def _request(
    *,
    kind: str = "agent",
    subject_id: str = AGENT,
    time_range=None,
    temporal_mode="window",
    include_claims: bool = True,
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=subject_id),
        page={"limit": 10},
        timeRange=time_range,
        temporalMode=temporal_mode,
        includeClaims=include_claims,
    )


class FakeSource:
    def __init__(
        self,
        *,
        empty: bool = False,
        fail: str | None = None,
        capability_grants: list[dict] | None = None,
    ) -> None:
        self.empty = empty
        self.fail = fail
        self.capability_grants = capability_grants
        self.calls = 0
        self.delegation_subjects: list[str] = []
        self.party_identity_subjects: list[set[str]] = []
        self.owner_relationship_subjects: list[tuple[str, str]] = []
        self.capability_subjects: list[str] = []
        self.risk_summary_calls: list[tuple[str, str, str, int]] = []
        self.risk_signal_calls = 0

    async def _rows(self, name: str, rows: list[dict]) -> list[dict]:
        self.calls += 1
        if self.fail == name:
            raise RuntimeError("secret database diagnostic must not leak")
        return [] if self.empty else rows

    async def agent_configs(self, tenant_id, agent_id):
        return await self._rows(
            "config",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "model": "model-x",
                    "status": "registered",
                    "created_at": "2026-10-01T00:00:00Z",
                    "owner_entity_id": "owner-1",
                    "tools": ["search"],
                }
            ],
        )

    async def actor_identity(self, tenant_id, agent_id):
        rows = await self._rows(
            "actor_identity",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "canonical_agent_entity_id": "canonical-agent-a",
                    "identity_evidence_id": "binding-agent-a",
                    "identity_evidence_source": "agent_deployment_identity_bindings",
                    "identity_binding_authority": "tenant_admin_explicit",
                    "identity_bound_at": "2026-10-01T00:00:00Z",
                }
            ],
        )
        return Agent360ReadBatch(rows=rows)

    async def principal_identities(self, tenant_id, principal_user_ids, limit):
        rows = await self._rows("principal_identities", [])
        return Agent360ReadBatch(rows=rows)

    async def executions(self, tenant_id, agent_id, limit):
        return await self._rows(
            "executions",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "execution_id": "exec-1",
                    "status": "completed",
                    "started_at": "2026-10-02T00:00:00Z",
                    "ended_at": "2026-10-02T00:01:00Z",
                    "delegation_id": "delegation-in-1",
                    "triggered_by_event_id": "event-1",
                    "initiating_principal_user_id": "authenticated-user-1",
                    "policy_log": {
                        "tools_used": ["search"],
                        "resources": ["doc-1"],
                        "delegation_check": {
                            "allowed": True,
                            "delegation_id": "delegation-in-1",
                            "reason": "scope_matched",
                            "evaluated_at": "2026-10-02T00:00:30Z",
                        },
                    },
                    "input_snapshot": {"action": "read", "resource": "customer:123"},
                    "reasoning": "private reasoning must not be projected",
                    "output": {"secret": "private output"},
                }
            ],
        )

    async def incoming_delegations(self, tenant_id, canonical_agent_entity_id, limit):
        self.delegation_subjects.append(canonical_agent_entity_id)
        return await self._rows(
            "incoming",
            [
                {
                    "tenant_id": tenant_id,
                    "delegation_id": "delegation-in-1",
                    "grantor_entity_id": "owner-1",
                    "grantee_entity_id": canonical_agent_entity_id,
                    "authorization_kind": "capability",
                    "capability_id": "tool-1",
                    "capability_observed": False,
                    "scope": {"actions": ["invoke"], "resources": ["capability:tool-1"]},
                    "starts_at": "2026-10-01T00:00:00Z",
                    "ends_at": None,
                    "revoked_at": None,
                }
            ],
        )

    async def outgoing_delegations(self, tenant_id, canonical_agent_entity_id, limit):
        self.delegation_subjects.append(canonical_agent_entity_id)
        return await self._rows("outgoing", [])

    async def active_incoming_delegations(self, tenant_id, canonical_agent_entity_id):
        self.delegation_subjects.append(canonical_agent_entity_id)
        return await self._rows(
            "active",
            [
                {
                    "tenant_id": tenant_id,
                    "delegation_id": "delegation-in-1",
                    "grantor_entity_id": "owner-1",
                    "grantee_entity_id": canonical_agent_entity_id,
                    "authorization_kind": "capability",
                    "capability_id": "tool-1",
                    "capability_observed": False,
                    "scope": {"actions": ["invoke"], "resources": ["capability:tool-1"]},
                    "starts_at": "2026-10-01T00:00:00Z",
                    "ends_at": None,
                    "revoked_at": None,
                }
            ],
        )

    async def delegation_party_identities(self, tenant_id, party_entity_ids):
        self.party_identity_subjects.append(set(party_entity_ids))
        rows = await self._rows(
            "delegation_party_identities",
            [
                {
                    "tenant_id": tenant_id,
                    "party_entity_id": "owner-1",
                    "party_entity_type": "human",
                    "identity_evidence_id": "owner-1",
                    "identity_evidence_source": "entities",
                    "identity_observed_at": "2026-09-01T00:00:00Z",
                },
                {
                    "tenant_id": tenant_id,
                    "party_entity_id": "canonical-agent-a",
                    "party_entity_type": "agent",
                    "identity_evidence_id": "canonical-agent-a",
                    "identity_evidence_source": "entities",
                    "identity_observed_at": "2026-09-02T00:00:00Z",
                },
            ],
        )
        return Agent360ReadBatch(
            rows=[row for row in rows if row["party_entity_id"] in party_entity_ids]
        )

    async def owner_relationships(
        self, tenant_id, owner_entity_id, canonical_agent_entity_id
    ):
        self.owner_relationship_subjects.append((owner_entity_id, canonical_agent_entity_id))
        rows = await self._rows("owner_relationships", [])
        return Agent360ReadBatch(rows=rows)

    async def activities(self, tenant_id, agent_id, limit):
        return await self._rows(
            "activities",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "observation_id": "obs-1",
                    "event_name": "agent_tool_invoked",
                    "observed_at": "2026-10-03T00:00:00Z",
                    "action": {"name": "invoke_tool", "status": "observed"},
                    "source": {"provider": "mcp"},
                    "raw_payload": {"secret": "must not be projected"},
                }
            ],
        )

    async def tools(self, tenant_id, agent_id, limit):
        return await self._rows(
            "tools",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "invocation_id": "tool-invoke-1",
                    "tool_name": "search",
                    "status": "observed",
                    "duration_ms": 12,
                    "observed_at": "2026-10-04T00:00:00Z",
                }
            ],
        )

    async def capability_access_profile(
        self, tenant_id, agent_id, canonical_agent_entity_id
    ):
        self.capability_subjects.append(canonical_agent_entity_id)
        grant_records = self.capability_grants
        if grant_records is None:
            grant_records = [
                {
                    "tenant_id": tenant_id,
                    "agent_id": canonical_agent_entity_id,
                    "grantee_entity_id": canonical_agent_entity_id,
                    "authorization_id": "capability-grant-1",
                    "authorization_kind": "capability",
                    "capability_id": "capability-search",
                    "scope": {
                        "actions": ["invoke"],
                        "resources": ["capability:capability-search"],
                    },
                    "state": "active",
                    "starts_at": "2026-10-01T00:00:00Z",
                    "created_at": "2026-10-01T00:00:00Z",
                }
            ]
        rows = await self._rows(
            "capability_access_profile",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "canonical_agent_entity_id": canonical_agent_entity_id,
                    "canonical_grant_records": grant_records,
                    "canonical_grant_read_complete": True,
                    "profile": {
                        "subject": {"kind": "agent", "id": agent_id},
                        "profile_known": True,
                        "missing_inputs": [],
                        "basis": "observed_only",
                        "identity": {"installation_ids": ["installation-agent-a"]},
                        "observation": {"last_seen_at": "2026-10-04T00:00:00Z"},
                        "counts": {
                            "capabilities_reachable": 1,
                            "capabilities_invoked": 1,
                            "capabilities_authorized": 1,
                            "capabilities_unauthorized": 0,
                            "authorizations_active": 1,
                        },
                        "reach": {
                            "capabilities": [
                                {
                                    "capability_id": "capability-search",
                                    "server_key": "mcp-main",
                                    "provider": "mcp",
                                    "tool_name": "search",
                                    "basis": "invoked",
                                    "authorized": True,
                                }
                            ]
                        },
                        "authorization": {
                            "known": True,
                            "authorizations_active": 1,
                            "activeRecordIds": ["capability-grant-1"],
                            "activeRecordIdsTruncated": False,
                        },
                    },
                }
            ],
        )
        return Agent360ReadBatch(rows=rows)

    async def risk_signals(self, tenant_id, agent_id, limit):
        self.risk_signal_calls += 1
        return await self._rows(
            "risks",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "signal_id": "risk-1",
                    "risk_level": "medium",
                    "reason_codes": ["observed_policy_flag"],
                    "policy_flags": ["review"],
                    "detected_at": "2026-10-05T00:00:00Z",
                }
            ],
        )

    async def canonical_risk_summary(
        self, tenant_id, agent_id, canonical_agent_entity_id, limit
    ):
        self.risk_summary_calls.append(
            (tenant_id, agent_id, canonical_agent_entity_id, limit)
        )
        if self.empty:
            return Agent360ReadBatch(rows=[])
        return Agent360ReadBatch(
            rows=[
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "canonical_agent_entity_id": canonical_agent_entity_id,
                    "subject_kind": "agent",
                    "subject_id": canonical_agent_entity_id,
                    "state": "partial",
                    "reason": "canonical_risk360_evidence_available_agent_freshness_unassessed",
                    "summary": {
                        "tenantId": tenant_id,
                        "subject": {"kind": "agent", "id": canonical_agent_entity_id},
                        "riskLevel": "medium",
                    },
                    "dimension_states": [{"dimension": "agentic", "state": "observed"}],
                    "assessment_coverage": {"state": "available"},
                    "assessment_section_state": "available",
                    "risk_state_section_state": "available",
                    "freshness": {"state": "not_assessed", "slaSeconds": None},
                    "evidence_refs": [
                        {
                            "id": "canonical-risk-evidence-1",
                            "type": "event",
                            "source": "risk_assessments",
                            "observedAt": "2026-10-05T00:00:00Z",
                        }
                    ],
                    "consent_evidence_ref": {
                        "id": "consent-receipt-1",
                        "type": "event",
                        "source": "governance.consent.authority",
                        "observedAt": "2026-10-06T00:00:00Z",
                        "uri": "store://consent_receipts/consent-receipt-1",
                    },
                    "claims": [
                        ClaimEnvelope(
                            id="risk-claim-1",
                            kind="canonical_agent_risk_assessment",
                            subject=ProjectionSubject(
                                kind="agent", id=canonical_agent_entity_id
                            ),
                            evidenceRefs=[
                                EvidenceRef(
                                    id="canonical-risk-evidence-1",
                                    type="event",
                                    source="risk_assessments",
                                )
                            ],
                            claims=["Canonical risk assessment evidence is available."],
                            claimState=EpistemicStatus.OBSERVED,
                            domainSlotIds=["risk_summary"],
                        )
                    ],
                    "contagion_state": "unknown",
                    "contagion_reason": "Risk360 does not establish causal social or financial contagion",
                    "canonical_authorities": ["risk_assessments", "risk_signals"],
                }
            ]
        )

    async def agentic_provenance(self, tenant_id, agent_id, queries, limit):
        rows = await self._rows("agentic_provenance", [])
        return Agent360ReadBatch(rows=rows)

    async def communications(self, tenant_id, agent_id, limit):
        rows = await self._rows(
            "communications",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "subject_binding_basis": "exact_tenant_inbox_agent_id",
                    "inbox_obs_id": "inbox-1",
                    "inbox_evidence_ref": {
                        "id": "inbox-1",
                        "type": "event",
                        "source": "obs_agent_inboxes",
                        "observedAt": "2026-10-01T00:00:00Z",
                    },
                    "message_obs_id": "message-1",
                    "thread_obs_id": "thread-1",
                    "direction": "outbound",
                    "has_attachments": False,
                    "observed_at": "2026-10-06T00:00:00Z",
                    "received_at": "2026-10-06T00:00:01Z",
                    "subject": "private message subject must not appear",
                    "from_address": "private-from@example.test",
                    "to_addresses": ["private-to@example.test"],
                    "body": "private message body must not appear",
                }
            ],
        )
        return Agent360ReadBatch(rows=rows)


def _sections(result):
    return {section.id: section for section in result.sections}


@pytest.mark.asyncio
async def test_agent360_risk_summary_requires_exact_outer_slot_authority_before_read():
    source = FakeSource()
    authorization_calls = []

    async def authorize(**kwargs):
        authorization_calls.append(kwargs)
        return True

    result = await Agent360Provider(
        source, risk_slot_authorizer=authorize
    ).project(_request(), _context())
    risk_dimension = next(
        dimension
        for dimension in _sections(result)["state"].content["dimensions"]
        if dimension["id"] == "risk_and_contagion"
    )
    risk_summary = risk_dimension["content"]["riskAssessment"]

    assert authorization_calls == [
        {
            "tenant_id": TENANT,
            "request_subject": ProjectionSubject(kind="agent", id=AGENT),
            "canonical_agent_entity_id": "canonical-agent-a",
            "slot_id": "risk_summary",
            "capability": "risk360.read",
        }
    ]
    assert source.risk_summary_calls == [(TENANT, AGENT, "canonical-agent-a", 10)]
    assert source.risk_signal_calls == 0
    assert risk_summary["state"] == "partial"
    assert risk_summary["subject"] == {"kind": "agent", "id": "canonical-agent-a"}
    assert risk_summary["canonicalAgentIdentityJoin"]["state"] == "resolved"
    assert risk_summary["canonicalAgentIdentityJoin"]["canonicalAgentEntityId"] == (
        "canonical-agent-a"
    )
    assert {
        (ref["source"], ref["id"])
        for ref in risk_summary["canonicalAgentIdentityJoin"]["evidenceRefs"]
    } == {("agent_deployment_identity_bindings", "binding-agent-a")}
    assert {
        (ref["source"], ref["id"]) for ref in risk_summary["evidenceRefs"]
    } >= {
        ("risk_assessments", "canonical-risk-evidence-1"),
        ("governance.consent.authority", "consent-receipt-1"),
        ("agent_deployment_identity_bindings", "binding-agent-a"),
    }
    claim = next(
        claim for claim in result.claims if claim.kind == "canonical_agent_risk_assessment"
    )
    assert claim.subject.id == "canonical-agent-a"
    assert claim.domainSlotIds == ["risk_summary"]


@pytest.mark.asyncio
async def test_agent360_risk_summary_fails_closed_without_outer_slot_authority():
    source = FakeSource()
    result = await Agent360Provider(source).project(_request(), _context())
    risk_dimension = next(
        dimension
        for dimension in _sections(result)["state"].content["dimensions"]
        if dimension["id"] == "risk_and_contagion"
    )

    assert source.risk_summary_calls == []
    assert source.risk_signal_calls == 0
    assert risk_dimension["content"]["riskAssessment"]["state"] == "suppressed"
    assert not any(claim.domainSlotIds == ["risk_summary"] for claim in result.claims)


@pytest.mark.asyncio
async def test_agent360_nested_risk_read_uses_exact_frame_policy_context():
    source = FakeSource()
    registry = ProviderRegistry()
    registry.register(Agent360Provider(source), source="test")
    runtime = ProjectionRuntime(executor=ProjectionExecutor(registry=registry))
    evaluated_at = "2026-10-23T14:00:00Z"

    class AllowExactRiskSlot:
        async def evaluate(self, request):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt=evaluated_at,
                frameDisposition=Experience360PolicyDisposition(
                    state="allowed", evaluatedAt=evaluated_at
                ),
                slotDispositions={
                    "owner_delegator": Experience360PolicyDisposition(
                        state="allowed",
                        policyIds=["access_control.evaluate"],
                        evaluatedAt=evaluated_at,
                    ),
                    "risk_summary": Experience360PolicyDisposition(
                        state="allowed",
                        policyIds=["access_control.evaluate"],
                        evaluatedAt=evaluated_at,
                    ),
                },
            )

    await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="agent360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="agent", id="canonical-agent-a"),
            requestedSlotIds=["owner_delegator", "risk_summary"],
        ),
        policy_evaluator=AllowExactRiskSlot(),
        projection_runtime=runtime,
    )

    assert source.risk_summary_calls == [
        (TENANT, "canonical-agent-a", "canonical-agent-a", 100)
    ]
    assert source.risk_signal_calls == 0


@pytest.mark.parametrize(
    ("requested_slots", "risk_slot_state"),
    [
        (["owner_delegator", "risk_summary"], "denied"),
        (["owner_delegator"], None),
    ],
)
@pytest.mark.asyncio
async def test_agent360_nested_risk_read_is_skipped_when_outer_slot_is_not_allowed(
    requested_slots, risk_slot_state
):
    source = FakeSource()
    registry = ProviderRegistry()
    registry.register(Agent360Provider(source), source="test")
    runtime = ProjectionRuntime(executor=ProjectionExecutor(registry=registry))
    evaluated_at = "2026-10-23T14:00:00Z"

    class DenyOrOmitRiskSlot:
        async def evaluate(self, request):
            dispositions = {
                "owner_delegator": Experience360PolicyDisposition(
                    state="allowed",
                    policyIds=["access_control.evaluate"],
                    evaluatedAt=evaluated_at,
                )
            }
            if risk_slot_state is not None:
                dispositions["risk_summary"] = Experience360PolicyDisposition(
                    state=risk_slot_state,
                    policyIds=["access_control.evaluate"],
                    evaluatedAt=evaluated_at,
                )
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt=evaluated_at,
                frameDisposition=Experience360PolicyDisposition(
                    state="allowed", evaluatedAt=evaluated_at
                ),
                slotDispositions=dispositions,
            )

    await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="agent360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="agent", id="canonical-agent-a"),
            requestedSlotIds=requested_slots,
        ),
        policy_evaluator=DenyOrOmitRiskSlot(),
        projection_runtime=runtime,
    )

    assert source.risk_summary_calls == []
    assert source.risk_signal_calls == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenantId": "other-tenant"},
        {"sourceSurfaceId": "profile360"},
        {"sourceSubject": ProjectionSubject(kind="agent", id="other-agent")},
        {"sourceSlotId": "owner_delegator"},
        {"consumerProjectionId": "execution360"},
        {"targetProjectionId": "profile360"},
        {"capabilityKey": "agent360.read"},
        {"policyState": "denied"},
    ],
)
@pytest.mark.asyncio
async def test_agent360_nested_risk_read_rejects_mismatched_frame_authorization(overrides):
    source = FakeSource()
    authorization = ProjectionReadAuthorization(
        tenantId=TENANT,
        sourceSurfaceId="agent360",
        sourceSubject=ProjectionSubject(kind="agent", id=AGENT),
        sourceSlotId="risk_summary",
        consumerProjectionId="agent360",
        targetProjectionId="risk360",
        capabilityKey="risk360.read",
        policyState="allowed",
        policyIds=["access_control.evaluate"],
        policyEvaluatedAt="2026-10-23T14:00:00Z",
    )
    authorization = authorization.model_copy(update=overrides)
    context = _context().model_copy(
        update={"experience360ReadAuthorizations": [authorization]}
    )

    result = await Agent360Provider(source).project(_request(), context)
    risk_dimension = next(
        dimension
        for dimension in _sections(result)["state"].content["dimensions"]
        if dimension["id"] == "risk_and_contagion"
    )

    assert source.risk_summary_calls == []
    assert risk_dimension["content"]["riskAssessment"]["state"] == "suppressed"


@pytest.mark.asyncio
async def test_agent360_risk_summary_denial_prevents_nested_risk360_source_read():
    source = FakeSource()
    authorization_calls = []

    async def deny(**kwargs):
        authorization_calls.append(kwargs)
        return False

    result = await Agent360Provider(source, risk_slot_authorizer=deny).project(
        _request(), _context()
    )
    risk_dimension = next(
        dimension
        for dimension in _sections(result)["state"].content["dimensions"]
        if dimension["id"] == "risk_and_contagion"
    )

    assert len(authorization_calls) == 1
    assert authorization_calls[0]["slot_id"] == "risk_summary"
    assert authorization_calls[0]["capability"] == "risk360.read"
    assert source.risk_summary_calls == []
    assert source.risk_signal_calls == 0
    assert risk_dimension["content"]["riskAssessment"]["state"] == "suppressed"


@pytest.mark.asyncio
async def test_agent360_risk_summary_skips_nested_read_when_identity_is_unresolved():
    source = FakeSource(empty=True)
    authorization_calls = []

    async def authorize(**kwargs):
        authorization_calls.append(kwargs)
        return True

    result = await Agent360Provider(
        source, risk_slot_authorizer=authorize
    ).project(_request(), _context())
    risk_dimension = next(
        dimension
        for dimension in _sections(result)["state"].content["dimensions"]
        if dimension["id"] == "risk_and_contagion"
    )

    assert authorization_calls == []
    assert source.risk_summary_calls == []
    assert source.risk_signal_calls == 0
    assert risk_dimension["content"]["riskAssessment"]["state"] == "unknown"
    assert "canonicalAgentIdentityJoin" not in risk_dimension["content"]["riskAssessment"]


@pytest.mark.asyncio
async def test_agent360_risk_summary_rejects_cross_tenant_rows_and_claims():
    class CrossTenantRiskSource(FakeSource):
        async def canonical_risk_summary(
            self, tenant_id, agent_id, canonical_agent_entity_id, limit
        ):
            batch = await super().canonical_risk_summary(
                tenant_id, agent_id, canonical_agent_entity_id, limit
            )
            return Agent360ReadBatch(
                rows=[{**batch.rows[0], "tenant_id": "other-tenant"}]
            )

    async def authorize(**kwargs):
        return True

    source = CrossTenantRiskSource()
    result = await Agent360Provider(
        source, risk_slot_authorizer=authorize
    ).project(_request(), _context())
    risk_dimension = next(
        dimension
        for dimension in _sections(result)["state"].content["dimensions"]
        if dimension["id"] == "risk_and_contagion"
    )

    assert risk_dimension["content"]["riskAssessment"]["state"] == "degraded"
    assert "risk_summary_scope_mismatch" in _sections(result)["summary"].warnings
    assert not any(claim.domainSlotIds == ["risk_summary"] for claim in result.claims)


@pytest.mark.asyncio
async def test_repository_risk360_read_requires_current_consent_and_exact_canonical_subject():
    class Consent:
        allowed = True
        receipt_id = "server-consent-9"

    class RiskProvider:
        def __init__(self):
            self.calls = []

        async def project(self, request, context):
            self.calls.append((request, context))
            evidence_ref = EvidenceRef(
                id="risk-assessment-9",
                type="event",
                source="risk_assessments",
                observedAt="2026-10-05T00:00:00Z",
            )
            claim = ClaimEnvelope(
                id="risk-claim-9",
                kind="canonical_agent_risk_assessment",
                subject=ProjectionSubject(kind="agent", id="canonical-agent-a"),
                evidenceRefs=[evidence_ref],
                claims=["Canonical Risk360 assessment evidence is available."],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["risk_summary"],
            )
            sections = [
                ProjectionSection(
                    id="summary",
                    state="available",
                    content={
                        "tenantId": TENANT,
                        "subject": {"kind": "agent", "id": "canonical-agent-a"},
                        "riskLevel": "medium",
                    },
                ),
                ProjectionSection(
                    id="state",
                    state="available",
                    content={
                        "tenantId": TENANT,
                        "subject": {"kind": "agent", "id": "canonical-agent-a"},
                        "dimensionStates": [{"dimension": "agentic", "state": "observed"}],
                    },
                ),
                ProjectionSection(
                    id="evidence",
                    state="available",
                    content={"tenantId": TENANT, "evidence": [evidence_ref.model_dump(mode="json")]},
                ),
                ProjectionSection(
                    id="findings",
                    state="available",
                    content={
                        "tenantId": TENANT,
                        "subject": {"kind": "agent", "id": "canonical-agent-a"},
                        "requiredSlotCoverage": {
                            "risk_summary": {"state": "available"}
                        },
                    },
                ),
            ]
            return SimpleNamespace(
                projectionId="risk360",
                tenantId=TENANT,
                sections=sections,
                claims=[claim],
            )

    consent_calls = []

    async def consent_reader(**kwargs):
        consent_calls.append(kwargs)
        return Consent()

    risk_provider = RiskProvider()
    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)
    source._risk_consent_reader = consent_reader
    source._risk360_provider = risk_provider

    batch = await source.canonical_risk_summary(
        TENANT, AGENT, "canonical-agent-a", limit=999
    )

    assert consent_calls == [
        {
            "tenant_id": TENANT,
            "subject_id": "canonical-agent-a",
            "anonymous_id": None,
            "purpose": "analytics",
        }
    ]
    assert len(risk_provider.calls) == 1
    request, context = risk_provider.calls[0]
    assert request.projectionId == "risk360"
    assert request.tenantId == TENANT
    assert request.subject == ProjectionSubject(kind="agent", id="canonical-agent-a")
    assert request.page.limit == 200
    assert context.tenantId == TENANT
    assert batch.rows[0]["state"] == "partial"
    assert batch.rows[0]["consent_evidence_ref"]["id"] == "server-consent-9"
    assert batch.rows[0]["claims"][0].subject.id == "canonical-agent-a"


@pytest.mark.asyncio
async def test_repository_risk360_read_does_not_run_when_consent_is_denied():
    class ConsentDenied:
        allowed = False
        receipt_id = None

    class RiskProvider:
        async def project(self, request, context):
            raise AssertionError("Risk360 must not run without affirmative consent")

    consent_calls = []

    async def consent_reader(**kwargs):
        consent_calls.append(kwargs)
        return ConsentDenied()

    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)
    source._risk_consent_reader = consent_reader
    source._risk360_provider = RiskProvider()

    batch = await source.canonical_risk_summary(
        TENANT, AGENT, "canonical-agent-a", limit=10
    )

    assert consent_calls == [
        {
            "tenant_id": TENANT,
            "subject_id": "canonical-agent-a",
            "anonymous_id": None,
            "purpose": "analytics",
        }
    ]
    assert batch.rows[0]["state"] == "suppressed"
    assert "consent_evidence_ref" not in batch.rows[0]
    assert "claims" not in batch.rows[0]


@pytest.mark.asyncio
async def test_repository_agent_communications_proves_exact_inbox_message_join():
    class Inboxes:
        async def find_many(self, *, filters, limit):
            assert filters == {"tenant_id": TENANT, "agent_id": AGENT}
            assert limit == 11
            return [
                {
                    "tenant_id": TENANT,
                    "agent_id": AGENT,
                    "inbox_obs_id": "inbox-1",
                    "observed_at": "2026-10-01T00:00:00Z",
                    "email_address": "private-inbox@example.test",
                },
                {
                    "tenant_id": "other-tenant",
                    "agent_id": AGENT,
                    "inbox_obs_id": "foreign-inbox",
                },
            ]

    class Messages:
        async def find_many(self, *, filters, limit):
            assert filters == {"tenant_id": TENANT, "inbox_obs_id": "inbox-1"}
            assert limit == 11
            return [
                {
                    "tenant_id": TENANT,
                    "inbox_obs_id": "inbox-1",
                    "message_obs_id": "message-1",
                    "observed_at": "2026-10-02T00:00:00Z",
                    "subject": "private message subject",
                },
                {
                    "tenant_id": "other-tenant",
                    "inbox_obs_id": "inbox-1",
                    "message_obs_id": "foreign-message",
                },
            ]

    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)
    source._inboxes = Inboxes()
    source._messages = Messages()

    batch = await source.communications(TENANT, AGENT, 10)

    assert batch.scope_mismatch is True
    assert batch.truncated is False
    assert len(batch.rows) == 1
    row = batch.rows[0]
    assert row["message_obs_id"] == "message-1"
    assert row["subject_binding_basis"] == "exact_tenant_inbox_agent_id"
    assert row["inbox_evidence_ref"]["source"] == "obs_agent_inboxes"
    assert row["inbox_evidence_ref"]["id"] == "inbox-1"
    assert "private-inbox@example.test" not in str(row)


@pytest.mark.asyncio
async def test_repository_agent_identity_uses_explicit_tenant_binding_and_agent_entity():
    class DeploymentSource:
        async def list_page(self, tenant_id, *, limit, cursor=None):
            assert tenant_id == TENANT
            assert limit == 200
            return (
                [
                    {
                        "tenant_id": TENANT,
                        "id": "deployment-1",
                        "agent_id": AGENT,
                        "agent_source_namespace": "provider-x",
                    }
                ],
                None,
                False,
            )

    class IdentityBindingSource:
        async def find_for_source(self, tenant_id, source_namespace, source_agent_ref):
            assert (tenant_id, source_namespace, source_agent_ref) == (TENANT, "provider-x", AGENT)
            return [
                {
                    "id": "binding-1",
                    "tenant_id": TENANT,
                    "source_namespace": "provider-x",
                    "source_agent_ref": AGENT,
                    "canonical_agent_entity_id": "canonical-agent-a",
                    "binding_authority": "tenant_admin_explicit",
                    "status": "active",
                    "bound_at": "2026-10-01T00:00:00Z",
                }
            ]

    class EntitySource:
        async def find_by_id(self, entity_id):
            if entity_id == AGENT:
                return None
            assert entity_id == "canonical-agent-a"
            return {
                "tenant_id": TENANT,
                "entity_type": "agent",
                "entity_id": entity_id,
            }

    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)
    source._deployments = DeploymentSource()
    source._identity_bindings = IdentityBindingSource()
    source._entities = EntitySource()

    result = await source.actor_identity(TENANT, AGENT)

    assert result.scope_mismatch is False
    assert result.truncated is False
    assert result.rows[0]["canonical_agent_entity_id"] == "canonical-agent-a"
    assert result.rows[0]["identity_evidence_id"] == "binding-1"
    assert result.rows[0]["identity_evidence_source"] == "agent_deployment_identity_bindings"


@pytest.mark.asyncio
async def test_repository_active_delegation_read_marks_repository_cap_as_incomplete():
    class DelegationSource:
        async def active_for(self, canonical_agent_entity_id, tenant_id):
            assert canonical_agent_entity_id == "canonical-agent-a"
            assert tenant_id == TENANT
            return [
                {
                    "tenant_id": TENANT,
                    "delegation_id": f"delegation-{index}",
                    "grantee_entity_id": canonical_agent_entity_id,
                }
                for index in range(200)
            ]

    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)
    source._delegations = DelegationSource()

    result = await source.active_incoming_delegations(TENANT, "canonical-agent-a")

    assert isinstance(result, Agent360ReadBatch)
    assert len(result.rows) == 200
    assert result.truncated is True


@pytest.mark.asyncio
async def test_entity_repository_party_lookup_is_exact_and_tenant_scoped(monkeypatch):
    repository = EntityRepository()
    entity_id = f"party-{uuid4().hex}"
    tenant_record_id = f"tenant-row-{uuid4().hex}"
    foreign_record_id = f"foreign-row-{uuid4().hex}"
    repository._store[tenant_record_id] = {
        "id": tenant_record_id,
        "tenant_id": TENANT,
        "entity_id": entity_id,
        "entity_type": "agent",
    }
    repository._store[foreign_record_id] = {
        "id": foreign_record_id,
        "tenant_id": "other-tenant",
        "entity_id": entity_id,
        "entity_type": "human",
    }

    async def local_store_only():
        return None

    monkeypatch.setattr(repository, "_ensure_pool", local_store_only)
    try:
        rows, truncated = await repository.find_many_for_tenant_entity_ids(
            TENANT, {entity_id}
        )
    finally:
        repository._store.pop(tenant_record_id, None)
        repository._store.pop(foreign_record_id, None)

    assert truncated is False
    assert rows == [
        {
            "id": tenant_record_id,
            "tenant_id": TENANT,
            "entity_id": entity_id,
            "entity_type": "agent",
        }
    ]


@pytest.mark.asyncio
async def test_repository_agent360_delegation_parties_revalidates_tenant_scope():
    class EntitySource:
        async def find_many_for_tenant_entity_ids(self, tenant_id, entity_ids):
            assert tenant_id == TENANT
            assert entity_ids == {"owner-1", "canonical-agent-a"}
            return [
                {
                    "tenant_id": tenant_id,
                    "entity_id": "owner-1",
                    "entity_type": "human",
                },
                {
                    "tenant_id": "other-tenant",
                    "entity_id": "canonical-agent-a",
                    "entity_type": "agent",
                },
            ], False

    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)
    source._entities = EntitySource()

    result = await source.delegation_party_identities(
        TENANT, {"owner-1", "canonical-agent-a"}
    )

    assert result.scope_mismatch is True
    assert result.rows == [
        {
            "tenant_id": TENANT,
            "party_entity_id": "owner-1",
            "party_entity_type": "human",
            "identity_evidence_id": "owner-1",
            "identity_evidence_source": "entities",
            "identity_observed_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_repository_agent_owner_relationship_reads_exact_tenant_graph_edges(
    monkeypatch: pytest.MonkeyPatch,
):
    from shared.graph.graph import Edge, EdgeType

    class Graph:
        def __init__(self):
            self.calls = []

        async def get_edges_for_tenant(self, tenant_id, *, limit, edge_types):
            self.calls.append((tenant_id, limit, edge_types))
            return [
                Edge(
                    EdgeType.OWNS,
                    "owner-1",
                    "canonical-agent-a",
                    {
                        "tenant_id": tenant_id,
                        "idempotency_key": "owner-edge-1",
                        "recorded_at": "2026-10-02T00:00:00Z",
                    },
                ),
                Edge(
                    EdgeType.OWNS_AGENT,
                    "owner-1",
                    "another-agent",
                    {"tenant_id": tenant_id, "idempotency_key": "other-agent-edge"},
                ),
                Edge(
                    EdgeType.OWNS,
                    "owner-1",
                    "canonical-agent-a",
                    {
                        "tenant_id": "foreign-tenant",
                        "idempotency_key": "foreign-owner-edge",
                    },
                ),
            ], False

    graph = Graph()
    monkeypatch.setattr("dependencies.providers.get_graph", lambda: graph)
    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)

    result = await source.owner_relationships(
        TENANT, "owner-1", "canonical-agent-a"
    )

    assert graph.calls == [(TENANT, 2000, [EdgeType.OWNS, EdgeType.OWNS_AGENT])]
    assert result.scope_mismatch is True
    assert result.truncated is False
    assert result.rows == [
        {
            "tenant_id": TENANT,
            "owner_entity_id": "owner-1",
            "canonical_agent_entity_id": "canonical-agent-a",
            "relationship_type": EdgeType.OWNS,
            "valid_from": None,
            "valid_to": None,
            "evidence_ref": {
                "id": "owner-edge-1",
                "type": "relationship",
                "source": "graph",
                "observedAt": "2026-10-02T00:00:00Z",
                "confidence": None,
                "uri": "graph://edges/owner-edge-1",
            },
        }
    ]


@pytest.mark.asyncio
async def test_agent360_owner_relationship_is_distinct_from_identity_and_authority():
    class ExactOwnerRelationshipSource(FakeSource):
        async def owner_relationships(
            self, tenant_id, owner_entity_id, canonical_agent_entity_id
        ):
            await super().owner_relationships(
                tenant_id, owner_entity_id, canonical_agent_entity_id
            )
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": tenant_id,
                        "owner_entity_id": owner_entity_id,
                        "canonical_agent_entity_id": canonical_agent_entity_id,
                        "relationship_type": "OWNS",
                        "valid_from": None,
                        "valid_to": None,
                        "evidence_ref": {
                            "id": "owner-edge-1",
                            "type": "relationship",
                            "source": "graph",
                            "observedAt": "2026-10-02T00:00:00Z",
                        },
                    }
                ]
            )

    source = ExactOwnerRelationshipSource()
    result = await Agent360Provider(source).project(_request(), _context())
    actor = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "actor_attribution"
    )["content"]
    relationship = actor["configuredOwnerRelationship"]

    assert source.owner_relationship_subjects == [("owner-1", "canonical-agent-a")]
    assert relationship["state"] == "observed"
    assert relationship["relationshipState"] == "stored_edge_observed"
    assert relationship["relationships"][0]["relationshipType"] == "OWNS"
    assert relationship["relationships"][0]["evidenceRef"]["id"] == "owner-edge-1"
    assert relationship["effectiveOwnership"] == "unknown"
    assert relationship["effectiveAuthorization"] == "unknown"
    assert relationship["freshness"] == {
        "state": "not_assessed",
        "slaSeconds": None,
        "reason": "owner_relationship_freshness_sla_not_configured",
    }
    assert actor["configuredOwnerIdentity"]["relationshipState"] == "configured_reference_only"
    assert actor["executionPrincipal"] == {"kind": "human", "id": "authenticated-user-1"}

    claim = next(
        claim for claim in result.claims if claim.kind == "observed_agent_owner_relationship"
    )
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert claim.domainSlotIds == ["owner_delegator", "actor_attribution"]
    assert {ref.source for ref in claim.evidenceRefs} == {
        "graph",
        "agent_configs",
        "entities",
        "agent_deployment_identity_bindings",
    }
    assert "does not establish legal or effective ownership" in claim.claims[0]


@pytest.mark.asyncio
async def test_agent360_owner_relationship_slot_policy_denial_skips_projection_read():
    class DenyOwnerSlotPolicy:
        async def evaluate(self, request):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-23T10:00:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "owner_delegator": Experience360PolicyDisposition(state="denied")
                },
            )

    class ProjectionRuntime:
        calls = []

        async def execute_projection(self, request, **_kwargs):
            self.calls.append(request.projectionId)
            raise AssertionError("denied owner slot must not trigger a provider read")

    runtime = ProjectionRuntime()
    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="agent360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="agent", id=AGENT),
            requestedSlotIds=["owner_delegator"],
        ),
        policy_evaluator=DenyOwnerSlotPolicy(),
        projection_runtime=runtime,
    )

    owner_slot = next(slot for slot in frame.slots if slot.id == "owner_delegator")
    assert runtime.calls == []
    assert owner_slot.state == "suppressed"
    assert owner_slot.content is None
    assert owner_slot.claims == []
    assert owner_slot.evidenceRefs == []


@pytest.mark.asyncio
async def test_agent360_active_delegation_cap_degrades_authority_and_hides_count():
    class CappedActiveDelegationsSource(FakeSource):
        async def active_incoming_delegations(self, tenant_id, canonical_agent_entity_id):
            batch = await super().active_incoming_delegations(tenant_id, canonical_agent_entity_id)
            return Agent360ReadBatch(rows=batch, truncated=True)

    result = await Agent360Provider(CappedActiveDelegationsSource()).project(_request(), _context())
    sections = _sections(result)
    authority = next(
        item
        for item in sections["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )

    assert authority["state"] == "degraded"
    assert authority["content"]["activeIncomingCount"] is None
    assert sections["summary"].content["sourceStates"]["active_delegations"] == "truncated"
    assert "active_delegations_read_truncated" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_does_not_attach_stale_active_status_to_changed_delegation_record():
    class StaleActiveDelegationsSource(FakeSource):
        async def active_incoming_delegations(self, tenant_id, canonical_agent_entity_id):
            rows = await super().active_incoming_delegations(tenant_id, canonical_agent_entity_id)
            rows[0]["scope"] = {
                "actions": ["delete"],
                "resources": ["customer:123"],
            }
            rows[0]["revoked_at"] = "2026-10-03T00:00:00Z"
            return rows

    result = await Agent360Provider(StaleActiveDelegationsSource()).project(_request(), _context())
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )
    conflict = authority["content"]["delegationReadConflicts"][0]
    disputed_claim = next(
        claim for claim in result.claims if claim.kind == "agent_delegation_active_state_conflict"
    )

    assert authority["state"] == "degraded"
    assert authority["content"]["effectiveAuthorizationDecision"] == "unknown"
    assert authority["content"]["activeIncomingCount"] is None
    assert authority["content"]["delegationRecords"][0]["recordState"] == "conflicted"
    assert conflict["delegationId"] == "delegation-in-1"
    assert conflict["state"] == "conflicted"
    assert conflict["differingFields"] == ["revoked_at", "scope"]
    assert conflict["evidenceRefs"][0]["source"] == "delegations"
    assert conflict["evidenceRefs"][0]["id"] == "delegation-in-1"
    assert disputed_claim.claimState == EpistemicStatus.DISPUTED
    assert disputed_claim.domainSlotIds == ["delegation_chain", "authority_check"]
    assert {ref.source for ref in disputed_claim.evidenceRefs} == {"delegations"}
    assert "agent_delegation_active_record_conflict" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_joins_adjacent_delegation_records_without_claiming_transitive_authority():
    class AdjacentDelegationsSource(FakeSource):
        async def outgoing_delegations(self, tenant_id, canonical_agent_entity_id, limit):
            self.delegation_subjects.append(canonical_agent_entity_id)
            return [
                {
                    "tenant_id": tenant_id,
                    "delegation_id": "delegation-out-1",
                    "grantor_entity_id": canonical_agent_entity_id,
                    "grantee_entity_id": "downstream-agent",
                    "authorization_kind": "capability",
                    "capability_id": "tool-2",
                    "scope": {"actions": ["invoke"], "resources": ["capability:tool-2"]},
                    "starts_at": "2026-10-02T00:00:00Z",
                    "ends_at": None,
                    "revoked_at": None,
                }
            ]

        async def delegation_party_identities(self, tenant_id, party_entity_ids):
            batch = await super().delegation_party_identities(tenant_id, party_entity_ids)
            rows = list(batch.rows)
            if "downstream-agent" in party_entity_ids:
                rows.append(
                    {
                        "tenant_id": tenant_id,
                        "party_entity_id": "downstream-agent",
                        "party_entity_type": "agent",
                        "identity_evidence_id": "downstream-agent",
                        "identity_evidence_source": "entities",
                        "identity_observed_at": "2026-09-03T00:00:00Z",
                    }
                )
            return Agent360ReadBatch(rows=rows, truncated=batch.truncated)

    result = await Agent360Provider(AdjacentDelegationsSource()).project(_request(), _context())
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )["content"]
    chain = authority["delegationChain"]

    assert chain["state"] == "partial"
    assert chain["intermediateCanonicalAgentEntityId"] == "canonical-agent-a"
    assert chain["observedAdjacentPathCount"] == 1
    assert chain["boundedReadComplete"] is True
    assert chain["transitiveAuthority"] == "unknown"
    assert chain["effectiveAuthorizationDecision"] == "unknown"
    path = chain["observedAdjacentPaths"][0]
    assert path["delegationRecordIds"] == ["delegation-in-1", "delegation-out-1"]
    assert path["partyEntityIds"] == ["owner-1", "canonical-agent-a", "downstream-agent"]
    assert [party["state"] for party in path["partyIdentities"]] == [
        "resolved",
        "resolved",
        "resolved",
    ]
    assert {
        (ref["source"], ref["id"]) for ref in path["evidenceRefs"] if ref["source"] == "delegations"
    } == {
        ("delegations", "delegation-in-1"),
        ("delegations", "delegation-out-1"),
    }
    assert "no transitive scope" in path["interpretation"]


@pytest.mark.asyncio
async def test_agent360_does_not_join_foreign_tenant_delegation_as_adjacent_path():
    class ForeignOutgoingDelegationSource(FakeSource):
        async def outgoing_delegations(self, tenant_id, canonical_agent_entity_id, limit):
            self.delegation_subjects.append(canonical_agent_entity_id)
            return [
                {
                    "tenant_id": "other-tenant",
                    "delegation_id": "foreign-delegation-out-1",
                    "grantor_entity_id": canonical_agent_entity_id,
                    "grantee_entity_id": "downstream-agent",
                    "scope": {"actions": ["invoke"], "resources": ["capability:tool-2"]},
                }
            ]

    result = await Agent360Provider(ForeignOutgoingDelegationSource()).project(
        _request(), _context()
    )
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )["content"]
    chain = authority["delegationChain"]

    assert chain["state"] == "unknown"
    assert chain["observedAdjacentPaths"] == []
    assert chain["observedAdjacentPathCount"] is None
    assert chain["boundedReadComplete"] is False
    assert chain["effectiveAuthorizationDecision"] == "unknown"
    assert authority["state"] == "degraded"


@pytest.mark.asyncio
async def test_agent360_projects_scoped_evidence_without_inventing_authority_or_outcomes():
    source = FakeSource()
    result = await Agent360Provider(source).project(_request(), _context())
    sections = _sections(result)

    assert tuple(section.id for section in result.sections) == OUTPUT_SECTIONS
    assert result.projectionId == "agent360"
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    assert result.tenantId == TENANT
    assert sections["summary"].content["profileKnown"] is True
    assert sections["state"].content["dimensions"][1]["state"] == "matched"
    actor = sections["state"].content["dimensions"][1]["content"]
    assert actor["assertedSourceActor"] == AGENT
    assert actor["configuredOwnerEntityId"] == "owner-1"
    assert actor["configuredOwnerIdentity"] == {
        "state": "resolved",
        "canonicalParty": {"kind": "human", "id": "owner-1"},
        "relationshipState": "configured_reference_only",
        "effectiveOwnership": "unknown",
        "effectiveAuthorization": "unknown",
        "temporalSemantics": (
            "current_agent_configuration_and_tenant_entity_state; "
            "not_reconstructed_for_requested_event_time"
        ),
        "freshness": {
            "state": "not_assessed",
            "slaSeconds": None,
            "reason": "owner_entity_freshness_sla_not_configured",
        },
        "evidenceRefs": [
            {
                "id": AGENT,
                "type": "entity",
                "source": "agent_configs",
                "observedAt": "2026-10-01T00:00:00Z",
                "confidence": None,
                "uri": None,
            },
            {
                "id": "owner-1",
                "type": "entity",
                "source": "entities",
                "observedAt": "2026-09-01T00:00:00Z",
                "confidence": None,
                "uri": None,
            },
        ],
        "reason": None,
    }
    assert actor["resolvedCanonicalActor"] == "canonical-agent-a"
    assert actor["executionPrincipal"] == {
        "kind": "human",
        "id": "authenticated-user-1",
    }
    assert actor["executionPrincipalState"] == "available"
    assert actor["executionPrincipalEvidenceRefs"] == [
        {
            "id": "exec-1",
            "type": "event",
            "source": "agent_executions",
            "observedAt": "2026-10-02T00:00:00Z",
            "confidence": None,
            "uri": None,
        }
    ]
    assert actor["executionPrincipalCanonicalIdentity"] == {
        "state": "unresolved",
        "canonicalHumanEntityId": None,
        "candidateEntityIds": [],
        "evidenceRefs": [],
        "reason": "no active tenant USER_ID alias resolved every observed principal",
    }
    assert actor["authorityDecision"] == "unknown"

    authority = sections["state"].content["dimensions"][2]["content"]
    assert authority["state"] == "available"
    assert authority["configuredOwnerIdentity"] == actor["configuredOwnerIdentity"]
    assert authority["effectiveAuthorizationDecision"] == "unknown"
    access_profile = authority["capabilityAccessProfile"]
    assert access_profile["state"] == "available"
    assert access_profile["authorization"]["activeGrantCount"] == 1
    assert access_profile["authorization"]["activeGrantRecordIds"] == [
        "capability-grant-1"
    ]
    assert access_profile["authorization"]["canonicalAgentEntityId"] == "canonical-agent-a"
    assert source.capability_subjects == ["canonical-agent-a"]
    assert access_profile["capabilities"][0]["invokeGrantCoversCapability"] is True
    assert access_profile["capabilities"][0]["activeGrantRecordIds"] == [
        "capability-grant-1"
    ]
    assert any(
        ref["id"] == "capability-grant-1" and ref["source"] == "delegations"
        for ref in access_profile["evidenceRefs"]
    )
    assert authority["actionScopedDecisionState"] == "available"
    assert authority["actionScopedDecisions"] == [
        {
            "executionId": "exec-1",
            "decision": "allow",
            "assertedDelegationId": "delegation-in-1",
            "recordedDecisionDelegationId": "delegation-in-1",
            "delegationId": "delegation-in-1",
            "delegationReferenceState": "matched_canonical_record",
            "delegationEvidenceRef": {
                "id": "delegation-in-1",
                "type": "relationship",
                "source": "delegations",
                "observedAt": "2026-10-01T00:00:00Z",
                "confidence": None,
                "uri": None,
            },
            "action": "read",
            "resource": "customer:123",
            "reason": "scope_matched",
            "decisionAt": "2026-10-02T00:00:30+00:00",
            "decisionTimestampState": "recorded",
            "scope": "action_scoped_request_time_only",
            "evidenceRef": {
                "id": "exec-1",
                "type": "event",
                "source": "agent_executions",
                "observedAt": "2026-10-02T00:00:00Z",
                "confidence": None,
                "uri": None,
            },
        }
    ]
    decision_claim = next(
        claim
        for claim in result.claims
        if claim.kind == "server_recorded_delegation_decision"
    )
    assert decision_claim.domainSlotIds == [
        "authority_envelope",
        "authority_check",
        "policy_boundary",
    ]
    policy_boundary = sections["policy_boundary"]
    assert policy_boundary.state == "degraded"
    assert policy_boundary.content["effectivePolicyState"] == "unknown"
    assert policy_boundary.content["decisionScope"] == "historical_action_scoped_only"
    assert policy_boundary.content["decisions"][0]["id"] == decision_claim.id
    assert "standing_policy_boundary_incomplete" in policy_boundary.warnings
    assert policy_boundary.content["standingDelegationReadComplete"] is True
    assert policy_boundary.content["standingDelegationScopes"][0]["delegationId"] == "delegation-in-1"
    assert policy_boundary.content["standingDelegationScopes"][0]["effectiveAuthorization"] == "unknown"
    assert authority["delegationRecords"][0]["recordState"] == "active_as_reported_by_repository"
    assert authority["delegationRecords"][0]["authorizationDecision"] == "unknown"
    assert authority["delegationRecords"][0]["authorizationKind"] == "capability"
    assert authority["delegationRecords"][0]["capabilityObserved"] is False
    assert authority["delegationRecords"][0]["grantorParty"] == {
        "state": "resolved",
        "party": {"kind": "human", "id": "owner-1"},
        "evidenceRefs": [
            {
                "id": "delegation-in-1",
                "type": "relationship",
                "source": "delegations",
                "observedAt": "2026-10-01T00:00:00Z",
                "confidence": None,
                "uri": None,
            },
            {
                "id": "owner-1",
                "type": "entity",
                "source": "entities",
                "observedAt": "2026-09-01T00:00:00Z",
                "confidence": None,
                "uri": None,
            },
        ],
        "reason": None,
    }
    assert authority["delegationRecords"][0]["granteeParty"]["party"] == {
        "kind": "agent",
        "id": "canonical-agent-a",
    }
    assert {ref["source"] for ref in authority["evidenceRefs"]} == {
        "agent_configs",
        "delegations",
        "entities",
    }
    party_claims = [
        claim
        for claim in result.claims
        if claim.kind == "canonically_resolved_delegation_party"
    ]
    owner_claim = next(
        claim for claim in result.claims if claim.kind == "configured_agent_owner_identity"
    )
    assert owner_claim.claimState == EpistemicStatus.RESOLVED
    assert owner_claim.domainSlotIds == ["owner_delegator", "actor_attribution"]
    assert {ref.source for ref in owner_claim.evidenceRefs} == {"agent_configs", "entities"}
    assert "does not independently establish legal ownership" in owner_claim.claims[0]
    assert len(party_claims) == 2
    assert all(claim.claimState == EpistemicStatus.RESOLVED for claim in party_claims)
    assert all(
        claim.domainSlotIds
        == ["owner_delegator", "delegation_chain", "actor_attribution"]
        for claim in party_claims
    )
    assert all({ref.source for ref in claim.evidenceRefs} == {"delegations", "entities"} for claim in party_claims)
    assert all(
        claim.kind != "canonically_resolved_delegation_party"
        or "authenticated-user-1" not in str(claim.model_dump(mode="json"))
        for claim in result.claims
    )
    assert source.delegation_subjects == ["canonical-agent-a"] * 3
    assert source.party_identity_subjects == [{"owner-1", "canonical-agent-a"}]

    assert sections["timeline"].content["causalRelationsDeclared"] is False
    timeline_messages = [
        item
        for item in sections["timeline"].content["entries"]
        if item.get("kind") == "agent_message_observation"
    ]
    assert [item["messageObservationId"] for item in timeline_messages] == ["message-1"]
    assert sections["evidence"].content["count"] >= 4
    assert sections["outcomes"].state == "unknown"
    assert "business outcome" in sections["outcomes"].content["reason"]
    assert sections["summary"].content["counts"]["communicationMessages"] == 1
    communication = sections["interactions"].content["communications"]
    assert communication["state"] == "available"
    assert communication["binding"] == "exact_tenant_inbox_agent_id_to_observed_message"
    assert communication["messages"][0]["messageObservationId"] == "message-1"
    assert communication["messages"][0]["subjectBindingBasis"] == "exact_tenant_inbox_agent_id"
    assert communication["messages"][0]["evidenceRef"]["source"] == "obs_agent_messages"
    unsupported = sections["summary"].content["unsupportedSlots"]
    assert any(item["slot"] == "economic_cost_and_settlement" for item in unsupported)

    claim_states = {claim.claimState for claim in result.claims}
    assert claim_states == {EpistemicStatus.OBSERVED, EpistemicStatus.RESOLVED}
    assert all(claim.evidenceRefs for claim in result.claims)
    assert any(claim.kind == "canonically_resolved_agent_identity" for claim in result.claims)
    assert any(claim.kind == "authenticated_execution_principal" for claim in result.claims)
    assert not any(
        claim.kind == "canonically_resolved_execution_principal" for claim in result.claims
    )
    assert any(claim.kind == "server_recorded_delegation_decision" for claim in result.claims)
    serialized = str([section.model_dump(mode="json") for section in result.sections])
    assert "private reasoning" not in serialized
    assert "private output" not in serialized
    assert "must not be projected" not in serialized
    assert "private message subject" not in serialized
    assert "private-from@example.test" not in serialized
    assert "private-to@example.test" not in serialized
    assert "private message body" not in serialized
    assert (
        "was not evaluated"
        in " ".join(
            claim.claims[0] for claim in result.claims if claim.kind == "agent_delegation_record"
        ).lower()
    )


@pytest.mark.asyncio
async def test_agent360_resolves_configured_owner_without_delegation_records():
    class OwnerOnlySource(FakeSource):
        async def incoming_delegations(self, tenant_id, canonical_agent_entity_id, limit):
            self.delegation_subjects.append(canonical_agent_entity_id)
            return []

        async def outgoing_delegations(self, tenant_id, canonical_agent_entity_id, limit):
            self.delegation_subjects.append(canonical_agent_entity_id)
            return []

        async def active_incoming_delegations(self, tenant_id, canonical_agent_entity_id):
            self.delegation_subjects.append(canonical_agent_entity_id)
            return Agent360ReadBatch(rows=[])

    source = OwnerOnlySource()
    result = await Agent360Provider(source).project(_request(), _context())
    actor = _sections(result)["state"].content["dimensions"][1]["content"]
    owner_claim = next(
        claim for claim in result.claims if claim.kind == "configured_agent_owner_identity"
    )

    assert source.party_identity_subjects == [{"owner-1"}]
    assert actor["configuredOwnerIdentity"]["state"] == "resolved"
    assert actor["configuredOwnerIdentity"]["canonicalParty"] == {
        "kind": "human",
        "id": "owner-1",
    }
    assert owner_claim.claimState == EpistemicStatus.RESOLVED
    assert {ref.source for ref in owner_claim.evidenceRefs} == {"agent_configs", "entities"}


@pytest.mark.asyncio
async def test_agent360_does_not_resolve_configured_owner_from_foreign_entity_row():
    class ForeignOwnerSource(FakeSource):
        async def incoming_delegations(self, tenant_id, canonical_agent_entity_id, limit):
            return []

        async def outgoing_delegations(self, tenant_id, canonical_agent_entity_id, limit):
            return []

        async def active_incoming_delegations(self, tenant_id, canonical_agent_entity_id):
            return Agent360ReadBatch(rows=[])

        async def delegation_party_identities(self, tenant_id, party_entity_ids):
            self.party_identity_subjects.append(set(party_entity_ids))
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": "foreign-tenant",
                        "party_entity_id": "owner-1",
                        "party_entity_type": "human",
                        "identity_evidence_id": "owner-1",
                        "identity_evidence_source": "entities",
                        "identity_observed_at": "2026-09-01T00:00:00Z",
                    }
                ],
                scope_mismatch=True,
            )

    source = ForeignOwnerSource()
    result = await Agent360Provider(source).project(_request(), _context())
    sections = _sections(result)
    actor = sections["state"].content["dimensions"][1]["content"]
    authority = sections["state"].content["dimensions"][2]
    owner_identity = actor["configuredOwnerIdentity"]
    owner_claim = next(
        claim for claim in result.claims if claim.kind == "agent_owner_identity_resolution"
    )

    assert source.party_identity_subjects == [{"owner-1"}]
    assert owner_identity["state"] == "unknown"
    assert owner_identity["canonicalParty"] is None
    assert {ref["source"] for ref in owner_identity["evidenceRefs"]} == {"agent_configs"}
    assert owner_identity["effectiveOwnership"] == "unknown"
    assert owner_identity["effectiveAuthorization"] == "unknown"
    assert authority["state"] == "degraded"
    assert owner_claim.claimState == EpistemicStatus.UNKNOWN
    assert {ref.source for ref in owner_claim.evidenceRefs} == {"agent_configs"}
    assert "agent_delegation_party_identity_scope_mismatch" in result.degradedReasons
    assert "agent_owner_identity_unresolved" in result.degradedReasons
    assert "foreign-tenant" not in str(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_agent360_keeps_capability_coverage_partial_without_exact_canonical_grant():
    foreign_grant = {
        "tenant_id": "tenant-b",
        "agent_id": "canonical-agent-a",
        "grantee_entity_id": "canonical-agent-a",
        "authorization_id": "foreign-capability-grant",
        "authorization_kind": "capability",
        "capability_id": "capability-search",
        "scope": {
            "actions": ["invoke"],
            "resources": ["capability:capability-search"],
        },
        "state": "active",
    }
    result = await Agent360Provider(FakeSource(capability_grants=[foreign_grant])).project(
        _request(), _context()
    )
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )
    access_profile = authority["content"]["capabilityAccessProfile"]

    assert access_profile["state"] == "partial"
    assert access_profile["counts"] is None
    assert access_profile["authorization"]["known"] is False
    assert access_profile["authorization"]["activeGrantCount"] is None
    assert access_profile["capabilities"][0]["invokeGrantCoversCapability"] is None
    assert access_profile["authorization"]["activeGrantRecordIds"] == []
    assert "canonical_capability_grant_read_incomplete" in access_profile["missingInputs"]
    assert not any(claim.domainSlotIds == ["capabilities"] for claim in result.claims)


@pytest.mark.asyncio
async def test_agent360_evidence_trace_requires_refs_and_obeys_frame_policy():
    result = await Agent360Provider(FakeSource()).project(_request(), _context())
    evidence_section = _sections(result)["evidence"]
    trace_claim = next(
        claim for claim in result.claims if claim.kind == "agent360_validated_evidence_trace"
    )
    assert trace_claim.domainSlotIds == ["evidence_trace"]
    assert trace_claim.claimState == EpistemicStatus.OBSERVED
    assert trace_claim.evidenceRefs
    assert {(ref.id, ref.source) for ref in trace_claim.evidenceRefs} <= {
        (ref["id"], ref["source"]) for ref in evidence_section.content["evidence"]
    }

    frame_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
        requestedSlotIds=["evidence_trace"],
        includeEvidence=True,
    )
    allowed = compose_experience360_frame(
        frame_request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    )
    slot = allowed.slots[0]
    assert slot.id == "evidence_trace"
    assert slot.content is not None
    assert any(claim.kind == trace_claim.kind for claim in slot.claims)
    assert slot.evidenceRefs and slot.provenance

    denied = compose_experience360_frame(
        frame_request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="denied"),
    )
    suppressed = denied.slots[0]
    assert suppressed.state == "suppressed"
    assert suppressed.content is None
    assert suppressed.claims == []
    assert suppressed.evidenceRefs == []


@pytest.mark.asyncio
async def test_agent360_evidence_trace_joins_exact_bronze_lineage_and_keeps_unknowns():
    class ExactProvenanceSource(FakeSource):
        async def activities(self, tenant_id, agent_id, limit):
            rows = await super().activities(tenant_id, agent_id, limit)
            return [
                {
                    **row,
                    "canonical_event_id": "bronze-activity-1",
                    "canonical_event_schema_version": SCHEMA_VERSION,
                }
                for row in rows
            ]

        async def tools(self, tenant_id, agent_id, limit):
            rows = await super().tools(tenant_id, agent_id, limit)
            return [
                {
                    **row,
                    "canonical_event_id": "bronze-tool-1",
                    "canonical_event_schema_version": SCHEMA_VERSION,
                }
                for row in rows
            ]

        async def risk_signals(self, tenant_id, agent_id, limit):
            rows = await super().risk_signals(tenant_id, agent_id, limit)
            return [
                {
                    **row,
                    "canonical_event_id": "bronze-risk-1",
                    "canonical_event_schema_version": SCHEMA_VERSION,
                }
                for row in rows
            ]

        async def agentic_provenance(self, tenant_id, agent_id, queries, limit):
            rows = []
            for query in queries[:limit]:
                record = build_agentic_provenance_record(
                    tenant_id=tenant_id,
                    bronze_event_id=query.bronze_event_id,
                    bronze_schema_version=query.bronze_schema_version,
                    bronze_event_type=query.evidence_ref.event_type,
                    reference=query.evidence_ref,
                    provider_claim="mcp",
                    observed_at=query.evidence_ref.observed_at,
                    received_at="2026-10-07T00:00:00Z",
                    ingested_at="2026-10-07T00:00:00Z",
                )
                rows.append(
                    {
                        **record.model_dump(mode="json", by_alias=True),
                        "source_row_id": f"bronze-row-{query.bronze_event_id}",
                        "source_tag_claim": "mcp",
                        "bronze_created_at": "2026-10-07T00:00:00Z",
                    }
                )
            return Agent360ReadBatch(rows=rows)

    source = ExactProvenanceSource()
    result = await Agent360Provider(source).project(_request(), _context())
    evidence = _sections(result)["evidence"].content
    source_provenance = evidence["sourceProvenance"]

    assert source_provenance["state"] == "partial"
    assert source_provenance["lineageState"] == "verified"
    assert source_provenance["exactBronzeLinks"] == 2
    assert source_provenance["unresolvedLinks"] == 0
    assert source_provenance["sourceIdentityState"] == "unresolved"
    assert source_provenance["sourceTrust"] == "unknown"
    assert source_provenance["freshness"] == {
        "state": "not_assessed",
        "slaSeconds": None,
        "reason": "agentic_source_freshness_sla_not_configured",
    }
    assert {ref["id"] for ref in evidence["evidence"] if ref["source"] == "bronze_sdk_events"} == {
        "bronze-activity-1",
        "bronze-tool-1",
    }
    assert source.risk_signal_calls == 0
    assert all(record["source_id"] is None for record in source_provenance["records"])
    assert all(
        record["freshness_state"] == "not_assessed"
        for record in source_provenance["records"]
    )

    denied = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="agent360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="agent", id=AGENT),
            requestedSlotIds=["evidence_trace"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=Experience360PolicyDisposition(state="denied"),
    )
    assert denied.slots[0].state == "suppressed"
    assert denied.slots[0].content is None
    assert denied.slots[0].claims == []
    assert denied.slots[0].evidenceRefs == []


@pytest.mark.asyncio
async def test_agent360_communications_claim_cites_inbox_and_message_under_policy():
    result = await Agent360Provider(FakeSource()).project(_request(), _context())
    communication_claim = next(
        claim for claim in result.claims if claim.kind == "agent_communication_observation"
    )
    assert communication_claim.domainSlotIds == ["communications"]
    assert {(ref.source, ref.id) for ref in communication_claim.evidenceRefs} == {
        ("agent_deployment_identity_bindings", "binding-agent-a"),
        ("obs_agent_inboxes", "inbox-1"),
        ("obs_agent_messages", "message-1"),
    }
    communication = _sections(result)["interactions"].content["communications"]
    assert {
        (ref["source"], ref["id"])
        for ref in communication["messages"][0]["bindingEvidenceRefs"]
    } == {
        ("obs_agent_inboxes", "inbox-1"),
        ("obs_agent_messages", "message-1"),
    }

    frame_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
        requestedSlotIds=["communications"],
        includeEvidence=True,
    )
    allowed = compose_experience360_frame(
        frame_request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    )
    slot = allowed.slots[0]
    assert slot.id == "communications"
    assert slot.content is not None
    assert any(claim.kind == communication_claim.kind for claim in slot.claims)
    assert {ref.source for ref in slot.evidenceRefs} >= {
        "obs_agent_inboxes",
        "obs_agent_messages",
    }
    assert slot.provenance

    denied = compose_experience360_frame(
        frame_request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="denied"),
    )
    assert denied.slots[0].state == "suppressed"
    assert denied.slots[0].content is None
    assert denied.slots[0].claims == []
    assert denied.slots[0].evidenceRefs == []


@pytest.mark.asyncio
async def test_agent360_communications_are_not_read_without_one_canonical_agent() -> None:
    class UnresolvedSource(FakeSource):
        def __init__(self):
            super().__init__()
            self.communication_reads = 0

        async def actor_identity(self, tenant_id, agent_id):
            return Agent360ReadBatch(rows=[])

        async def communications(self, tenant_id, agent_id, limit):
            self.communication_reads += 1
            return await super().communications(tenant_id, agent_id, limit)

    source = UnresolvedSource()
    result = await Agent360Provider(source).project(_request(), _context())
    communication = _sections(result)["interactions"].content["communications"]
    assert source.communication_reads == 0
    assert communication["state"] == "unknown"
    assert communication["messages"] == []
    assert communication["count"] is None
    assert "identity is unresolved" in communication["reason"]
    assert not any(
        claim.kind == "agent_communication_observation" for claim in result.claims
    )

    class AmbiguousSource(UnresolvedSource):
        async def actor_identity(self, tenant_id, agent_id):
            first = (await FakeSource.actor_identity(self, tenant_id, agent_id)).rows[0]
            return Agent360ReadBatch(
                rows=[
                    first,
                    {**first, "canonical_agent_entity_id": "another-tenant-agent"},
                ]
            )

    ambiguous = AmbiguousSource()
    result = await Agent360Provider(ambiguous).project(_request(), _context())
    assert ambiguous.communication_reads == 0
    assert _sections(result)["interactions"].content["communications"]["messages"] == []
    assert not any(
        claim.kind == "agent_communication_observation" for claim in result.claims
    )


@pytest.mark.asyncio
async def test_agent360_communication_claim_does_not_repeat_untrusted_direction() -> None:
    class UntrustedDirectionSource(FakeSource):
        async def communications(self, tenant_id, agent_id, limit):
            batch = await super().communications(tenant_id, agent_id, limit)
            return Agent360ReadBatch(
                rows=[{**row, "direction": "private message body"} for row in batch.rows]
            )

    result = await Agent360Provider(UntrustedDirectionSource()).project(
        _request(), _context()
    )
    claim = next(
        claim for claim in result.claims if claim.kind == "agent_communication_observation"
    )
    assert "private message body" not in str(claim.model_dump(mode="json"))
    message = _sections(result)["interactions"].content["communications"]["messages"][0]
    assert message["direction"] is None


@pytest.mark.asyncio
async def test_agent360_communication_without_inbox_proof_or_in_window_is_unclaimed():
    class UnprovenCommunicationSource(FakeSource):
        async def communications(self, tenant_id, agent_id, limit):
            batch = await super().communications(tenant_id, agent_id, limit)
            rows = [{**row, "inbox_evidence_ref": None} for row in batch.rows]
            return Agent360ReadBatch(rows=rows)

    unproven = await Agent360Provider(UnprovenCommunicationSource()).project(
        _request(), _context()
    )
    assert not any(
        claim.kind == "agent_communication_observation" for claim in unproven.claims
    )
    assert _sections(unproven)["interactions"].content["communications"]["messages"] == []
    assert "agent_source_scope_mismatch" in unproven.degradedReasons

    earlier_window = _request(
        time_range={"from": "2026-10-03T00:00:00Z", "to": "2026-10-03T23:59:59Z"}
    )
    outside = await Agent360Provider(FakeSource()).project(earlier_window, _context())
    assert not any(
        claim.kind == "agent_communication_observation" for claim in outside.claims
    )
    outside_communications = _sections(outside)["interactions"].content["communications"]
    assert outside_communications["messages"] == []
    assert outside_communications["count"] == 0
    assert "event_time_window" in outside_communications["temporalSemantics"]


@pytest.mark.asyncio
async def test_agent360_evidence_trace_does_not_claim_empty_or_foreign_rows():
    empty = await Agent360Provider(FakeSource(empty=True)).project(_request(), _context())

    class ForeignOnlySource(FakeSource):
        async def agent_configs(self, tenant_id, agent_id):
            return [{"tenant_id": "foreign-tenant", "agent_id": agent_id}]

    foreign = await Agent360Provider(ForeignOnlySource(empty=True)).project(
        _request(), _context()
    )
    for result in (empty, foreign):
        assert not any(
            claim.kind == "agent360_validated_evidence_trace" for claim in result.claims
        )
        frame = compose_experience360_frame(
            Experience360FrameRequest(
                surfaceId="agent360",
                tenantId=TENANT,
                subject=ProjectionSubject(kind="agent", id=AGENT),
                requestedSlotIds=["evidence_trace"],
                includeEvidence=True,
            ),
            [result],
            frame_policy=Experience360PolicyDisposition(state="allowed"),
        )
        assert frame.slots[0].state != "available"
        assert frame.slots[0].content is None
        assert frame.slots[0].claims == []
        assert frame.slots[0].evidenceRefs == []

    no_claims = await Agent360Provider(FakeSource()).project(
        _request(include_claims=False), _context()
    )
    assert no_claims.claims == []
    assert _sections(no_claims)["evidence"].content["evidence"]


@pytest.mark.asyncio
async def test_agent360_window_evidence_trace_claims_only_admitted_observations():
    request = _request(
        time_range={"from": "2026-10-03T00:00:00Z", "to": "2026-10-03T23:59:59Z"}
    )
    result = await Agent360Provider(FakeSource()).project(request, _context())
    actor = _sections(result)["state"].content["dimensions"][1]["content"]
    assert actor["configuredOwnerIdentity"]["temporalSemantics"].startswith(
        "current_agent_configuration_and_tenant_entity_state"
    )
    assert not any(
        claim.domainSlotIds
        and "owner_delegator" in claim.domainSlotIds
        and claim.kind == "configured_agent_owner_identity"
        for claim in result.claims
    )

    trace_claim = next(
        claim for claim in result.claims if claim.kind == "agent360_validated_evidence_trace"
    )
    assert {(ref.source, ref.id) for ref in trace_claim.evidenceRefs} == {
        ("obs_agent_activities", "obs-1")
    }

    empty_window = _request(
        time_range={"from": "2026-10-09T00:00:00Z", "to": "2026-10-09T23:59:59Z"}
    )
    empty_result = await Agent360Provider(FakeSource()).project(empty_window, _context())
    assert not any(
        claim.kind == "agent360_validated_evidence_trace" for claim in empty_result.claims
    )


@pytest.mark.asyncio
async def test_agent360_policy_boundary_shows_stored_grant_without_action_decision():
    class NoActionDecisionSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            rows = await super().executions(tenant_id, agent_id, limit)
            rows[0]["policy_log"].pop("delegation_check", None)
            return rows

    result = await Agent360Provider(NoActionDecisionSource()).project(_request(), _context())
    policy_boundary = _sections(result)["policy_boundary"]

    assert policy_boundary.state == "degraded"
    assert policy_boundary.content["effectivePolicyState"] == "unknown"
    assert policy_boundary.content["decisionScope"] == "no_action_scoped_decision_observed"
    assert policy_boundary.content["decisions"] == []
    assert policy_boundary.content["standingDelegationReadComplete"] is True
    assert policy_boundary.content["standingDelegationScopes"][0]["scope"] == {
        "actions": ["invoke"],
        "resources": ["capability:tool-1"],
    }
    assert "standing_policy_boundary_incomplete" in policy_boundary.warnings
    assert any(
        claim.kind == "observed_standing_delegation_scope"
        and "policy_boundary" in claim.domainSlotIds
        for claim in result.claims
    )
    assert not any(
        claim.kind == "server_recorded_delegation_decision" for claim in result.claims
    )


@pytest.mark.asyncio
async def test_agent360_policy_boundary_stays_unknown_without_grant_or_decision():
    class NoPolicyEvidenceSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            return []

        async def incoming_delegations(self, tenant_id, canonical_agent_entity_id, limit):
            return []

        async def active_incoming_delegations(self, tenant_id, canonical_agent_entity_id):
            return Agent360ReadBatch(rows=[])

    result = await Agent360Provider(NoPolicyEvidenceSource()).project(_request(), _context())
    policy_boundary = _sections(result)["policy_boundary"]
    assert policy_boundary.state == "unknown"
    assert policy_boundary.content is None
    assert policy_boundary.warnings == ["standing_policy_boundary_not_exposed"]


@pytest.mark.asyncio
async def test_agent360_policy_boundary_degrades_when_execution_decision_read_is_truncated():
    class TruncatedExecutionSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            rows = await super().executions(tenant_id, agent_id, limit)
            return Agent360ReadBatch(rows=rows, truncated=True)

    result = await Agent360Provider(TruncatedExecutionSource()).project(_request(), _context())
    policy_boundary = _sections(result)["policy_boundary"]

    assert policy_boundary.state == "degraded"
    assert policy_boundary.content["state"] == "partial"
    assert policy_boundary.content["effectivePolicyState"] == "unknown"
    assert policy_boundary.content["decisionScope"] == "historical_action_scoped_only"
    assert len(policy_boundary.content["decisions"]) == 1
    assert "action_scoped_policy_decision_read_truncated" in policy_boundary.warnings


@pytest.mark.asyncio
async def test_agent360_keeps_unresolved_delegation_party_unknown_and_degrades_authority():
    class MissingGrantorIdentitySource(FakeSource):
        async def delegation_party_identities(self, tenant_id, party_entity_ids):
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": tenant_id,
                        "party_entity_id": "canonical-agent-a",
                        "party_entity_type": "agent",
                        "identity_evidence_id": "canonical-agent-a",
                        "identity_evidence_source": "entities",
                        "identity_observed_at": "2026-09-02T00:00:00Z",
                    }
                ]
            )

    result = await Agent360Provider(MissingGrantorIdentitySource()).project(_request(), _context())
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )
    grantor = authority["content"]["delegationRecords"][0]["grantorParty"]
    unknown_claim = next(
        claim
        for claim in result.claims
        if claim.id == "delegation_party.delegation-in-1.grantor"
    )

    assert authority["state"] == "degraded"
    assert authority["content"]["effectiveAuthorizationDecision"] == "unknown"
    assert grantor["state"] == "unknown"
    assert grantor["party"] is None
    assert grantor["reason"] == "no tenant-scoped canonical entity row resolved this party ID"
    assert unknown_claim.claimState == EpistemicStatus.UNKNOWN
    assert unknown_claim.domainSlotIds == [
        "owner_delegator",
        "delegation_chain",
        "actor_attribution",
    ]
    assert {ref.source for ref in unknown_claim.evidenceRefs} == {"delegations"}
    assert "agent_delegation_party_identity_unresolved" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_conflicting_delegation_party_entities_do_not_select_a_kind():
    class DuplicateGrantorIdentitySource(FakeSource):
        async def delegation_party_identities(self, tenant_id, party_entity_ids):
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": tenant_id,
                        "party_entity_id": "owner-1",
                        "party_entity_type": entity_type,
                        "identity_evidence_id": "owner-1",
                        "identity_evidence_source": "entities",
                        "identity_observed_at": "2026-09-01T00:00:00Z",
                    }
                    for entity_type in ("human", "organization")
                ]
                + [
                    {
                        "tenant_id": tenant_id,
                        "party_entity_id": "canonical-agent-a",
                        "party_entity_type": "agent",
                        "identity_evidence_id": "canonical-agent-a",
                        "identity_evidence_source": "entities",
                        "identity_observed_at": "2026-09-02T00:00:00Z",
                    }
                ]
            )

    result = await Agent360Provider(DuplicateGrantorIdentitySource()).project(
        _request(), _context()
    )
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )
    grantor = authority["content"]["delegationRecords"][0]["grantorParty"]
    disputed_claim = next(
        claim
        for claim in result.claims
        if claim.id == "delegation_party.delegation-in-1.grantor"
    )

    assert authority["state"] == "degraded"
    assert grantor["state"] == "conflicted"
    assert grantor["party"] is None
    assert {ref["source"] for ref in grantor["evidenceRefs"]} == {"delegations", "entities"}
    assert disputed_claim.claimState == EpistemicStatus.DISPUTED
    assert {ref.source for ref in disputed_claim.evidenceRefs} == {"delegations", "entities"}
    assert "agent_delegation_party_identity_conflicted" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_keeps_source_reported_outcomes_unmeasured_with_exact_subject_context():
    class SourceReportedOutcomeSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            rows = await super().executions(tenant_id, agent_id, limit)
            rows[0].update(
                {
                    "outcome": "completed",
                    "outcome_ref": "opaque-callback-outcome-1",
                    "actor_type": "agent",
                    "value_amount": "2500.00",
                }
            )
            return rows

        async def activities(self, tenant_id, agent_id, limit):
            return await self._rows(
                "activities",
                [
                    {
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "observation_id": "agent-outcome-callback-1",
                        "event_name": "agent_outcome_recorded",
                        "observed_at": "2026-10-03T00:00:00Z",
                        "action": {"name": "report_outcome", "status": "source_reported"},
                        "actor_type": "agent",
                        "outcome_ref": "opaque-callback-outcome-1",
                        "value_amount": "2500.00",
                    }
                ],
            )

    result = await Agent360Provider(SourceReportedOutcomeSource()).project(
        _request(), _context()
    )
    sections = _sections(result)
    outcomes = sections["outcomes"].content
    interactions = sections["interactions"].content["items"]
    callback = next(
        item for item in interactions if item.get("eventName") == "agent_outcome_recorded"
    )

    assert sections["outcomes"].state == "unknown"
    assert outcomes["state"] == "unknown"
    assert outcomes["claims"] == []
    assert outcomes["measuredOutcomeAuthority"] == {
        "projection": "outcome360",
        "dependencyState": "unknown",
        "factState": "unknown",
        "subject": {
            "tenantId": TENANT,
            "kind": "agent",
            "id": "canonical-agent-a",
            "bindingState": "resolved",
            "evidenceRefs": [
                {
                    "id": "binding-agent-a",
                    "type": "entity",
                    "source": "agent_deployment_identity_bindings",
                    "observedAt": "2026-10-01T00:00:00Z",
                    "confidence": None,
                    "uri": None,
                }
            ],
        },
        "readByAgent360": False,
    }
    assert outcomes["sourceReportedEvidence"]["state"] == "not_used_for_measurement"
    assert callback["evidenceRef"]["id"] == "agent-outcome-callback-1"
    assert callback["evidenceRef"]["source"] == "obs_agent_activities"

    serialized = str([section.model_dump(mode="json") for section in result.sections])
    assert "opaque-callback-outcome-1" not in serialized
    assert "2500.00" not in serialized


@pytest.mark.asyncio
async def test_agent360_does_not_canonicalize_execution_delegation_reference_without_record_join():
    class UnlinkedDelegationSource(FakeSource):
        async def incoming_delegations(self, tenant_id, canonical_agent_entity_id, limit):
            self.delegation_subjects.append(canonical_agent_entity_id)
            return await self._rows("incoming", [])

        async def active_incoming_delegations(self, tenant_id, canonical_agent_entity_id):
            self.delegation_subjects.append(canonical_agent_entity_id)
            return await self._rows("active", [])

    result = await Agent360Provider(UnlinkedDelegationSource()).project(_request(), _context())
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )
    action_decision = authority["content"]["actionScopedDecisions"][0]

    assert authority["state"] == "degraded"
    assert authority["content"]["effectiveAuthorizationDecision"] == "unknown"
    assert action_decision["decision"] == "allow"
    assert action_decision["assertedDelegationId"] == "delegation-in-1"
    assert action_decision["recordedDecisionDelegationId"] == "delegation-in-1"
    assert action_decision["delegationId"] is None
    assert action_decision["delegationReferenceState"] == "unresolved"
    assert action_decision["delegationEvidenceRef"] is None
    assert "agent_execution_delegation_reference_unresolved" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_rejects_conflicting_execution_and_policy_log_delegation_ids():
    class ConflictingDelegationReferenceSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            rows = await super().executions(tenant_id, agent_id, limit)
            rows[0]["policy_log"]["delegation_check"]["delegation_id"] = (
                "different-delegation"
            )
            return rows

    result = await Agent360Provider(ConflictingDelegationReferenceSource()).project(
        _request(), _context()
    )
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )
    action_decision = authority["content"]["actionScopedDecisions"][0]

    assert authority["state"] == "degraded"
    assert action_decision["assertedDelegationId"] == "delegation-in-1"
    assert action_decision["recordedDecisionDelegationId"] == "different-delegation"
    assert action_decision["delegationId"] is None
    assert action_decision["delegationReferenceState"] == "conflicted"
    assert action_decision["delegationEvidenceRef"] is None
    assert "agent_execution_delegation_reference_conflicted" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_marks_invalid_recorded_decision_timestamp_unknown_and_degraded():
    class InvalidDecisionTimestampSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            rows = await super().executions(tenant_id, agent_id, limit)
            rows[0]["policy_log"]["delegation_check"]["evaluated_at"] = "not-an-instant"
            return rows

    result = await Agent360Provider(InvalidDecisionTimestampSource()).project(
        _request(), _context()
    )
    authority = next(
        item
        for item in _sections(result)["state"].content["dimensions"]
        if item["id"] == "authority_and_delegation"
    )
    action_decision = authority["content"]["actionScopedDecisions"][0]

    assert action_decision["decisionAt"] is None
    assert action_decision["decisionTimestampState"] == "invalid"
    assert "agent_execution_decision_timestamp_invalid" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_resolves_authenticated_principal_to_canonical_human_with_evidence():
    class ResolvedPrincipalSource(FakeSource):
        async def principal_identities(self, tenant_id, principal_user_ids, limit):
            assert principal_user_ids == {"authenticated-user-1"}
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": tenant_id,
                        "principal_user_id": "authenticated-user-1",
                        "canonical_human_entity_id": "human-canonical-1",
                        "identity_evidence_refs": [
                            {
                                "id": "identity-alias-1",
                                "type": "entity",
                                "source": "identity_aliases",
                                "observedAt": "2026-10-01T00:00:00Z",
                            },
                            {
                                "id": "identity-subject-1",
                                "type": "entity",
                                "source": "identity_subjects",
                                "observedAt": "2026-10-01T00:00:00Z",
                            },
                        ],
                    }
                ]
            )

    result = await Agent360Provider(ResolvedPrincipalSource()).project(_request(), _context())
    sections = _sections(result)
    actor = sections["state"].content["dimensions"][1]["content"]

    assert actor["executionPrincipal"]["id"] == "authenticated-user-1"
    assert actor["executionPrincipalCanonicalIdentity"] == {
        "state": "resolved",
        "canonicalHumanEntityId": "human-canonical-1",
        "candidateEntityIds": ["human-canonical-1"],
        "evidenceRefs": [
            {
                "id": "identity-alias-1",
                "type": "entity",
                "source": "identity_aliases",
                "observedAt": "2026-10-01T00:00:00Z",
                "confidence": None,
                "uri": None,
            },
            {
                "id": "identity-subject-1",
                "type": "entity",
                "source": "identity_subjects",
                "observedAt": "2026-10-01T00:00:00Z",
                "confidence": None,
                "uri": None,
            },
        ],
        "reason": None,
    }
    assert "authenticated principal identity state is resolved" in actor["reason"]
    assert "action authorization remains unknown" in actor["reason"]
    claim = next(
        claim
        for claim in result.claims
        if claim.kind == "canonically_resolved_execution_principal"
    )
    assert claim.claimState == EpistemicStatus.RESOLVED
    assert claim.domainSlotIds == ["actor_attribution"]
    assert {ref.source for ref in claim.evidenceRefs} == {
        "agent_executions",
        "identity_aliases",
        "identity_subjects",
    }
    assert any(
        raw_ref["source"] == "identity_aliases"
        for raw_ref in sections["evidence"].content["evidence"]
    )


@pytest.mark.asyncio
async def test_repository_agent360_source_resolves_principal_via_active_user_alias():
    class FakeIdentityRepository:
        def __init__(self):
            self.alias_query = None

        async def find_aliases_by_signal(self, tenant_id, alias_type, alias_hash, *, limit):
            self.alias_query = (tenant_id, alias_type, alias_hash, limit)
            return [
                {
                    "id": "identity-alias-1",
                    "tenant_id": tenant_id,
                    "alias_type": IdentitySignalType.USER_ID.value,
                    "alias_value_hash": alias_hash,
                    "canonical_entity_id": "merged-human-id",
                    "confidence_tier": "deterministic",
                    "last_seen_at": "2026-10-01T00:00:00Z",
                    "revoked_at": None,
                }
            ]

        async def resolve_surviving_canonical_entity_id(self, tenant_id, canonical_entity_id):
            assert tenant_id == TENANT
            assert canonical_entity_id == "merged-human-id"
            return "human-canonical-1"

        async def get_subject_by_canonical_entity_id(self, tenant_id, canonical_entity_id):
            return {
                "id": "identity-subject-1",
                "tenant_id": tenant_id,
                "canonical_entity_id": canonical_entity_id,
                "entity_type": "human",
                "status": "active",
                "last_seen_at": "2026-10-01T00:00:00Z",
            }

    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)
    source._principal_identity_repository = FakeIdentityRepository()

    result = await source.principal_identities(
        TENANT, {"authenticated-user-1"}, limit=10
    )

    assert result.truncated is False
    assert result.scope_mismatch is False
    assert result.rows == [
        {
            "tenant_id": TENANT,
            "principal_user_id": "authenticated-user-1",
            "canonical_human_entity_id": "human-canonical-1",
            "identity_evidence_refs": [
                {
                    "id": "identity-alias-1",
                    "type": "entity",
                    "source": "identity_aliases",
                    "observedAt": "2026-10-01T00:00:00Z",
                    "confidence": None,
                    "uri": None,
                },
                {
                    "id": "identity-subject-1",
                    "type": "entity",
                    "source": "identity_subjects",
                    "observedAt": "2026-10-01T00:00:00Z",
                    "confidence": None,
                    "uri": None,
                },
            ],
        }
    ]
    assert source._principal_identity_repository.alias_query == (
        TENANT,
        IdentitySignalType.USER_ID,
        hash_value("authenticated-user-1", scope=f"user:{TENANT}"),
        11,
    )


@pytest.mark.parametrize(
    ("alias_changes", "subject_type"),
    [
        ({"confidence_tier": "probabilistic"}, "human"),
        ({"revoked_at": "2026-10-02T00:00:00Z"}, "human"),
        ({"tenant_id": "other-tenant"}, "human"),
        ({}, "organization"),
    ],
)
@pytest.mark.asyncio
async def test_repository_agent360_principal_identity_rejects_untrusted_aliases(
    alias_changes, subject_type
):
    class UntrustedIdentityRepository:
        async def find_aliases_by_signal(self, tenant_id, alias_type, alias_hash, *, limit):
            return [
                {
                    "id": "identity-alias-1",
                    "tenant_id": tenant_id,
                    "alias_type": IdentitySignalType.USER_ID.value,
                    "alias_value_hash": alias_hash,
                    "canonical_entity_id": "human-canonical-1",
                    "confidence_tier": "deterministic",
                    **alias_changes,
                }
            ]

        async def resolve_surviving_canonical_entity_id(self, tenant_id, canonical_entity_id):
            return canonical_entity_id

        async def get_subject_by_canonical_entity_id(self, tenant_id, canonical_entity_id):
            return {
                "id": "identity-subject-1",
                "tenant_id": tenant_id,
                "canonical_entity_id": canonical_entity_id,
                "entity_type": subject_type,
                "status": "active",
            }

    source = RepositoryAgent360Source.__new__(RepositoryAgent360Source)
    source._principal_identity_repository = UntrustedIdentityRepository()

    result = await source.principal_identities(TENANT, {"authenticated-user-1"}, limit=10)

    assert result.rows == []
    assert result.scope_mismatch is True


@pytest.mark.asyncio
async def test_agent360_does_not_resolve_principal_without_identity_authority_provenance():
    class UnprovenPrincipalSource(FakeSource):
        async def principal_identities(self, tenant_id, principal_user_ids, limit):
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": tenant_id,
                        "principal_user_id": "authenticated-user-1",
                        "canonical_human_entity_id": "human-canonical-1",
                        "identity_evidence_refs": [
                            {
                                "id": "identity-alias-1",
                                "type": "entity",
                                "source": "identity_aliases",
                            },
                            {
                                "id": "execution-record-1",
                                "type": "event",
                                "source": "agent_executions",
                            },
                        ],
                    }
                ]
            )

    result = await Agent360Provider(UnprovenPrincipalSource()).project(_request(), _context())
    actor = _sections(result)["state"].content["dimensions"][1]["content"]

    assert actor["executionPrincipalCanonicalIdentity"]["state"] == "conflicted"
    assert actor["executionPrincipalCanonicalIdentity"]["canonicalHumanEntityId"] is None
    assert not any(
        claim.kind == "canonically_resolved_execution_principal" for claim in result.claims
    )


@pytest.mark.asyncio
async def test_agent360_does_not_collapse_multiple_authenticated_execution_principals():
    class MultiplePrincipalSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            rows = await super().executions(tenant_id, agent_id, limit)
            return rows + [
                {
                    **rows[0],
                    "execution_id": "exec-2",
                    "initiating_principal_user_id": "authenticated-user-2",
                    "started_at": "2026-10-03T00:00:00Z",
                }
            ]

    result = await Agent360Provider(MultiplePrincipalSource()).project(_request(), _context())
    actor = _sections(result)["state"].content["dimensions"][1]["content"]

    assert actor["executionPrincipal"] is None
    assert actor["executionPrincipalState"] == "ambiguous"
    assert {item["principal"]["id"] for item in actor["executionPrincipalCandidates"]} == {
        "authenticated-user-1",
        "authenticated-user-2",
    }
    assert len(actor["executionPrincipalEvidenceRefs"]) == 2


@pytest.mark.asyncio
async def test_agent360_keeps_unobserved_agent_unknown_and_reports_real_empty_reads():
    result = await Agent360Provider(FakeSource(empty=True)).project(_request(), _context())
    sections = _sections(result)

    assert sections["summary"].state == "unknown"
    assert sections["summary"].content["identity"]["state"] == "unknown"
    assert sections["summary"].content["counts"]["executions"] == 0
    assert sections["summary"].content["counts"]["riskSignals"] is None
    # The source Agent reference is unresolved, so the communication store is
    # deliberately not read and an empty count would overstate coverage.
    assert sections["summary"].content["counts"]["communicationMessages"] is None
    assert sections["timeline"].state == "empty"
    assert sections["timeline"].content["count"] == 0
    assert sections["outcomes"].state == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_agent360_preserves_truncated_communication_scan_as_incomplete():
    class TruncatedCommunicationSource(FakeSource):
        async def communications(self, tenant_id, agent_id, limit):
            batch = await super().communications(tenant_id, agent_id, limit)
            return Agent360ReadBatch(rows=batch.rows, truncated=True)

    result = await Agent360Provider(TruncatedCommunicationSource()).project(_request(), _context())
    sections = _sections(result)

    assert sections["summary"].state == "degraded"
    assert sections["summary"].content["sourceStates"]["communications"] == "truncated"
    assert sections["summary"].content["counts"]["communicationMessages"] is None
    assert sections["interactions"].content["communications"]["truncated"] is True
    assert "communications_read_truncated" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_marks_communication_scope_mismatch_degraded_and_incomplete():
    class MismatchedCommunicationSource(FakeSource):
        async def communications(self, tenant_id, agent_id, limit):
            batch = await super().communications(tenant_id, agent_id, limit)
            return Agent360ReadBatch(rows=batch.rows, scope_mismatch=True)

    result = await Agent360Provider(MismatchedCommunicationSource()).project(_request(), _context())
    sections = _sections(result)

    assert sections["summary"].content["sourceStates"]["communications"] == "degraded"
    assert sections["summary"].content["counts"]["communicationMessages"] is None
    assert "communications_scope_mismatch" in sections["summary"].warnings
    assert sections["timeline"].state == "degraded"
    assert sections["timeline"].content["count"] is None
    assert sections["interactions"].state == "degraded"
    assert sections["interactions"].content["communications"]["state"] == "degraded"
    assert sections["interactions"].content["communications"]["count"] is None
    assert [
        message["messageObservationId"]
        for message in sections["interactions"].content["communications"]["messages"]
    ] == ["message-1"]
    assert "agent_source_scope_mismatch" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_filters_cross_scope_execution_but_marks_its_counts_incomplete():
    class CrossScopeExecutionSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            rows = await super().executions(tenant_id, agent_id, limit)
            return rows + [
                {
                    "tenant_id": "tenant-foreign",
                    "agent_id": agent_id,
                    "execution_id": "foreign-execution",
                    "started_at": "2026-10-03T00:00:00Z",
                }
            ]

    result = await Agent360Provider(CrossScopeExecutionSource()).project(_request(), _context())
    sections = _sections(result)

    assert sections["summary"].content["sourceStates"]["executions"] == "degraded"
    assert sections["summary"].content["counts"]["executions"] is None
    assert "executions_scope_mismatch" in sections["summary"].warnings
    dimensions = sections["state"].content["dimensions"]
    execution = next(item for item in dimensions if item["id"] == "execution_lifecycle")
    assert execution["state"] == "degraded"
    assert [row["executionId"] for row in execution["content"]["records"]] == ["exec-1"]
    assert sections["timeline"].state == "degraded"
    assert sections["timeline"].content["count"] is None
    assert sections["interactions"].state == "degraded"
    assert "foreign-execution" not in str(result.model_dump(mode="json"))
    assert "agent_source_scope_mismatch" in result.degradedReasons
    actor = sections["state"].content["dimensions"][1]["content"]
    assert actor["executionPrincipal"] is None
    assert actor["executionPrincipalState"] == "partial"


@pytest.mark.asyncio
async def test_agent360_fail_isolates_source_errors_and_never_echoes_exception_details():
    result = await Agent360Provider(FakeSource(fail="executions")).project(_request(), _context())
    sections = _sections(result)

    assert "agent_execution_source_unavailable" in result.degradedReasons
    assert sections["summary"].content["counts"]["executions"] is None
    assert sections["timeline"].state == "degraded"
    serialized = str([section.model_dump(mode="json") for section in result.sections])
    assert "secret database diagnostic" not in serialized


@pytest.mark.asyncio
async def test_agent360_resolves_only_tenant_canonical_agent_entity_subjects():
    canonical_agent_id = "canonical-agent-entity"

    class CanonicalAgentEntitySource(FakeSource):
        async def actor_identity(self, tenant_id, agent_id):
            self.calls += 1
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "canonical_agent_entity_id": canonical_agent_id,
                        "identity_evidence_id": canonical_agent_id,
                        "identity_evidence_source": "entities",
                        "identity_binding_authority": "canonical_agent_entity",
                        "identity_bound_at": "2026-10-01T00:00:00Z",
                    }
                ]
            )

    source = CanonicalAgentEntitySource()
    result = await Agent360Provider(source).project(
        _request(kind="entity", subject_id=canonical_agent_id), _context()
    )
    sections = _sections(result)

    assert sections["summary"].content["subject"] == {
        "kind": "entity",
        "id": canonical_agent_id,
    }
    assert sections["summary"].content["identity"]["canonicalAgentEntityId"] == canonical_agent_id
    assert sections["state"].content["dimensions"][1]["state"] == "matched"
    assert source.calls > 1


@pytest.mark.asyncio
async def test_agent360_does_not_report_empty_delegations_when_agent_identity_is_unresolved():
    class UnresolvedAgentSource(FakeSource):
        async def actor_identity(self, tenant_id, agent_id):
            return Agent360ReadBatch(rows=[])

    source = UnresolvedAgentSource()
    result = await Agent360Provider(source).project(_request(), _context())
    sections = _sections(result)
    authority = sections["state"].content["dimensions"][2]["content"]

    assert source.delegation_subjects == []
    assert authority["state"] == "degraded"
    assert authority["delegationRecords"] == []
    assert authority["activeIncomingCount"] is None
    assert sections["summary"].content["counts"]["delegationRecords"] is None
    assert "agent_identity_binding_unresolved" in result.degradedReasons
    assert sections["summary"].content["sourceStates"]["incoming_delegations"] == "unknown"


@pytest.mark.asyncio
async def test_agent360_never_resolves_identity_from_a_truncated_binding_read():
    class TruncatedIdentitySource(FakeSource):
        async def actor_identity(self, tenant_id, agent_id):
            batch = await super().actor_identity(tenant_id, agent_id)
            return Agent360ReadBatch(rows=batch.rows, truncated=True)

    source = TruncatedIdentitySource()
    result = await Agent360Provider(source).project(_request(), _context())
    sections = _sections(result)
    actor = sections["state"].content["dimensions"][1]["content"]

    assert actor["state"] == "unknown"
    assert actor["resolvedCanonicalActor"] is None
    assert source.delegation_subjects == []
    assert not any(claim.kind == "canonically_resolved_agent_identity" for claim in result.claims)
    assert "actor_identity_read_truncated" in result.degradedReasons
    assert "agent_identity_binding_unresolved" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_never_resolves_identity_from_a_scope_unknown_binding_read():
    class ScopeUnknownIdentitySource(FakeSource):
        async def actor_identity(self, tenant_id, agent_id):
            batch = await super().actor_identity(tenant_id, agent_id)
            return Agent360ReadBatch(rows=batch.rows, scope_known=False)

    source = ScopeUnknownIdentitySource()
    result = await Agent360Provider(source).project(_request(), _context())
    sections = _sections(result)
    actor = sections["state"].content["dimensions"][1]["content"]

    assert actor["state"] == "unknown"
    assert actor["resolvedCanonicalActor"] is None
    assert source.delegation_subjects == []
    assert not any(claim.kind == "canonically_resolved_agent_identity" for claim in result.claims)
    assert "agent_identity_binding_unresolved" in result.degradedReasons
    assert sections["summary"].content["sourceStates"]["actor_identity"] == "unknown"


@pytest.mark.asyncio
async def test_agent360_rejects_canonical_entity_when_binding_scope_is_unknown():
    canonical_agent_id = "canonical-agent-a"

    class ScopeUnknownCanonicalEntitySource(FakeSource):
        async def actor_identity(self, tenant_id, agent_id):
            batch = await super().actor_identity(tenant_id, agent_id)
            return Agent360ReadBatch(
                rows=[
                    {
                        **batch.rows[0],
                        "canonical_agent_entity_id": canonical_agent_id,
                        "identity_evidence_id": canonical_agent_id,
                        "identity_evidence_source": "entities",
                        "identity_binding_authority": "canonical_agent_entity",
                    }
                ],
                scope_known=False,
            )

    source = ScopeUnknownCanonicalEntitySource()
    result = await Agent360Provider(source).project(
        _request(kind="entity", subject_id=canonical_agent_id), _context()
    )

    assert source.calls == 1
    assert source.delegation_subjects == []
    assert result.claims == []
    assert result.degradedReasons == ["agent_entity_subject_unresolved"]


@pytest.mark.asyncio
async def test_agent360_does_not_read_agent_sources_for_unverified_entity_subject():
    source = FakeSource()
    result = await Agent360Provider(source).project(_request(kind="entity"), _context())

    assert source.calls == 1  # Only the canonical identity preflight is allowed.
    assert result.claims == []
    assert all(section.state == "unknown" for section in result.sections)
    assert result.degradedReasons == ["agent_entity_subject_unresolved"]
    assert "tenant-owned canonical Agent" in result.sections[0].content["reason"]


@pytest.mark.asyncio
async def test_agent360_refuses_current_records_for_historical_request():
    result = await Agent360Provider(FakeSource()).project(
        _request(temporal_mode="as_of", time_range={"from": "2026-10-01T00:00:00Z"}),
        _context(),
    )

    assert result.claims == []
    assert result.degradedReasons == ["agent_temporal_replay_unavailable"]
    assert all(
        "current rows are not served" in section.content["reason"] for section in result.sections
    )


@pytest.mark.asyncio
async def test_agent360_resolves_only_exact_observed_mcp_tool_catalog_identity():
    class CatalogSource(FakeSource):
        def __init__(self, *, exact: bool):
            super().__init__()
            self.exact = exact

        async def capability_access_profile(self, tenant_id, agent_id, canonical_agent_entity_id):
            batch = await super().capability_access_profile(
                tenant_id, agent_id, canonical_agent_entity_id
            )
            capability = batch.rows[0]["profile"]["reach"]["capabilities"][0]
            capability["capability_kind"] = "mcp_tool"
            capability["capability_id"] = (
                capability_id_for(tenant_id, "mcp", "mcp-main", "search")
                if self.exact else "foreign-or-inconsistent-id"
            )
            return batch

    async def tool_identity(exact: bool):
        result = await Agent360Provider(CatalogSource(exact=exact)).project(
            _request(), _context()
        )
        authority = next(
            item for item in _sections(result)["state"].content["dimensions"]
            if item["id"] == "authority_and_delegation"
        )
        return authority["content"]["capabilityAccessProfile"]["capabilities"][0]["toolIdentity"]

    resolved = await tool_identity(True)
    assert resolved["state"] == "resolved_observed_catalog"
    assert resolved["evidenceRef"]["source"] == "capability_catalog"
    assert resolved["effectiveToolAuthorization"] == "unknown"
    inconsistent = await tool_identity(False)
    assert inconsistent["state"] == "unknown"
    assert inconsistent["evidenceRef"] is None
