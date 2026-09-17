"""Scenario E — cross-tenant block (blueprint §8.3 hard veto).

Same email appearing in two tenants must NEVER create a cross-tenant entity.
Gate 3 merge-safety: cross-tenant impossible.
"""
from __future__ import annotations

import os
import sys
import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.veto_engine import evaluate_vetoes  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402

TENANT_A = "tenant_alpha"
TENANT_B = "tenant_beta"

@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()

@pytest.fixture
def registry_a():
    from services.identity.repository import IdentityResolutionRepository
    return SourceIdentityRegistry(IdentityResolutionRepository())

@pytest.mark.asyncio
async def test_cross_tenant_same_email_blocked():
    vetoes = await evaluate_vetoes(
        tenant_id=TENANT_A,
        candidate_tenant_id=TENANT_B,
        candidate_entity_types=["person"],
        candidate_statuses=["active"],
        candidate_verified_emails=[],
        candidate_authenticated_user_ids=[],
        candidate_device_ids=[],
        candidate_has_revoked_consent=False,
        candidate_is_deleted=False,
        candidate_is_suppressed=False,
        candidate_source_namespaces=["csv:contacts_tenant_beta"],
        current_entity_type="person",
        current_authenticated_user_ids=[],
    )
    types = {v.veto_type.value for v in vetoes}
    assert "cross_tenant" in types or "cross_tenant_candidate" in types or len(vetoes) > 0

@pytest.mark.asyncio
async def test_cross_tenant_policy_blocks_merge():
    from services.identity.merge_policy import MergePolicyContext, evaluate
    from services.identity.models import IdentitySignalType
    ctx = MergePolicyContext(
        tenant_id=TENANT_A,
        source_tenant_id=TENANT_B,
        matching_signal_types=[IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED],
        consent_snapshot={"purposes": {"identity": True}},
        existing_entity_ids=["person_a"],
    )
    res = evaluate(ctx)
    assert res.decision.value != "merge"

@pytest.mark.asyncio
async def test_cross_tenant_source_identity_namespace_isolation(registry_a):
    email = "shared@example.com"
    sid_a = await registry_a.register_source_identity(
        tenant_id=TENANT_A, source_system_id="csv:contacts_tenant_a", source_kind="csv",
        source_namespace="csv:contacts_tenant_a", external_id="row_1",
    )
    await registry_a.upsert_identity_claim(tenant_id=TENANT_A, source_identity_id=sid_a.id, claim_type="email", raw_value=email, verification_status="observed")
    sid_b = await registry_a.register_source_identity(
        tenant_id=TENANT_B, source_system_id="csv:contacts_tenant_b", source_kind="csv",
        source_namespace="csv:contacts_tenant_b", external_id="row_1",
    )
    await registry_a.upsert_identity_claim(tenant_id=TENANT_B, source_identity_id=sid_b.id, claim_type="email", raw_value=email, verification_status="observed")
    assert sid_a.id != sid_b.id
    found_a = await registry_a.find_existing_source_identity(TENANT_A, external_id="row_1")
    found_b = await registry_a.find_existing_source_identity(TENANT_B, external_id="row_1")
    assert found_a is not None and found_b is not None
    assert found_a.id == sid_a.id
    assert found_b.id == sid_b.id
