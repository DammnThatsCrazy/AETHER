"""Durable late-binding actions remain visible while approval recovers."""

import uuid

import pytest

from services.identity.explainability import AdminIdentityService
from services.identity.pending_review import PendingIdentityReviewRepository
from services.identity.repository import IdentityResolutionRepository


@pytest.mark.asyncio
async def test_review_queue_keeps_inflight_and_recoverable_approval_states_visible():
    tenant_id = f"tenant-recovery-{uuid.uuid4().hex}"
    pending = PendingIdentityReviewRepository()
    row = await pending.upsert_candidate(
        tenant_id=tenant_id,
        identify_source_identity_id="sdk-source-recovery",
        candidate_source_identity_ids=["import-source-recovery"],
        reason_codes=["identity_match_requires_review"],
        evidence=[{"source_identity_id": "import-source-recovery", "claim_type": "email"}],
    )

    expected_statuses = (
        "open",
        "approving",
        "approval_recovery_required",
        "merge_committed",
    )
    prior = "open"
    for status in expected_statuses:
        if status != "open":
            assert await pending.compare_and_set_disposition(
                tenant_id=tenant_id,
                record_id=row["id"],
                expected_status=prior,
                status=status,
                reason_codes=[f"state_{status}"],
            )
        entries = await AdminIdentityService(
            repo=IdentityResolutionRepository()
        ).review_queue(tenant_id, limit=50)
        assert len(entries) == 1
        assert entries[0]["conflict_id"] == row["id"]
        assert entries[0]["status"] == status
        assert entries[0]["authority"] == "none"
        prior = status


@pytest.mark.asyncio
async def test_review_queue_does_not_expose_another_tenants_recovery_state():
    tenant_id = f"tenant-recovery-{uuid.uuid4().hex}"
    other_tenant = f"tenant-recovery-{uuid.uuid4().hex}"
    row = await PendingIdentityReviewRepository().upsert_candidate(
        tenant_id=other_tenant,
        identify_source_identity_id="sdk-source-cross-tenant",
        candidate_source_identity_ids=["import-source-cross-tenant"],
        reason_codes=["identity_match_requires_review"],
        evidence=[],
    )
    pending = PendingIdentityReviewRepository()
    assert await pending.compare_and_set_disposition(
        tenant_id=other_tenant,
        record_id=row["id"],
        expected_status="open",
        status="merge_committed",
    )

    entries = await AdminIdentityService(
        repo=IdentityResolutionRepository()
    ).review_queue(tenant_id, limit=50)
    assert entries == []
