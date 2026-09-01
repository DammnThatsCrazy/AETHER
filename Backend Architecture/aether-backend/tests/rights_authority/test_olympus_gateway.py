from __future__ import annotations

import asyncio

import pytest

from services.integrations.data_rights.models import DataRightsGrantCreate
from services.integrations.data_rights.service import DataRightsService
from services.olympus.gateway import (
    OlympusGeneralizedGraphGateway,
    OlympusPromotionRequest,
    _PromotionRepository,
)
from shared.rights_authority.contracts import AttachRightsEnvelope, IssueRightsPolicySet
from shared.rights_authority.repository import RightsLedgerRepository
from shared.rights_authority.service import RightsAuthority


def run(coro):
    return asyncio.run(coro)


def test_olympus_gateway_requires_release_evidence_and_releases_after_signed_decision(monkeypatch):
    monkeypatch.setenv("AETHER_RIGHTS_AUTHORITY_MODE", "enforce")
    repo = RightsLedgerRepository()
    authority = RightsAuthority(repo, signing_key="test-key")
    monkeypatch.setattr("services.olympus.gateway.rights_authority", authority)

    policy = run(authority.issue_policy_set(IssueRightsPolicySet(
        tenant_id="tenant-olympus",
        agreement_ref={
            "contract_id": "agreement-1",
            "contract_version": "1",
            "accepted_at": "2026-09-01T00:00:00+00:00",
        },
        rights_profile="secure_tenant",
        activation_state="rights_active",
    )))
    grant = run(DataRightsService(repo).create_grant(DataRightsGrantCreate(
        tenant_id="tenant-olympus",
        source_id="source-1",
        connector_id="connector-1",
        connector_class="tenant_byod",
        data_category="events",
        raw_data_owner="tenant",
    ), granted_by_user_id="tenant-admin"))
    source = run(authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref={"kind": "feature", "id": "feature-1"},
        primary_rights_class="tenant_confidential_intelligence",
        policy_set_ref=policy.policy_set_id,
        tenant_id="tenant-olympus",
        source_grant_refs=[grant.data_rights_grant_id],
    )))

    gateway = OlympusGeneralizedGraphGateway(_PromotionRepository())
    request = OlympusPromotionRequest(
        tenant_id="tenant-olympus",
        input_envelope_refs=[source.envelope_id],
        policy_set_ref=policy.policy_set_id,
        source_grant_refs=[grant.data_rights_grant_id],
        approval_refs=["approval-1"],
        evidence={
            "lineage": [source.envelope_id],
            "privacy_test": "passed",
            "reidentification_test": "passed",
            "aggregate_threshold": 25,
            "release_proof": "release-proof-1",
        },
        requested_by="operator-1",
    )
    promotion = run(gateway.enqueue(request))
    released = run(gateway.process(promotion["promotion_id"]))

    assert released["status"] == "released"
    assert released["decision_id"]
    assert released["output_envelope_id"]


def test_olympus_gateway_kill_switch_blocks_queueing(monkeypatch):
    monkeypatch.setenv("AETHER_RIGHTS_AUTHORITY_MODE", "off")
    gateway = OlympusGeneralizedGraphGateway(_PromotionRepository())
    run(gateway.set_kill_switch(active=True, actor_id="operator-1", reason="incident"))
    request = OlympusPromotionRequest(
        tenant_id="tenant-olympus",
        input_envelope_refs=["rae-1"],
        policy_set_ref="rps-1",
        approval_refs=["approval-1"],
        evidence={"aggregate_threshold": 25, "release_proof": "proof"},
        requested_by="operator-1",
    )

    with pytest.raises(RuntimeError, match="kill_switch"):
        run(gateway.enqueue(request))
