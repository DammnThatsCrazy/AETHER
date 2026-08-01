"""Tests for SDKConfigService ungated active-manifest retrieval.

Covers the management path used by the tenant settings UI: it must always see
the latest published manifest, even when a staged rollout would serve an
individual SDK instance the previous/stable version.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.sdk_config.service import SDKConfigService  # noqa: E402


@pytest.fixture
def svc() -> SDKConfigService:
    # In-memory store (no REDIS configured under AETHER_ENV=local).
    s = SDKConfigService()
    # Isolate cache and durable local repositories per test.
    from shared.store import InMemoryStore
    s._manifest_store = InMemoryStore(f"sdk_manifests_test_{id(s)}")
    from repositories.sdk_repos import SDKManifestStateRepository, SDKManifestVersionRepository
    s._versions = SDKManifestVersionRepository()
    s._versions.table_name = f"sdk_manifest_versions_{id(s)}"
    s._versions._store = {}
    s._states = SDKManifestStateRepository()
    s._states.table_name = f"sdk_manifest_states_{id(s)}"
    s._states._store = {}
    return s


@pytest.mark.asyncio
async def test_active_manifest_returns_none_when_unpublished(svc: SDKConfigService):
    manifest = await svc.get_active_manifest("tenant-a")
    assert manifest is None


@pytest.mark.asyncio
async def test_active_manifest_bypasses_rollout_gating(svc: SDKConfigService):
    tenant = "tenant-a"

    # v1 fully rolled out, then v2 as a 1% canary.
    await svc.publish_manifest(
        tenant_id=tenant, min_sdk_version="6.0.0", schema_version="7.0.0",
        features={"analytics": True}, endpoints={}, flags={}, rollout_percentage=100,
    )
    await svc.publish_manifest(
        tenant_id=tenant, min_sdk_version="6.0.0", schema_version="7.0.0",
        features={"analytics": False}, endpoints={}, flags={}, rollout_percentage=1,
    )

    # Find an sdk_id that falls OUTSIDE the 1% rollout (the common case).
    outside_id = next(
        sid for sid in (f"sdk-{i}" for i in range(100))
        if SDKConfigService._cohort_bucket(tenant, sid) >= 1
    )

    # The SDK-facing gated fetch serves the previous stable manifest (v1)...
    gated = await svc.get_manifest(tenant_id=tenant, sdk_id=outside_id)
    assert gated is not None and gated.manifest_version == "1"

    # ...but the settings/admin path always sees the current version (v2).
    active = await svc.get_active_manifest(tenant)
    assert active is not None and active.manifest_version == "2"
    assert active.features == {"analytics": False}
