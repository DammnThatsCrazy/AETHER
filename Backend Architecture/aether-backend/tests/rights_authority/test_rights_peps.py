from __future__ import annotations

import pytest

from shared.graph.graph import Edge, GraphClient
from shared.graph.mutation_gateway import GraphMutationGateway, MutationIntent
from shared.rights_authority.contracts import (
    ActorRef,
    AttachRightsEnvelope,
    IssueRightsPolicySet,
)
from shared.rights_authority.repository import RightsLedgerRepository
from shared.rights_authority.service import RightsAuthority
from services.integrations.data_rights.models import DataRightsGrantCreate
from services.integrations.data_rights.service import DataRightsService
from services.model_governance.training_gate import TrainingDataGate


async def _authority(tenant_id: str, *, training: bool = False):
    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="pep-test-key")
    profile = "collaborative_learning" if training else "secure_tenant"
    policy = await authority.issue_policy_set(IssueRightsPolicySet(
        tenant_id=tenant_id,
        agreement_ref={
            "contract_id": "agreement-pep",
            "contract_version": "1",
            "accepted_at": "2026-09-01T00:00:00+00:00",
        },
        rights_profile=profile,
        activation_state="rights_active",
    ))
    grant = await DataRightsService(repo).create_grant(
        DataRightsGrantCreate(
            tenant_id=tenant_id,
            source_id="source-pep",
            connector_id="connector-pep",
            connector_class="tenant_byod",
            data_category="events",
            raw_data_owner="tenant",
            model_training_allowed=training,
        ),
        granted_by_user_id="tenant-admin",
    )
    return authority, policy, grant


@pytest.mark.asyncio
async def test_graph_gateway_blocks_unproven_mutation_and_stamps_allowed_fact(monkeypatch):
    tenant_id = "pep-graph-tenant"
    authority, policy, grant = await _authority(tenant_id)
    envelope = await authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "graph_edge", "id": "edge-1", "tenant_id": tenant_id},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id=tenant_id,
        source_grant_refs=[grant.data_rights_grant_id],
    ))
    import shared.rights_authority.pep as pep
    monkeypatch.setattr(pep, "rights_authority", authority)
    monkeypatch.setenv("AETHER_RIGHTS_AUTHORITY_MODE", "enforce")

    graph = GraphClient()
    await graph.connect()
    gateway = GraphMutationGateway(graph_client=graph)
    intent = MutationIntent(
        operation="edge_created",
        tenant_id=tenant_id,
        edge=Edge("OWNS_WALLET", "user-1", "wallet-1", {"tenant_id": tenant_id}),
        actor_kind="service",
        actor_id="projection",
        rights_envelope_id=envelope.envelope_id,
        rights_policy_set_ref=policy.policy_set_id,
        rights_source_grant_refs=[grant.data_rights_grant_id],
    )
    allowed = await gateway.apply(intent, mode_override="shadow")
    assert allowed.applied
    assert allowed.rights_decision_id
    assert intent.edge.properties["rights_decision_id"] == allowed.rights_decision_id

    blocked = await gateway.apply(MutationIntent(
        operation="edge_created",
        tenant_id=tenant_id,
        edge=Edge("OWNS_WALLET", "user-2", "wallet-2", {"tenant_id": tenant_id}),
        actor_kind="service",
        actor_id="projection",
    ), mode_override="off")
    assert blocked.blocked
    assert "rights:rights_envelope_missing" in blocked.violations


@pytest.mark.asyncio
async def test_training_gate_requires_signed_irrl_training_decision(monkeypatch):
    tenant_id = "pep-training-tenant"
    authority, policy, grant = await _authority(tenant_id, training=True)
    envelope = await authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "training_record", "id": "record-1", "tenant_id": tenant_id},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id=tenant_id,
        source_grant_refs=[grant.data_rights_grant_id],
    ))
    import shared.rights_authority.pep as pep
    monkeypatch.setattr(pep, "rights_authority", authority)
    monkeypatch.setenv("AETHER_RIGHTS_AUTHORITY_MODE", "enforce")

    result = await TrainingDataGate().partition([
        {
            "record_ref": "record-1",
            "source_purposes": ["analytics"],
            "rights_envelope_refs": [envelope.envelope_id],
            "rights_source_grant_refs": [grant.data_rights_grant_id],
            "rights_policy_set_ref": policy.policy_set_id,
        }
    ], model_id="model-pep", tenant_id=tenant_id)
    assert result.admitted_count == 1
    assert result.admitted[0].rights_decision_id
    assert result.admitted[0].rights_outcome == "allow_with_obligations"

    denied = await TrainingDataGate().partition([
        {"record_ref": "record-without-envelope", "source_purposes": ["analytics"]}
    ], model_id="model-pep", tenant_id=tenant_id)
    assert denied.quarantined_count == 1
    assert any(reason.startswith("rights_deny:") for reason in denied.quarantined[0].quarantine_reasons)


@pytest.mark.asyncio
async def test_lake_last_mile_reloads_signed_receipt(monkeypatch):
    tenant_id = "pep-lake-tenant"
    authority, policy, grant = await _authority(tenant_id)
    envelope = await authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "silver_record", "id": "silver-1", "tenant_id": tenant_id},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id=tenant_id,
        source_grant_refs=[grant.data_rights_grant_id],
    ))
    from services.ingestion.rights import authorize_derivation, rights_context_from_result
    import shared.rights_authority.service as authority_module

    monkeypatch.setattr(authority_module, "rights_authority", authority)
    monkeypatch.setenv("AETHER_RIGHTS_AUTHORITY_MODE", "enforce")
    derivation = await authorize_derivation(
        tenant_id,
        artifact={"kind": "gold_feature", "id": "feature-1", "tenant_id": tenant_id},
        input_envelope_refs=[envelope.envelope_id],
        source_grant_refs=[grant.data_rights_grant_id],
        transform="feature_extraction",
        evidence={"lineage": envelope.envelope_id},
        authority=authority,
    )
    context = rights_context_from_result(derivation)
    from repositories.lake import GoldRepository

    row = await GoldRepository("pep_lake").materialize(
        metric_name="feature",
        entity_id="entity-1",
        entity_type="wallet",
        value={"x": 1},
        tenant_id=tenant_id,
        rights=context,
    )
    assert row["rights"]["rights_decision_refs"]

    context["decision_outcomes"] = ["allow"]
    with pytest.raises(ValueError, match="outcome mismatch"):
        await GoldRepository("pep_lake_tampered").materialize(
            metric_name="feature",
            entity_id="entity-1",
            entity_type="wallet",
            value={"x": 1},
            tenant_id=tenant_id,
            rights=context,
        )
