from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from repositories.account_deletion import AccountDeletionWorkflowRepository
from repositories.repos import APIKeyRepository, AdminRepository, reset_in_memory_stores
from repositories.typed_repo import reset_typed_in_memory_stores
from services.account_lifecycle.models import validate_step_up_evidence
from services.account_lifecycle.service import AccountLifecycleService
from services.account_lifecycle.storage_registry import (
    STORAGE_DOMAIN_REGISTRY,
    TENANT_SCOPED_REPOSITORY_REGISTRY,
    validate_storage_domain_coverage,
)
from services.auth.sessions import (
    public_ingest_service,
    service_credential_service,
    session_service,
)
from shared.common.common import BadRequestError, ConflictError


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()
    reset_typed_in_memory_stores()


def evidence(at: datetime | None = None) -> dict:
    return {
        "verified": True,
        "method": "mfa",
        "evidence_id": "reauth-123",
        "verified_at": (at or datetime.now(timezone.utc)).isoformat(),
        "assurance_level": "step_up",
        "provider": "test-auth",
    }


async def principal(tenant_id: str = "tenant-a") -> None:
    await AdminRepository().insert(tenant_id, {
        "status": "active", "plan_tier": "P2", "name": "Acme"
    })


@pytest.mark.asyncio
async def test_step_up_is_required_and_expired_evidence_is_rejected():
    now = datetime.now(timezone.utc)
    with pytest.raises(BadRequestError):
        validate_step_up_evidence({"verified": False}, now=now)
    with pytest.raises(BadRequestError):
        validate_step_up_evidence(evidence(now - timedelta(minutes=16)), now=now)


@pytest.mark.asyncio
async def test_request_suspends_and_revokes_all_exposed_credentials():
    await principal()
    session = await session_service.create_session("tenant-a", "user-a")
    await service_credential_service._accounts.insert("acct-a", {
        "tenant_id": "tenant-a", "status": "active", "name": "worker"
    })
    _, credential = await service_credential_service.issue_credential(
        "tenant-a", "acct-a", purpose="test", permissions=["read"]
    )
    ingest = await public_ingest_service.issue_identifier("tenant-a")
    await APIKeyRepository().insert("key-a", {
        "tenant_id": "tenant-a", "status": "active", "key_hash": "hash-a"
    })

    service = AccountLifecycleService()
    workflow = await service.request_deletion(
        tenant_id="tenant-a", actor_id="user-a", idempotency_key="delete-1",
        reauth_evidence=evidence(),
    )

    assert workflow["status"] == "recovery"
    assert (await AdminRepository().find_by_id("tenant-a"))["status"] == "suspended"
    with pytest.raises(Exception):
        await session_service.validate_session(session.token)
    with pytest.raises(Exception):
        await service_credential_service.validate_credential(_)
    assert (await APIKeyRepository().find_by_id("key-a"))["status"] == "revoked"
    assert (await public_ingest_service._repo.find_by_id(ingest["id"]))["status"] == "revoked"
    assert credential["tenant_id"] == "tenant-a"
    assert workflow["storage_results"]["domains"]["graph"]["status"] == "unavailable"
    assert workflow["storage_results"]["domains"]["object_store"]["status"] == "deferred"
    assert set(workflow["erasure_manifest"]["domains"]) == {
        domain.name for domain in STORAGE_DOMAIN_REGISTRY
    }


@pytest.mark.asyncio
async def test_recovery_cancellation_reactivates_tenant_but_keeps_audit_trail():
    await principal()
    service = AccountLifecycleService()
    workflow = await service.request_deletion(
        tenant_id="tenant-a", actor_id="user-a", idempotency_key="delete-2",
        reauth_evidence=evidence(),
    )
    cancelled = await service.cancel_during_window(
        workflow["id"], tenant_id="tenant-a", actor_id="user-a",
        reauth_evidence=evidence(),
    )
    assert cancelled["status"] == "cancelled"
    assert (await AdminRepository().find_by_id("tenant-a"))["status"] == "active"
    with pytest.raises(ConflictError):
        await service.cancel_during_window(
            workflow["id"], tenant_id="tenant-a", actor_id="user-a",
            reauth_evidence=evidence(),
        )


@pytest.mark.asyncio
async def test_processing_is_idempotent_and_retains_billing_and_audit_as_detached_stubs():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    await principal()
    service = AccountLifecycleService(now_factory=lambda: start)
    workflow = await service.request_deletion(
        tenant_id="tenant-a", actor_id="user-a", idempotency_key="delete-3",
        reauth_evidence=evidence(start),
    )
    due = start + timedelta(days=30, seconds=1)
    completed = await service.process_retry(
        workflow["id"], tenant_id="tenant-a", now=due
    )
    replay = await service.process_retry(
        workflow["id"], tenant_id="tenant-a", now=due + timedelta(seconds=1)
    )

    assert completed["status"] == "completed"
    assert replay["id"] == completed["id"]
    assert replay["retry_count"] == 1
    assert replay["erasure_manifest"]["fully_erased"] is False
    assert replay["erasure_manifest"]["completion"] == (
        "completed_with_unavailable_or_deferred_domains"
    )
    assert replay["storage_results"]["domains"]["billing"]["status"] == "retained"
    assert replay["storage_results"]["domains"]["audit"]["status"] == "retained"
    stubs = await service._retention_repo.find_many(limit=10)
    assert {stub["domain"] for stub in stubs} == {"billing", "audit"}
    assert all("tenant_id" not in stub for stub in stubs)
    assert await AdminRepository().find_by_id("tenant-a") is None


@pytest.mark.asyncio
async def test_idempotency_replays_same_workflow_without_new_suspension():
    await principal()
    service = AccountLifecycleService()
    first = await service.request_deletion(
        tenant_id="tenant-a", actor_id="user-a", idempotency_key="same",
        reauth_evidence=evidence(),
    )
    replay = await service.request_deletion(
        tenant_id="tenant-a", actor_id="user-a", idempotency_key="same",
        reauth_evidence=evidence(),
    )
    assert replay["id"] == first["id"]
    assert await AccountDeletionWorkflowRepository().count({"tenant_id": "tenant-a"}) == 1


def test_new_tenant_scoped_repository_without_domain_coverage_fails_closed():
    repositories = dict(TENANT_SCOPED_REPOSITORY_REGISTRY)
    repositories["new_tenant_repository"] = "missing_domain"
    with pytest.raises(AssertionError, match="missing account-erasure coverage"):
        validate_storage_domain_coverage(repositories, STORAGE_DOMAIN_REGISTRY)
