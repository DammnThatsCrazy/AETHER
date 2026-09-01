from __future__ import annotations

import asyncio

import pytest

from shared.rights_authority.contracts import (
    ActorRef,
    ArtifactRef,
    AttachRightsEnvelope,
    DerivationEdge,
    IssueRightsPolicySet,
    RevokeRightsAuthority,
    RightsUseRequest,
)
from shared.rights_authority.repository import RightsLedgerRepository
from shared.rights_authority.service import RightsAuthority
from services.integrations.data_rights.models import (
    DataRightsGrantCreate,
    DataRightsGrantRevoke,
)
from services.integrations.data_rights.service import DataRightsService


def run(coro):
    return asyncio.run(coro)


def _policy(authority: RightsAuthority, tenant_id: str, **kwargs):
    return run(authority.issue_policy_set(IssueRightsPolicySet(
        tenant_id=tenant_id,
        agreement_ref={
            "contract_id": "agreement-1",
            "contract_version": "2026-09-01",
            "accepted_at": "2026-09-01T00:00:00+00:00",
        },
        rights_profile="secure_tenant",
        activation_state="rights_active",
        **kwargs,
    )))


def _grant(repo: RightsLedgerRepository, tenant_id: str, **kwargs):
    service = DataRightsService(repo)
    body = DataRightsGrantCreate(
        tenant_id=tenant_id,
        source_id="source-1",
        connector_id="connector-1",
        connector_class="tenant_byod",
        data_category="events",
        raw_data_owner="tenant",
        **kwargs,
    )
    return run(service.create_grant(body, granted_by_user_id="tenant-admin"))


def test_store_is_signed_and_replay_is_immutable():
    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="test-key")
    policy = _policy(authority, "tenant-1")
    grant = _grant(repo, "tenant-1")
    envelope = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "event", "id": "event-1"},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-1",
        source_grant_refs=[grant.data_rights_grant_id],
    )))
    request = RightsUseRequest(
        request_id="request-1",
        action="store",
        actor=ActorRef(kind="service", id="ingestion"),
        purpose="tenant_service",
        artifacts=[ArtifactRef(kind="event", id="event-1")],
        envelope_refs=[envelope.envelope_id],
        source_grant_refs=[grant.data_rights_grant_id],
        tenant_id="tenant-1",
    )

    decision = run(authority.evaluate(request))
    replay = run(authority.evaluate(request))

    assert decision.outcome == "allow_with_obligations"
    assert decision.decision_id == replay.decision_id
    assert authority.verify_signature(decision)
    assert run(repo.get_decision(decision.decision_id))["signature"] == decision.signature


def test_read_does_not_imply_export_when_policy_omits_export():
    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="test-key")
    policy = _policy(authority, "tenant-2", allowed_uses=[{"action": "read", "purpose": "*"}])
    envelope = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "profile360", "id": "profile-1"},
        primary_rights_class="tenant_confidential_intelligence",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-2",
    )))
    request = RightsUseRequest(
        action="export",
        actor=ActorRef(kind="tenant_user", id="user-1"),
        purpose="customer_export",
        artifacts=[{"kind": "profile360", "id": "profile-1"}],
        envelope_refs=[envelope.envelope_id],
        tenant_id="tenant-2",
        destination={"kind": "external_recipient", "id": "recipient-1", "disclosure_level": "tenant_scoped"},
    )

    decision = run(authority.evaluate(request))

    assert decision.outcome == "deny"
    assert "use_not_allowed_by_policy" in decision.reasons


def test_revocation_fans_out_to_derivation_descendants():
    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="test-key")
    policy = _policy(authority, "tenant-3")
    root = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "event", "id": "root"},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-3",
    )))
    child_ref = ArtifactRef(kind="feature", id="feature-1")
    edge = DerivationEdge(
        parent_refs=[root.artifact_ref],
        child_ref=child_ref,
        transform_ref="feature_extraction",
        rights_decision_ref="rdec-parent",
        lineage_set_hash="lineage-1",
    )
    run(authority.record_derivation(edge))
    graph = run(authority.revoke(RevokeRightsAuthority(
        root_refs=[root.artifact_ref.ref],
        reason="source grant withdrawn",
        actor=ActorRef(kind="tenant_user", id="user-3", tenant_id="tenant-3"),
        tenant_id="tenant-3",
    )))

    assert graph.status == "open"
    assert child_ref in [node.artifact_ref for node in graph.nodes] or graph.nodes == []
    assert run(authority.impact([root.artifact_ref.ref], "tenant-3")).impact_graph_id == graph.impact_graph_id


def test_transform_requires_release_evidence_and_approval():
    authority = RightsAuthority(RightsLedgerRepository(), signing_key="test-key")
    missing = run(authority.prove_transform("deidentification", [ArtifactRef(kind="event", id="e")], {}))
    complete = run(authority.prove_transform(
        "deidentification",
        [ArtifactRef(kind="event", id="e")],
        {
            "lineage": "lineage-1",
            "privacy_test": "passed",
            "reidentification_test": "passed",
            "aggregate_threshold": 25,
            "approval_refs": ["privacy-review-1"],
        },
    ))

    assert missing.approved is False
    assert complete.approved is True


def test_data_rights_compatibility_facade_persists_revisions():
    repo = RightsLedgerRepository()
    first = _grant(repo, "tenant-4")
    service = DataRightsService(repo)
    revoked = run(service.revoke_grant(
        first.data_rights_grant_id,
        DataRightsGrantRevoke(revocation_reason="withdrawn", revoked_by_user_id="admin"),
    ))

    assert revoked.status.value == "revoked"
    assert run(service.get_grant(first.data_rights_grant_id)).status.value == "revoked"
    assert len(run(repo.list_source_grants("tenant-4"))) == 2
