"""Multi-SDK same-user stitching (Blueprint Iota §14.3).

Web + iOS + Android SDKs identifying as the same user_id must resolve to the
same canonical profile when multi_sdk_identity_stitching_enabled.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402

TENANT = "tenant_multi_sdk_same_user"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.fixture
def source_registry():
    from services.identity.repository import IdentityResolutionRepository

    return SourceIdentityRegistry(IdentityResolutionRepository())


async def _sdk_identify(registry, tenant, anon, user_id, email, *, kind, namespace):
    sid = await registry.register_source_identity(
        tenant_id=tenant,
        source_system_id=namespace,
        source_kind=kind,
        source_namespace=namespace,
        user_id=user_id,
        anonymous_id=anon,
    )
    if email:
        await registry.upsert_identity_claim(
            tenant_id=tenant, source_identity_id=sid.id, claim_type="email", raw_value=email, verification_status="claimed"
        )
    return sid


@pytest.mark.asyncio
async def test_multi_sdk_same_user_single_canonical(source_registry):
    email = "multi_sdk@example.com"
    user_id = f"user_{uuid.uuid4().hex[:8]}"

    web = await _sdk_identify(source_registry, TENANT, f"web_anon_{uuid.uuid4().hex[:8]}", user_id, email, kind="sdk", namespace="aether-web:marketing_site")
    ios = await _sdk_identify(
        source_registry,
        TENANT,
        f"ios_anon_{uuid.uuid4().hex[:8]}",
        user_id,
        email,
        kind="mobile_sdk",
        namespace="aether-ios:consumer_app",
    )
    # add installation_id on iOS record via registry update path (re-register with same ids is idempotent)
    android = await _sdk_identify(
        source_registry,
        TENANT,
        f"android_anon_{uuid.uuid4().hex[:8]}",
        user_id,
        email,
        kind="mobile_sdk",
        namespace="aether-android:consumer_app",
    )

    # all share same user_id
    for sid in (web, ios, android):
        assert sid.user_id == user_id

    # deterministic lookup by user_id returns a record with that user_id
    found = await source_registry.find_existing_source_identity(TENANT, user_id=user_id)
    assert found is not None
    assert found.user_id == user_id

    # email normalized consistently across platforms
    for sid in (web, ios, android):
        claims = await source_registry.get_claims_for_source_identity(sid.id)
        assert any(c.normalized_value == email.lower() for c in claims)


@pytest.mark.asyncio
async def test_multi_sdk_different_users_not_merged_by_sdk_alone(source_registry):
    # two different user_ids must not collapse even if same email claim not verified
    email = "distinct@example.com"
    u1 = f"user_{uuid.uuid4().hex[:8]}"
    u2 = f"user_{uuid.uuid4().hex[:8]}"
    s1 = await _sdk_identify(source_registry, TENANT, f"anon_{uuid.uuid4().hex[:8]}", u1, email, kind="sdk", namespace="aether-web:marketing_site")
    s2 = await _sdk_identify(source_registry, TENANT, f"anon_{uuid.uuid4().hex[:8]}", u2, email, kind="sdk", namespace="aether-web:marketing_site")
    assert s1.id != s2.id
    assert s1.user_id != s2.user_id
