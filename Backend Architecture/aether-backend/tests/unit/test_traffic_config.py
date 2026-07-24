"""Per-tenant traffic configuration CRUD + validation (spec §15.4)."""

from __future__ import annotations

import pytest

from services.traffic import config as config_module
from services.traffic.config import (
    TenantTrafficConfigRepository,
    TrafficConfig,
    ConfigValidationError,
    validate_config,
)
from services.traffic import routes as traffic_routes


@pytest.fixture(autouse=True)
def _clean_config_store():
    config_module._reset_local_config()
    yield
    config_module._reset_local_config()


def _tenant(tenant_id="tenant-a", role="ADMIN"):
    from types import SimpleNamespace
    return SimpleNamespace(tenant_id=tenant_id, role=role, has_permission=lambda p: False)


def test_validate_rejects_unknown_field() -> None:
    with pytest.raises(ConfigValidationError):
        validate_config("tenant-a", {"not_a_field": 1})


def test_validate_rejects_non_canonical_alias() -> None:
    with pytest.raises(ConfigValidationError) as exc:
        validate_config("tenant-a", {"custom_source_aliases": {"myad": "totally_made_up"}})
    assert "canonical source_class" in str(exc.value)


def test_validate_accepts_canonical_alias() -> None:
    cfg = validate_config("tenant-a", {"custom_source_aliases": {"housead": "paid_social"}})
    assert cfg.custom_source_aliases == {"housead": "paid_social"}


def test_validate_policy_enums() -> None:
    with pytest.raises(ConfigValidationError):
        validate_config("tenant-a", {"direct_traffic_policy": "invent"})
    cfg = validate_config("tenant-a", {"direct_traffic_policy": "suppress"})
    assert cfg.direct_traffic_policy == "suppress"


def test_validate_attribution_expiration_bounds() -> None:
    with pytest.raises(ConfigValidationError):
        validate_config("tenant-a", {"attribution_expiration_days": 0})
    with pytest.raises(ConfigValidationError):
        validate_config("tenant-a", {"attribution_expiration_days": 99999})
    cfg = validate_config("tenant-a", {"attribution_expiration_days": 14})
    assert cfg.attribution_expiration_days == 14


def test_destination_allowlist_matching() -> None:
    cfg = TrafficConfig(tenant_id="t", destination_allowlist=["example.com"])
    assert cfg.allows_destination("https://example.com/path") is True
    assert cfg.allows_destination("https://app.example.com/x") is True
    assert cfg.allows_destination("https://evil.test/x") is False
    # Empty allowlist is permissive (v1 default).
    assert TrafficConfig(tenant_id="t").allows_destination("https://anywhere.test") is True


@pytest.mark.asyncio
async def test_repo_roundtrip_and_defaults() -> None:
    repo = TenantTrafficConfigRepository()
    # Unset tenant returns defaults.
    default = await repo.get("tenant-a")
    assert default.interaction_tracking_policy == "standard"
    assert default.custom_source_aliases == {}

    cfg = validate_config("tenant-a", {
        "destination_allowlist": ["example.com"],
        "custom_source_aliases": {"housead": "display"},
    })
    await repo.upsert(cfg)
    loaded = await repo.get("tenant-a")
    assert loaded.destination_allowlist == ["example.com"]
    assert loaded.custom_source_aliases == {"housead": "display"}

    assert await repo.delete("tenant-a") is True
    assert (await repo.get("tenant-a")).destination_allowlist == []


@pytest.mark.asyncio
async def test_config_is_tenant_scoped() -> None:
    repo = TenantTrafficConfigRepository()
    await repo.upsert(validate_config("tenant-a", {"placement_taxonomy": ["hero"]}))
    await repo.upsert(validate_config("tenant-b", {"placement_taxonomy": ["footer"]}))
    assert (await repo.get("tenant-a")).placement_taxonomy == ["hero"]
    assert (await repo.get("tenant-b")).placement_taxonomy == ["footer"]


@pytest.mark.asyncio
async def test_crud_routes_end_to_end() -> None:
    tenant = _tenant()
    # PUT
    put_resp = await traffic_routes.put_traffic_config(
        {"source_link_domains": ["go.example.com"], "url_sanitization_policy": "strict"},
        tenant=tenant,
    )
    assert put_resp["data"]["source_link_domains"] == ["go.example.com"]
    assert put_resp["data"]["url_sanitization_policy"] == "strict"
    # GET
    get_resp = await traffic_routes.get_traffic_config(tenant=tenant)
    assert get_resp["data"]["source_link_domains"] == ["go.example.com"]
    # DELETE
    del_resp = await traffic_routes.delete_traffic_config(tenant=tenant)
    assert del_resp["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_put_route_rejects_invalid_config() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await traffic_routes.put_traffic_config(
            {"custom_source_aliases": {"x": "nonsense"}}, tenant=_tenant()
        )
    assert exc.value.status_code == 422
