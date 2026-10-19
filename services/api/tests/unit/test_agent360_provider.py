"""Focused contract tests for the read-only Agent360 projection provider."""

from __future__ import annotations

import os
import sys
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
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=subject_id),
        page={"limit": 10},
        timeRange=time_range,
        temporalMode=temporal_mode,
    )


class FakeSource:
    def __init__(self, *, empty: bool = False, fail: str | None = None) -> None:
        self.empty = empty
        self.fail = fail
        self.calls = 0
        self.delegation_subjects: list[str] = []

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

    async def capability_access_profile(self, tenant_id, agent_id):
        rows = await self._rows(
            "capability_access_profile",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
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

    async def communications(self, tenant_id, agent_id, limit):
        rows = await self._rows(
            "communications",
            [
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "subject_binding_basis": "exact_tenant_inbox_agent_id",
                    "inbox_obs_id": "inbox-1",
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
    assert disputed_claim.domainSlotIds == ["authority_and_delegation"]
    assert {ref.source for ref in disputed_claim.evidenceRefs} == {"delegations"}
    assert "agent_delegation_active_record_conflict" in result.degradedReasons


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
    assert authority["effectiveAuthorizationDecision"] == "unknown"
    access_profile = authority["capabilityAccessProfile"]
    assert access_profile["state"] == "available"
    assert access_profile["authorization"]["activeGrantCount"] == 1
    assert access_profile["authorization"]["activeGrantRecordIds"] == [
        "capability-grant-1"
    ]
    assert access_profile["capabilities"][0]["invokeGrantCoversCapability"] is True
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
            "decisionAt": "2026-10-02T00:00:00Z",
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
        "delegations",
        "entities",
    }
    party_claims = [
        claim
        for claim in result.claims
        if claim.kind == "canonically_resolved_delegation_party"
    ]
    assert len(party_claims) == 2
    assert all(claim.claimState == EpistemicStatus.RESOLVED for claim in party_claims)
    assert all(claim.domainSlotIds == ["authority_and_delegation"] for claim in party_claims)
    assert all({ref.source for ref in claim.evidenceRefs} == {"delegations", "entities"} for claim in party_claims)
    assert all(
        claim.kind != "canonically_resolved_delegation_party"
        or "authenticated-user-1" not in str(claim.model_dump(mode="json"))
        for claim in result.claims
    )
    assert source.delegation_subjects == ["canonical-agent-a"] * 3

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
    assert unknown_claim.domainSlotIds == ["authority_and_delegation"]
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
    assert sections["summary"].content["counts"]["riskSignals"] == 0
    assert sections["summary"].content["counts"]["communicationMessages"] == 0
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
