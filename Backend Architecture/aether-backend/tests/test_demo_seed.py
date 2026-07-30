from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from repositories.repos import BaseRepository, reset_in_memory_stores
from services.demo_seed.dataset import v1_manifest
from services.demo_seed.policy import SeedPolicyError
from services.demo_seed import routes as seed_routes
from services.demo_seed.service import DemoSeedService, SeedSafetyError
from services.demo_seed.startup import maybe_seed_demo_on_start

pytestmark = pytest.mark.asyncio

TENANT = "tenant-demo-test"
NAMESPACE = "test-demo-v1"
ANCHOR = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_memory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AETHER_STAGING_DEMO_ENABLED", raising=False)
    monkeypatch.delenv("AETHER_STAGING_DEMO_TENANT_ALLOWLIST", raising=False)
    reset_in_memory_stores()


def service(*run_ids: str, environment: str = "test") -> DemoSeedService:
    values = iter(run_ids or ("seed-run-1",))
    return DemoSeedService(
        environment=environment,
        clock=lambda: ANCHOR,
        run_id_factory=lambda: next(values),
    )


async def test_manifest_is_deterministic_and_uses_stable_ids():
    first = v1_manifest(NAMESPACE)
    second = v1_manifest(NAMESPACE)
    assert first.checksum == second.checksum
    assert [record.record_id for record in first.records] == [
        record.record_id for record in second.records
    ]
    assert len({record.record_id for record in first.records}) == len(first.records)
    assert all(record.offset_seconds <= 0 for record in first.records)


async def test_clean_install_has_zero_seed_runs_and_zero_demo_records():
    manager = service("unused")
    status = await manager.status(tenant_id=TENANT, namespace=NAMESPACE)
    assert status["seeded"] is False
    assert status["is_demo_tenant"] is False
    assert status["run_count"] == 0
    assert status["owned_record_count"] == 0
    assert status["latest_run"] is None
    for repository in manager.repositories.values():
        assert await repository.count() == 0


async def test_seed_is_idempotent_api_visible_and_verifiable():
    manager = service("seed-run-1", "seed-run-2")
    first = await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)
    second = await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)

    assert sum(first.inserted.values()) == len(v1_manifest(NAMESPACE).records)
    assert sum(second.inserted.values()) == 0
    assert sum(second.skipped.values()) == len(v1_manifest(NAMESPACE).records)
    assert (await manager.verify(tenant_id=TENANT, namespace=NAMESPACE))["ok"] is True
    status = await manager.status(tenant_id=TENANT, namespace=NAMESPACE)
    assert status["run_count"] == 2
    assert status["seeded"] is True
    assert status["is_demo_tenant"] is True
    assert status["data_origin"] == "synthetic_seed"
    assert status["latest_run"]["dataset_version"] == "v1"
    assert status["latest_run"]["inserted_counts"] == {}
    assert sum(status["latest_run"]["skipped_counts"].values()) == len(
        v1_manifest(NAMESPACE).records
    )

    entities = await manager.repositories["entities"].find_many(
        filters={"tenant_id": TENANT},
    )
    assert len(entities) == 1
    assert entities[0]["data_origin"] == "synthetic_seed"
    assert entities[0]["seed_provenance"]["demo_tenant_id"] == TENANT
    assert entities[0]["observed_at"] == "2026-07-25T10:00:00+00:00"

    quality = await manager.repositories["data_quality_scores"].find_by_id(
        f"tenant:{TENANT}",
    )
    assert quality["availability"] == "available"
    assert quality["calculated_at"] == "2026-07-25T11:47:30+00:00"
    imports = await manager.repositories["import_sessions"].find_many(
        filters={"tenant_id": TENANT},
    )
    assert [item["status"] for item in imports] == ["validated"]
    approval = (await manager.repositories["commerce_approvals"].find_many(
        filters={"tenant_id": TENANT},
    ))[0]
    settlement = (await manager.repositories["commerce_settlements"].find_many(
        filters={"tenant_id": TENANT},
    ))[0]
    entitlement = (await manager.repositories["commerce_entitlements"].find_many(
        filters={"tenant_id": TENANT},
    ))[0]
    assert settlement["approval_id"] == approval["approval_id"]
    assert entitlement["settlement_id"] == settlement["settlement_id"]
    assert entitlement["expires_at"] == "2026-07-26T12:00:00+00:00"

    for repository in manager.repositories.values():
        for row in await repository.find_many(filters={"tenant_id": TENANT}, limit=100):
            assert row["data_origin"] == "synthetic_seed"
            assert row["seed_provenance"]["source_domain"]


async def test_reset_deletes_only_owned_records_and_emits_audit():
    manager = service("seed-run", "reset-audit")
    await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)
    control = BaseRepository("entities")
    await control.insert("control-record", {
        "tenant_id": TENANT,
        "entity_id": "control-record",
        "display_name": "Real control record",
    })

    with pytest.raises(SeedSafetyError, match="confirmation"):
        await manager.reset(
            tenant_id=TENANT,
            namespace=NAMESPACE,
            confirmation="yes",
        )

    result = await manager.reset(
        tenant_id=TENANT,
        namespace=NAMESPACE,
        confirmation=f"RESET {TENANT} {NAMESPACE}",
    )
    assert result["cross_tenant_records_removed"] == 0
    assert await control.find_by_id("control-record") is not None
    assert (await manager.verify(tenant_id=TENANT, namespace=NAMESPACE))["ok"] is False
    audits = await manager.reset_audit.find_many(filters={"tenant_id": TENANT})
    assert len(audits) == 1
    assert audits[0]["action"] == "demo_seed_reset"


async def test_tenant_ids_are_isolated_and_reset_cannot_cross_tenants():
    manager = service("seed-a", "seed-b", "audit-a")
    other_tenant = "tenant-control"
    await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)
    await manager.seed(tenant_id=other_tenant, namespace=NAMESPACE)

    first_ids = {
        row["id"]
        for row in await manager.repositories["entities"].find_many(
            filters={"tenant_id": TENANT},
        )
    }
    other_ids = {
        row["id"]
        for row in await manager.repositories["entities"].find_many(
            filters={"tenant_id": other_tenant},
        )
    }
    assert first_ids.isdisjoint(other_ids)

    await manager.reset(
        tenant_id=TENANT,
        namespace=NAMESPACE,
        confirmation=f"RESET {TENANT} {NAMESPACE}",
    )
    assert await manager.repositories["entities"].count(
        filters={"tenant_id": other_tenant},
    ) == 1
    assert (await manager.verify(
        tenant_id=other_tenant, namespace=NAMESPACE,
    ))["ok"] is True


async def test_production_refuses_seed_and_reset():
    manager = service("unused", environment="production")
    with pytest.raises(SeedPolicyError, match="disabled in production"):
        await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)
    with pytest.raises(SeedPolicyError, match="disabled in production"):
        await manager.reset(
            tenant_id=TENANT,
            namespace=NAMESPACE,
            confirmation=f"RESET {TENANT} {NAMESPACE}",
        )


async def test_staging_requires_enabled_allowlisted_tenant(monkeypatch: pytest.MonkeyPatch):
    manager = service("seed-staging", environment="staging")
    with pytest.raises(SeedPolicyError, match="allowlisted"):
        await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)

    monkeypatch.setenv("AETHER_STAGING_DEMO_ENABLED", "true")
    monkeypatch.setenv("AETHER_STAGING_DEMO_TENANT_ALLOWLIST", TENANT)
    result = await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)
    assert result.status == "completed"


async def test_missing_environment_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AETHER_ENV", raising=False)
    with pytest.raises(SeedPolicyError, match="explicitly configured"):
        DemoSeedService()


async def test_normal_startup_never_seeds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AETHER_DEMO_SEED_ON_START", raising=False)
    app = SimpleNamespace(state=SimpleNamespace())
    assert await maybe_seed_demo_on_start(app, environment="local") is False
    assert not hasattr(app.state, "demo_seed_result")


async def test_startup_seed_refuses_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AETHER_DEMO_SEED_ON_START", "true")
    monkeypatch.setenv("AETHER_DEMO_TENANT_ID", TENANT)
    monkeypatch.setenv("AETHER_DEMO_SEED_NAMESPACE", NAMESPACE)
    app = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(RuntimeError, match="only in local/test"):
        await maybe_seed_demo_on_start(app, environment="production")


async def test_existing_non_seeded_stable_id_is_never_claimed_or_overwritten():
    manager = service("seed-run")
    manifest = v1_manifest(NAMESPACE)
    entity_template = next(record for record in manifest.records if record.repository == "entities")
    # Ask the service for a first seed in a different tenant to learn nothing
    # about the target ID; the collision is created using its deterministic
    # mapping via a dry first seed followed by ownership removal.
    await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)
    owners = await manager.ownership.find_many(
        filters={"tenant_id": TENANT, "seed_namespace": NAMESPACE},
        limit=100,
    )
    owner = next(item for item in owners if item["repository"] == "entities")
    await manager.ownership.delete(owner["id"])
    record_id = owner["record_id"]
    await manager.repositories["entities"].update(record_id, {
        "data_origin": "customer",
        "seed_provenance": {},
    })

    second = service("seed-run-2")
    with pytest.raises(SeedSafetyError, match="refusing to overwrite"):
        await second.seed(tenant_id=TENANT, namespace=NAMESPACE)
    stored = await second.repositories["entities"].find_by_id(record_id)
    assert stored["data_origin"] == "customer"


def _request(*, tenant=None, operator=None) -> Request:
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/v1/demo-seed/status",
        "headers": [],
        "client": ("127.0.0.1", 10000),
    })
    if tenant is not None:
        request.state.tenant = tenant
    if operator is not None:
        request.state.operator = operator
    return request


class _Tenant:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.permissions: list[str] = []

    def require_permission(self, permission: str) -> None:
        self.permissions.append(permission)


async def test_status_contract_uses_api_envelope_and_tenant_auth():
    manager = service("seed-route")
    await manager.seed(tenant_id=TENANT, namespace=NAMESPACE)
    router = seed_routes.build_demo_seed_status_router()
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/status"))
    tenant = _Tenant(TENANT)

    response = await endpoint(
        tenant_id=TENANT,
        namespace=NAMESPACE,
        request=_request(tenant=tenant),
    )
    assert response["data"]["seeded"] is True
    assert response["data"]["latest_run"]["dataset_version"] == "v1"
    assert tenant.permissions == ["read"]

    response_for_current_tenant = await endpoint(
        tenant_id=None,
        namespace=NAMESPACE,
        request=_request(tenant=tenant),
    )
    assert response_for_current_tenant["data"]["tenant_id"] == TENANT

    with pytest.raises(HTTPException) as cross_tenant:
        await endpoint(
            tenant_id="another-tenant",
            namespace=NAMESPACE,
            request=_request(tenant=tenant),
        )
    assert cross_tenant.value.status_code == 403


async def test_status_route_does_not_trust_arbitrary_operator_state(
    monkeypatch: pytest.MonkeyPatch,
):
    router = seed_routes.build_demo_seed_status_router()
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/status"))
    request = _request(operator=SimpleNamespace(operator_id="forged"))
    monkeypatch.setattr(
        seed_routes,
        "require_kyber_operator",
        lambda _request: (_ for _ in ()).throw(RuntimeError("not a real operator")),
    )
    with pytest.raises(HTTPException) as denied:
        await endpoint(tenant_id=TENANT, namespace=NAMESPACE, request=request)
    assert denied.value.status_code == 401

    called: list[bool] = []
    monkeypatch.setattr(
        seed_routes,
        "require_kyber_operator",
        lambda _request: called.append(True),
    )
    response = await endpoint(tenant_id=TENANT, namespace=NAMESPACE, request=request)
    assert response["data"]["tenant_id"] == TENANT
    assert called == [True]
