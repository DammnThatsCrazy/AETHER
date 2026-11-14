"""Action integration secrets are stored under a server-built, tenant-scoped ref."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import ProvidersRepository, reset_in_memory_stores
from intelligence.intelligence import routes
from intelligence.intelligence.decision_models import ActionDispatch, ActionIntegrationConfig
from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.service import credential_service

pytestmark = pytest.mark.asyncio

OTHER_REF = "slack_bot_token:other_tenant"


class _Tenant:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"

    def require_permission(self, _permission: str) -> None:
        return None


def _request(tenant_id: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant(tenant_id)))


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    InMemoryCredentialBackend.reset()
    yield
    reset_in_memory_stores()
    InMemoryCredentialBackend.reset()


async def _seed_other_tenant_secret() -> None:
    await ProvidersRepository().upsert(
        OTHER_REF, {"api_key": "xoxb-other-tenant", "provider": "slack", "tenant_id": "other_tenant"}
    )


def _body(config: dict) -> routes.IntegrationConfigRequest:
    return routes.IntegrationConfigRequest(target_type="ticketing", name="jira", config=config)


async def _stored(config_id: str) -> dict:
    return await routes._integrations.find_by_id(config_id)


async def test_create_ignores_caller_supplied_secret_ref():
    await _seed_other_tenant_secret()
    result = await routes.create_action_integration(
        _body({"backend": "jira", "base_url": "https://jira.example", "secret_ref": OTHER_REF}),
        _request("own_tenant"),
    )
    stored = await _stored(result["data"]["config_id"])
    assert "secret_ref" not in stored["config"]
    assert "has_secret" not in result["data"]


async def test_update_ignores_caller_supplied_secret_ref():
    await _seed_other_tenant_secret()
    created = await routes.create_action_integration(
        _body({"backend": "jira"}), _request("own_tenant")
    )
    config_id = created["data"]["config_id"]
    await routes.update_action_integration(
        config_id,
        _body({"backend": "jira", "secret_ref": OTHER_REF}),
        _request("own_tenant"),
    )
    assert "secret_ref" not in (await _stored(config_id))["config"]


async def test_plaintext_secret_stored_in_tenant_credential_store_under_server_ref():
    result = await routes.create_action_integration(
        _body({"backend": "jira", "auth_secret": "own-jira-token", "api_key": "also-removed"}),
        _request("own_tenant"),
    )
    config_id = result["data"]["config_id"]
    stored = await _stored(config_id)
    expected_ref = f"action_integration:own_tenant:{config_id}"
    assert stored["config"]["secret_ref"] == expected_ref
    assert not {"api_key", "auth_secret"} & stored["config"].keys()
    assert result["data"]["has_secret"] is True
    assert await credential_service.reveal("own_tenant", expected_ref) == "own-jira-token"
    assert await credential_service.reveal("other_tenant", expected_ref) is None

    await routes.update_action_integration(
        config_id, _body({"backend": "jira", "project_key": "P"}), _request("own_tenant")
    )
    assert (await _stored(config_id))["config"]["secret_ref"] == expected_ref

    await routes.update_action_integration(
        config_id, _body({"backend": "jira", "api_key": "rotated"}), _request("own_tenant")
    )
    assert await credential_service.reveal("own_tenant", expected_ref) == "rotated"


async def test_delivery_job_secret_ref_is_server_built_and_not_overridable():
    dispatch = ActionDispatch(
        dispatch_id="d-1", tenant_id="own_tenant", action_id="a-1", decision_id="dec-1",
        recommendation_id="r-1", target_type="ticketing", config_id="cfg-1",
        created_at="2026-10-15T00:00:00+00:00",
    )
    own_ref = "action_integration:own_tenant:cfg-1"
    with_secret = ActionIntegrationConfig(
        config_id="cfg-1", tenant_id="own_tenant", target_type="ticketing", name="jira",
        config={"backend": "jira", "secret_ref": own_ref}, created_at="2026-10-15T00:00:00+00:00",
    )
    job = await routes._enqueue_action_delivery(dispatch, with_secret)
    assert job["provider_config"]["secret_ref"] == own_ref
    assert job["provider_config"]["tenant_id"] == "own_tenant"

    legacy = with_secret.model_copy(update={"config": {"backend": "jira", "secret_ref": OTHER_REF}})
    dispatch_2 = dispatch.model_copy(update={"dispatch_id": "d-2"})
    job = await routes._enqueue_action_delivery(dispatch_2, legacy)
    assert "secret_ref" not in job["provider_config"]
