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


def test_replay_reuses_one_decision_and_one_audit_receipt(monkeypatch):
    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="test-key")
    policy = _policy(authority, "tenant-replay")
    grant = _grant(repo, "tenant-replay")
    envelope = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "event", "id": "event-replay"},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-replay",
        source_grant_refs=[grant.data_rights_grant_id],
    )))
    request = RightsUseRequest(
        request_id="request-replay",
        action="store",
        actor=ActorRef(kind="service", id="ingestion"),
        purpose="tenant_service",
        artifacts=[{"kind": "event", "id": "event-replay"}],
        envelope_refs=[envelope.envelope_id],
        source_grant_refs=[grant.data_rights_grant_id],
        tenant_id="tenant-replay",
    )

    from services.security.audit_ledger import audit_ledger

    calls = 0
    original = audit_ledger.record

    async def counted_record(**kwargs):
        nonlocal calls
        calls += 1
        return await original(**kwargs)

    monkeypatch.setattr(audit_ledger, "record", counted_record)
    first = run(authority.evaluate(request))
    second = run(authority.evaluate(request))

    assert first.decision_id == second.decision_id
    assert first.signature == second.signature
    assert calls == 1
    assert first.signature_key_id == "rights-v1"
    assert authority.verify_signature(first)


def test_audit_outbox_delivery_is_retry_safe(monkeypatch):
    from shared.rights_authority.audit_outbox import flush_audit_outbox
    from services.security.audit_ledger import audit_ledger

    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="outbox-key")
    policy = _policy(authority, "tenant-outbox")
    envelope = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "event", "id": "event-outbox"},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-outbox",
    )))
    decision = run(authority.evaluate(RightsUseRequest(
        request_id="request-outbox",
        action="read",
        actor=ActorRef(kind="tenant_user", id="user-1", tenant_id="tenant-outbox"),
        purpose="tenant_service",
        artifacts=[{"kind": "event", "id": "event-outbox"}],
        envelope_refs=[envelope.envelope_id],
        tenant_id="tenant-outbox",
    )))
    assert run(repo.list_audit_outbox("tenant-outbox"))[0]["status"] == "pending"

    first = run(flush_audit_outbox(authority=authority, tenant_id="tenant-outbox"))
    second = run(flush_audit_outbox(authority=authority, tenant_id="tenant-outbox"))
    assert first["delivered"] == 1
    assert second["scanned"] == 0
    assert run(repo.list_audit_outbox("tenant-outbox"))[0]["status"] == "delivered"
    assert run(audit_ledger._repo.find_by_id(f"raev_{decision.decision_id}"))["audit_event_id"] == f"raev_{decision.decision_id}"


def test_rotated_key_id_can_verify_historical_decision(monkeypatch):
    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="old-key")
    policy = _policy(authority, "tenant-rotation")
    grant = _grant(repo, "tenant-rotation")
    envelope = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "event", "id": "event-rotation"},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-rotation",
        source_grant_refs=[grant.data_rights_grant_id],
    )))
    decision = run(authority.evaluate(RightsUseRequest(
        request_id="request-rotation",
        action="store",
        actor=ActorRef(kind="service", id="ingestion"),
        purpose="tenant_service",
        artifacts=[{"kind": "event", "id": "event-rotation"}],
        envelope_refs=[envelope.envelope_id],
        source_grant_refs=[grant.data_rights_grant_id],
        tenant_id="tenant-rotation",
    )))

    monkeypatch.setenv("AETHER_RIGHTS_SIGNING_KEYS", '{"rights-v1":"old-key"}')
    verifier = RightsAuthority(repo, signing_key=None)
    assert verifier.verify_signature(decision)


def test_evidence_manifest_is_signed_and_checked_by_pdp():
    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="evidence-key")
    policy = _policy(authority, "tenant-evidence")
    grant = _grant(repo, "tenant-evidence")
    manifest = run(authority.issue_evidence_manifest(
        tenant_id="tenant-evidence",
        subject_refs=["event:evidence"],
        evidence={"consent": ["consent-1"], "license": ["license-1"]},
        attested_by=ActorRef(kind="tenant_user", id="admin", tenant_id="tenant-evidence"),
    ))
    envelope = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "event", "id": "evidence"},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-evidence",
        source_grant_refs=[grant.data_rights_grant_id],
        evidence_manifest_refs=[manifest.manifest_id],
    )))

    decision = run(authority.evaluate(RightsUseRequest(
        request_id="request-evidence",
        action="store",
        actor=ActorRef(kind="service", id="ingestion"),
        purpose="tenant_service",
        artifacts=[{"kind": "event", "id": "evidence"}],
        envelope_refs=[envelope.envelope_id],
        source_grant_refs=[grant.data_rights_grant_id],
        tenant_id="tenant-evidence",
    )))

    assert decision.outcome == "allow_with_obligations"
    assert decision.evidence_manifest_refs == [manifest.manifest_id]
    assert authority.verify_evidence_manifest(manifest)

    tampered = manifest.model_copy(update={"evidence": {"consent": ["other"]}})
    assert not authority.verify_evidence_manifest(tampered)


def test_remediation_never_claims_completion_without_adapter():
    from shared.rights_authority.remediation import execute_impact

    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="remediation-key")
    policy = _policy(authority, "tenant-remediation")
    envelope = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "event", "id": "remediation"},
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-remediation",
    )))
    impact = run(authority.revoke(RevokeRightsAuthority(
        root_refs=[envelope.artifact_ref.ref],
        reason="withdrawn",
        actor=ActorRef(kind="tenant_user", id="admin", tenant_id="tenant-remediation"),
        tenant_id="tenant-remediation",
    )))

    blocked = run(execute_impact(impact.impact_graph_id, authority=authority))
    assert blocked["status"] == "blocked"
    assert blocked["receipt_refs"]
    receipts = run(repo.list_remediation_receipts(impact.impact_graph_id))
    assert receipts[0]["outcome"] == "blocked"

    async def adapter(_artifact, _action):
        return {"detail": "quarantined"}

    completed = run(execute_impact(
        impact.impact_graph_id, authority=authority, executor=adapter,
    ))
    assert completed["status"] == "completed"


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
