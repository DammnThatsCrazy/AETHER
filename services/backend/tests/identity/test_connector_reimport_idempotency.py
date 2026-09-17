"""Scenario H — connector reimport idempotency (duplicate source dedup).

Gate 2 routing: re-importing same source_record must not duplicate source identities.
"""
from __future__ import annotations

import os
import sys
import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402

TENANT = "tenant_reimport_idempotent"

@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()

@pytest.fixture
def registry():
    from services.identity.repository import IdentityResolutionRepository
    return SourceIdentityRegistry(IdentityResolutionRepository())

@pytest.mark.asyncio
async def test_shopify_reimport_is_idempotent(registry):
    email = "jordan@example.com"
    sid1 = await registry.register_source_identity(
        tenant_id=TENANT, source_system_id="shopify:store_123", source_kind="shopify",
        source_namespace="shopify:store_123", external_id="cust_123",
    )
    await registry.upsert_identity_claim(tenant_id=TENANT, source_identity_id=sid1.id, claim_type="email", raw_value=email, verification_status="observed")
    sid2 = await registry.register_source_identity(
        tenant_id=TENANT, source_system_id="shopify:store_123", source_kind="shopify",
        source_namespace="shopify:store_123", external_id="cust_123",
    )
    assert sid2.id == sid1.id
    claims = await registry.get_claims_for_source_identity(sid1.id)
    emails = [c for c in claims if c.claim_type == "email"]
    assert len(emails) == 1

@pytest.mark.asyncio
async def test_csv_reimport_is_idempotent(registry):
    sid1 = await registry.register_source_identity(
        tenant_id=TENANT, source_system_id="csv:contacts", source_kind="csv",
        source_namespace="csv:contacts", external_id="row_42",
    )
    sid2 = await registry.register_source_identity(
        tenant_id=TENANT, source_system_id="csv:contacts", source_kind="csv",
        source_namespace="csv:contacts", external_id="row_42",
    )
    assert sid1.id == sid2.id

@pytest.mark.asyncio
async def test_different_external_ids_create_different_identities(registry):
    sid1 = await registry.register_source_identity(
        tenant_id=TENANT, source_system_id="shopify:store_123", source_kind="shopify",
        source_namespace="shopify:store_123", external_id="cust_1",
    )
    sid2 = await registry.register_source_identity(
        tenant_id=TENANT, source_system_id="shopify:store_123", source_kind="shopify",
        source_namespace="shopify:store_123", external_id="cust_2",
    )
    assert sid1.id != sid2.id

@pytest.mark.asyncio
async def test_sdk_idempotency_key_no_duplicate(registry):
    anon = "anon_dupe_001"
    sid1 = await registry.register_source_identity(
        tenant_id=TENANT, source_system_id="aether-web:site", source_kind="sdk",
        source_namespace="aether-web:site", anonymous_id=anon,
    )
    sid2 = await registry.register_source_identity(
        tenant_id=TENANT, source_system_id="aether-web:site", source_kind="sdk",
        source_namespace="aether-web:site", anonymous_id=anon,
    )
    assert sid1.id == sid2.id
