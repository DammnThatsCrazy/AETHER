from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.consent.control_plane import (
    TenantProcessingProfile,
    integration_policy_manifests,
    tenant_processing_profiles,
)
from services.integrations import discovery
from services.integrations.connectors.base import ConnectorConfig
from services.integrations.consent_policy import evaluate_connector_processing
from shared.common.common import BadRequestError, ForbiddenError
from shared.privacy.generated_integration_consent import (
    INTEGRATION_CONSENT_REGISTRY_VERSION,
)


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture
def discovery_enabled(monkeypatch):
    monkeypatch.setattr(
        discovery.settings,
        "integration_consent",
        SimpleNamespace(
            control_plane_v2_enabled=True,
            integration_discovery_enabled=True,
        ),
    )


def _stripe_config(tenant_id: str) -> dict:
    return ConnectorConfig(
        tenant_id=tenant_id,
        connector_type="stripe",
        enabled=False,
        secret_configured=True,
        secret_ref="vault:must-not-be-copied",
    ).model_dump()


@pytest.mark.asyncio
async def test_discovery_is_default_off_and_fails_closed(monkeypatch):
    monkeypatch.setattr(
        discovery.settings,
        "integration_consent",
        SimpleNamespace(
            control_plane_v2_enabled=True,
            integration_discovery_enabled=False,
        ),
    )

    with pytest.raises(ForbiddenError):
        await discovery.discover_configured_integrations(
            "tenant-1",
            [_stripe_config("tenant-1")],
        )


@pytest.mark.asyncio
async def test_discovery_persists_registry_backed_non_secret_detections(
    discovery_enabled,
):
    items = await discovery.discover_configured_integrations(
        "tenant-1",
        [_stripe_config("tenant-1")],
    )

    assert {item["capability"] for item in items} == {"pull", "webhook"}
    assert {item["provider"] for item in items} == {"Stripe"}
    assert {item["status"] for item in items} == {"manifest_required"}
    assert {
        item["policy_manifest_version"] for item in items
    } == {INTEGRATION_CONSENT_REGISTRY_VERSION}
    assert "secret_ref" not in str(items)
    assert "must-not-be-copied" not in str(items)


@pytest.mark.asyncio
async def test_draft_manifest_never_infers_admin_approval_or_consent(
    discovery_enabled,
):
    await discovery.discover_configured_integrations(
        "tenant-1",
        [_stripe_config("tenant-1")],
    )

    manifest = await discovery.create_draft_manifest(
        "tenant-1",
        "stripe",
        actor_id="admin-1",
    )

    assert manifest["status"] == "draft"
    assert manifest["tenant_admin_approved"] is False
    assert manifest["provider_admin_installed"] is False
    assert manifest["approved_purposes"] == []
    assert manifest["processing_basis"] == "contract"
    detections = await discovery.list_detections("tenant-1")
    assert {item["status"] for item in detections} == {"manifested"}


@pytest.mark.asyncio
async def test_manifest_approval_validates_registry_and_unblocks_policy(
    discovery_enabled,
):
    with pytest.raises(BadRequestError):
        await discovery.approve_manifest(
            "tenant-1",
            "stripe",
            approved_purposes=[],
            processing_basis="contract",
            allowed_fields=["event_id"],
            provider_admin_installed=True,
            actor_id="admin-1",
        )

    manifest = await discovery.approve_manifest(
        "tenant-1",
        "stripe",
        approved_purposes=["commerce"],
        processing_basis="contract",
        allowed_fields=["event_id"],
        provider_admin_installed=True,
        actor_id="admin-1",
    )
    await tenant_processing_profiles.upsert_profile(
        TenantProcessingProfile(
            tenant_id="tenant-1",
            status="active",
            policy_version=INTEGRATION_CONSENT_REGISTRY_VERSION,
            tenant_admin_approved=True,
            approved_purposes=["commerce"],
            allowed_processing_bases=["contract"],
        )
    )

    decision = await evaluate_connector_processing(
        "tenant-1",
        "stripe",
        source_kind="configuration",
        processing_basis="contract",
        action="enable",
    )

    assert manifest["status"] == "approved"
    assert manifest["tenant_admin_approved"] is True
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_discovery_and_manifests_remain_tenant_scoped(discovery_enabled):
    await discovery.discover_configured_integrations(
        "tenant-1",
        [_stripe_config("tenant-1")],
    )
    await discovery.create_draft_manifest(
        "tenant-1",
        "stripe",
        actor_id="admin-1",
    )

    assert await discovery.list_detections("tenant-2") == []
    assert await integration_policy_manifests.for_connector(
        "tenant-2",
        "stripe",
    ) is None
