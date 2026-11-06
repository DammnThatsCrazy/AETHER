"""Program C — async SDK manifest request intake.

The request path is intentionally not a publisher: these tests pin that it
records one planned ChangeSet and one stage-zero rollout, refuses without the
``plan`` capability, and never calls an SDK publish method.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from connectors.managed_integrations.activation import RuntimeActivationDecision
from ingestion.sdk_config.rcp_requests import (
    SDK_CONFIG_ENVIRONMENT_ID,
    SDK_CONFIG_REQUEST_ADVANCE_CONDITION,
    SDKManifestRequestNotFound,
    SDKManifestRequestRefused,
    SDKManifestRequestService,
)


class _Activation:
    def __init__(self, decision: RuntimeActivationDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, *, tenant_id: str, environment_id: str):
        self.calls.append((tenant_id, environment_id))
        return self.decision


class _ChangeSets:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.create_calls = 0

    async def get(self, tenant_id: str, environment_id: str, changeset_id: str):
        row = self.rows.get(changeset_id)
        if (
            row is None
            or row["tenant_id"] != tenant_id
            or row["environment_id"] != environment_id
        ):
            return None
        return row

    async def create(self, plan):
        self.create_calls += 1
        row = plan.model_dump(mode="json")
        self.rows[plan.changeset_id] = row
        return row


class _Rollouts:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.create_calls = 0

    async def get(self, *, tenant_id: str, environment_id: str, rollout_id: str):
        row = self.rows.get(rollout_id)
        if (
            row is None
            or row["tenant_id"] != tenant_id
            or row["environment_id"] != environment_id
        ):
            return None
        return row

    async def create(self, row):
        self.create_calls += 1
        payload = row.model_dump(mode="json")
        self.rows[row.rollout_id] = payload
        return payload


class _SDKConfig:
    def __init__(self, current_version: str | None = "3") -> None:
        self.current_version = current_version
        self.published = False

    async def get_rollout_status(self, tenant_id: str):
        return {"tenant_id": tenant_id, "current_version": self.current_version}

    async def publish_manifest(self, **kwargs):  # pragma: no cover - must not run
        self.published = True
        raise AssertionError("request intake must not publish a manifest")


class _SDKConfigError:
    async def get_rollout_status(self, tenant_id: str):
        raise RuntimeError("manifest store unavailable")


def _decision(state: str, capabilities: set[str]) -> RuntimeActivationDecision:
    return RuntimeActivationDecision(
        state=state,
        capabilities=frozenset(capabilities),
        blockers=(),
        global_state=state,
    )


def _service(*, state: str = "plan", sdk_config=None):
    change_sets = _ChangeSets()
    rollouts = _Rollouts()
    sdk = sdk_config or _SDKConfig()
    service = SDKManifestRequestService(
        activation_resolver=_Activation(
            _decision(state, {"observe", "detect", "plan"})
        ),
        change_sets=change_sets,
        rollouts=rollouts,
        sdk_config=sdk,
    )
    return service, change_sets, rollouts, sdk


async def _request(service, *, idempotency_key=None, schema_version="7.0.0"):
    return await service.request_manifest_change(
        tenant_id="tenant-a",
        initiator="user-1",
        min_sdk_version="6.0.0",
        schema_version=schema_version,
        features={"analytics": True},
        endpoints={"ingest": "https://ingest.aether.xyz"},
        flags={"heartbeat_interval_seconds": 60},
        reason="requested by tenant admin",
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_request_records_plan_and_stage_zero_rollout_without_publishing():
    service, change_sets, rollouts, sdk = _service()

    result = await _request(service)

    assert result["status"] == "planned"
    assert result["execution_state"] == "not_started"
    assert result["manifest_published"] is False
    assert result["activation_state"] == "plan"
    assert result["desired_revision"].startswith("sdkcfg_")
    assert result["observed_revision"] == "sdkcfg:3"
    assert result["risk_class"] == "R1"
    assert sdk.published is False

    assert change_sets.create_calls == 1
    changeset = next(iter(change_sets.rows.values()))
    assert changeset["environment_id"] == SDK_CONFIG_ENVIRONMENT_ID
    assert changeset["integration_scope"] == ["sdk_config:tenant-a"]
    assert changeset["changes"][0]["action"] == "remote_manifest_change"
    assert changeset["changes"][0]["params"]["tenant_id"] == "tenant-a"
    assert changeset["changes"][0]["params"]["features"] == {"analytics": True}

    assert rollouts.create_calls == 1
    rollout = next(iter(rollouts.rows.values()))
    assert rollout["changeset_ref"] == result["changeset_id"]
    assert rollout["artifact_kind"] == "runtime_config"
    assert rollout["current_stage"] == "olympus_internal"
    assert rollout["percentage"] == 0.0
    assert rollout["advance_conditions"] == [SDK_CONFIG_REQUEST_ADVANCE_CONDITION]


@pytest.mark.asyncio
async def test_request_refused_when_activation_lacks_plan():
    service, change_sets, rollouts, _ = _service(state="detect")
    # The helper always grants plan; replace with the detect decision only.
    service._activation = _Activation(
        _decision("detect", {"observe", "detect"})
    )

    with pytest.raises(SDKManifestRequestRefused) as exc:
        await _request(service)

    assert exc.value.reason == "activation_insufficient"
    assert change_sets.create_calls == 0
    assert rollouts.create_calls == 0


@pytest.mark.asyncio
async def test_idempotency_key_reuses_one_plan_and_rollout():
    service, change_sets, rollouts, _ = _service()

    first = await _request(service, idempotency_key="request-1")
    second = await _request(service, idempotency_key="request-1")

    assert first["changeset_id"] == second["changeset_id"]
    assert first["rollout_id"] == second["rollout_id"]
    assert change_sets.create_calls == 1
    assert rollouts.create_calls == 1


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_different_payload_is_refused():
    service, change_sets, rollouts, _ = _service()

    await _request(service, idempotency_key="request-1")
    with pytest.raises(SDKManifestRequestRefused) as exc:
        await _request(service, idempotency_key="request-1", schema_version="8.0.0")

    assert exc.value.reason == "idempotency_key_reused"
    assert change_sets.create_calls == 1
    assert rollouts.create_calls == 1


@pytest.mark.asyncio
async def test_observed_state_failure_fails_closed():
    service, change_sets, rollouts, _ = _service(sdk_config=_SDKConfigError())

    with pytest.raises(SDKManifestRequestRefused) as exc:
        await _request(service)

    assert exc.value.reason == "observed_state_unavailable"
    assert change_sets.create_calls == 0
    assert rollouts.create_calls == 0


@pytest.mark.asyncio
async def test_get_request_is_tenant_scoped_and_absent_fails_closed():
    service, _, _, _ = _service()
    created = await _request(service)

    fetched = await service.get_request(
        tenant_id="tenant-a", request_id=created["request_id"]
    )
    assert fetched["changeset_id"] == created["changeset_id"]
    assert fetched["rollout_stage"] == "olympus_internal"

    with pytest.raises(SDKManifestRequestNotFound):
        await service.get_request(tenant_id="tenant-b", request_id=created["request_id"])


def _route_request(path: str):
    class _Caller:
        tenant_id = "tenant-a"
        user_id = "user-1"

        def require_permission(self, permission: str) -> None:
            assert permission == "admin"

    return SimpleNamespace(
        state=SimpleNamespace(tenant=_Caller(), request_id="req-1"),
        headers={},
        url=SimpleNamespace(path=path),
    )


@pytest.mark.asyncio
async def test_direct_manifest_publish_is_refused_when_rcp_is_enabled(monkeypatch):
    from ingestion.sdk_config import routes

    request = _route_request("/v1/config/sdk/manifest")
    monkeypatch.setattr(routes.rcp_flags, "enabled", lambda: True)

    with pytest.raises(routes.ConflictError):
        await routes.publish_manifest(routes.PublishManifestRequest(), request)


@pytest.mark.asyncio
async def test_direct_manifest_publish_remains_legacy_when_rcp_is_off(monkeypatch):
    from ingestion.sdk_config import routes

    class _LegacyService:
        async def publish_manifest(self, **kwargs):
            assert kwargs["tenant_id"] == "tenant-a"
            assert kwargs["rollout_percentage"] == 25
            return SimpleNamespace(
                manifest_version="9",
                rollout_percentage=25,
                signature="x" * 86,
                published_at="2026-11-06T00:00:00Z",
            )

    request = _route_request("/v1/config/sdk/manifest")
    monkeypatch.setattr(routes.rcp_flags, "enabled", lambda: False)
    monkeypatch.setattr(routes, "get_sdk_config_service", _LegacyService)

    result = await routes.publish_manifest(
        routes.PublishManifestRequest(rollout_percentage=25), request
    )

    assert result["data"]["manifest_version"] == "9"
    assert result["data"]["rollout_percentage"] == 25


@pytest.mark.asyncio
async def test_request_route_is_unavailable_when_rcp_is_off(monkeypatch):
    from ingestion.sdk_config import routes

    request = _route_request("/v1/config/sdk/manifest/requests")
    monkeypatch.setattr(routes.rcp_flags, "enabled", lambda: False)

    with pytest.raises(routes.ServiceUnavailableError):
        await routes.request_manifest_publish(
            routes.RequestManifestPublishRequest(), request
        )
