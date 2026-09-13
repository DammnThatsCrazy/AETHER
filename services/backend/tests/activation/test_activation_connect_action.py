"""WS-3 connect actions — one action run through the shared connector runtime.

:meth:`ActivationPlanner.run_connect_action` must delegate to
``connector_service`` (the exact runtime behind the Settings connect surface) —
never a second implementation. These tests pin that contract over the four
activation actions:

* ``create_tenant_integration`` — enables a config row through the consent-aware
  configure path;
* ``configure_credential`` — hands the secret to the credential service and flips
  ``secret_configured`` (the secret itself is never stored on the config);
* ``enable_connection`` — re-enables a disabled, credential-ready row;
* ``first_sync`` — surfaces an honest ``ok=False`` + ``sync_failed`` when the
  provider cannot pull (webhook), rather than a server error or a fabricated
  forward step.

Invalid families/actions and non-connectable catalog members (advertising) are
client errors, keeping the activation surface honest about what it can run.
"""
from __future__ import annotations

import pytest

from services.activation.planner import (
    ActivationPlanner,
    CONFIGURE_CREDENTIAL,
    FIRST_SYNC,
)
from services.integrations.connectors.service import connector_service
from shared.common.common import BadRequestError
from shared.integration_contracts.lifecycle import ConnectionState

# Deterministic, self-serve (BYOD ingestion) families.
COMMERCE_FAMILY = "shopify"
CRED_FAMILY = "stripe"
WEBHOOK_FAMILY = "webhook"


@pytest.mark.asyncio
async def test_create_tenant_integration_creates_credential_waiting_row() -> None:
    """A brand-new integration is enabled but waits on a credential first."""
    planner = ActivationPlanner()
    result = await planner.run_connect_action(
        "t-ca-create", COMMERCE_FAMILY, "create_tenant_integration"
    )
    assert result["ok"] is True
    assert result["family"] == COMMERCE_FAMILY
    assert result["action"] == "create_tenant_integration"
    # enabled, no credential yet -> the honest next step is configure_credential.
    assert result["connection_state"] == ConnectionState.CREDENTIAL_WAITING.value
    assert result["next_action"] == CONFIGURE_CREDENTIAL
    assert result["can_act"] is True

    row = await connector_service.get("t-ca-create", COMMERCE_FAMILY)
    assert row is not None
    assert row["enabled"] is True
    assert row["secret_configured"] is False


@pytest.mark.asyncio
async def test_configure_credential_stores_secret_and_advances_to_first_sync() -> None:
    """Providing the secret lands the row at initial_sync_pending -> first_sync."""
    planner = ActivationPlanner()
    created = await planner.run_connect_action(
        "t-ca-cred", COMMERCE_FAMILY, "create_tenant_integration"
    )
    assert created["next_action"] == CONFIGURE_CREDENTIAL

    configured = await planner.run_connect_action(
        "t-ca-cred",
        COMMERCE_FAMILY,
        "configure_credential",
        credential="sk_test_secret_value",
    )
    assert configured["ok"] is True
    assert configured["connection_state"] == ConnectionState.INITIAL_SYNC_PENDING.value
    assert configured["next_action"] == FIRST_SYNC
    assert configured["can_act"] is True

    row = await connector_service.get("t-ca-cred", COMMERCE_FAMILY)
    assert row["secret_configured"] is True
    # The secret must never live on the config row — only its ref is stored.
    stored = {k: v for k, v in row.items() if "secret" in k}
    assert "sk_test_secret_value" not in str(stored)


@pytest.mark.asyncio
async def test_enable_connection_reenables_disabled_credential_ready_row() -> None:
    tenant = "t-ca-enable"
    # A disabled row that already has a credential in the vault.
    await connector_service.configure(
        tenant, CRED_FAMILY, credential="sk_live_x", enabled=False, actor_id="test"
    )
    planner = ActivationPlanner()
    result = await planner.run_connect_action(
        tenant, CRED_FAMILY, "enable_connection"
    )
    assert result["ok"] is True
    assert result["connection_state"] == ConnectionState.INITIAL_SYNC_PENDING.value
    assert result["next_action"] == FIRST_SYNC
    row = await connector_service.get(tenant, CRED_FAMILY)
    assert row["enabled"] is True and row["secret_configured"] is True


@pytest.mark.asyncio
async def test_first_sync_honest_failure_returns_ok_false_not_server_error() -> None:
    """A provider that cannot pull surfaces sync_failed, never a fake step."""
    tenant = "t-ca-sync"
    planner = ActivationPlanner()
    # Create + configure a webhook connector (no provider-backed pull).
    await planner.run_connect_action(tenant, WEBHOOK_FAMILY, "create_tenant_integration")
    await planner.run_connect_action(
        tenant, WEBHOOK_FAMILY, "configure_credential", credential="whsec_test"
    )

    result = await planner.run_connect_action(tenant, WEBHOOK_FAMILY, "first_sync")
    assert result["ok"] is False
    assert result["connection_state"] == ConnectionState.SYNC_FAILED.value
    assert result["detail"], "honest failure carries a detail for the UI"

    # The durable connector row records the failure honestly (health signal that
    # the plan projection then surfaces as an attention state, no forward step).
    row = await connector_service.get(tenant, WEBHOOK_FAMILY)
    assert row["sync_status"] == "failed"
    assert row["error_count"] == 1


@pytest.mark.asyncio
async def test_unknown_action_is_client_error() -> None:
    with pytest.raises(BadRequestError):
        await ActivationPlanner().run_connect_action(
            "t-ca-bad", COMMERCE_FAMILY, "teleport"
        )


@pytest.mark.asyncio
async def test_unknown_family_is_client_error() -> None:
    with pytest.raises(BadRequestError):
        await ActivationPlanner().run_connect_action(
            "t-ca-bad", "definitely_not_a_provider", "create_tenant_integration"
        )


@pytest.mark.asyncio
async def test_non_connectable_catalog_member_is_refused() -> None:
    """Advertising surfaces stay honest: no activation connect action is offered."""
    with pytest.raises(BadRequestError):
        await ActivationPlanner().run_connect_action(
            "t-ca-ads", "google_ads", "create_tenant_integration"
        )
