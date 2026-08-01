"""Tenant erasure removes provider credential versions (DSR cascade + purge)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.providers.credentials.authority import CredentialAuthority  # noqa: E402
from services.providers.credentials.repository import CredentialVersionRepo  # noqa: E402
from shared.privacy.retention import DeletionPlan  # noqa: E402


async def _seed(a: CredentialAuthority, tenant: str) -> None:
    await a.create_pending(tenant, "coinbase", "sandbox", "webhook_signing_secret", "wh", created_by="admin")
    await a.activate(tenant, "coinbase", "sandbox", "webhook_signing_secret", credential_version=1, actor="admin")


def test_standard_plan_includes_credential_step():
    plan = DeletionPlan(entity_id="t1", tenant_id="t1")
    plan.build_standard_plan()
    step = [s for s in plan.steps if s["table"] == "provider_credential_versions"]
    assert step and step[0]["entity_field"] == "tenant_id"


@pytest.mark.asyncio
async def test_tenant_erasure_removes_only_that_tenant():
    reset_in_memory_stores()
    a = CredentialAuthority()
    await _seed(a, "tenantA")
    await _seed(a, "tenantB")

    plan = DeletionPlan(entity_id="tenantA", tenant_id="tenantA", reason="tenant_erasure")
    plan.add_step(
        "postgresql", "provider_credential_versions",
        __import__("shared.privacy.retention", fromlist=["DeletionBehavior"]).DeletionBehavior.HARD_DELETE,
        __import__("shared.privacy.retention", fromlist=["DataClassification"]).DataClassification.SENSITIVE_PII,
        "", entity_field="tenant_id",
    )
    result = await plan.execute({"postgresql:provider_credential_versions": CredentialVersionRepo()})
    assert result["failed"] == 0

    repo = CredentialVersionRepo()
    assert await repo.versions_for_slot("tenantA", "coinbase", "sandbox", "webhook_signing_secret") == []
    assert await repo.versions_for_slot("tenantB", "coinbase", "sandbox", "webhook_signing_secret")


@pytest.mark.asyncio
async def test_purge_tenant_helper():
    reset_in_memory_stores()
    a = CredentialAuthority()
    await _seed(a, "tenantA")
    assert await a.purge_tenant("tenantA") >= 1
    repo = CredentialVersionRepo()
    assert await repo.versions_for_slot("tenantA", "coinbase", "sandbox", "webhook_signing_secret") == []
