"""WS-2 ad-source auto-link orchestration honesty tests (campaign layer).

Covers the additive ``services/campaign/ad_source_links.py`` orchestration over
the connector store: idempotent connect (one active source per family),
canonical platform resolution, complete-credential enforcement, secret
redaction in every read model, disable/enable with the one-active-per-family
guard, and account rotation that archives the old source and carries the
credentials forward.
"""
from __future__ import annotations

from typing import Any

import pytest

from services.measurement.repositories.measurement_connector_repo import (
    MeasurementConnectorRepository,
    _reset_local_connectors,
)
from services.campaign import ad_source_links as L
from services.measurement.connectors.ad_accounts import AD_ACCOUNT_FAMILIES

GOOGLE_FULL_CONFIG: dict[str, str] = {
    "customer_id": "123-456",
    "developer_token": "dev-token",
    "client_id": "client-id",
    "client_secret": "client-secret",
    "refresh_token": "rt-secret",
}


@pytest.fixture(autouse=True)
def reset_local_store(monkeypatch: pytest.MonkeyPatch):
    async def no_pool() -> None:
        return None

    monkeypatch.setattr(
        "services.measurement.repositories.measurement_connector_repo.get_pool",
        no_pool,
    )
    _reset_local_connectors()
    yield
    _reset_local_connectors()


async def _connect_google(repo: MeasurementConnectorRepository, tenant_id: str, account: str = "123-456") -> str:
    config = dict(GOOGLE_FULL_CONFIG)
    config["customer_id"] = account
    result = await L.connect_ad_source(
        repo, tenant_id=tenant_id, platform="google_ads", name="Google", config=config
    )
    assert result["already_connected"] is False
    connector_id = result["source"]["connector_id"]
    assert connector_id
    return connector_id


# ── Canonical platform resolution ───────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("google_ads", "google_ads"),
        ("adwords", "google_ads"),
        ("facebook", "meta_ads"),
        ("instagram", "meta_ads"),
        ("twitter_ads", "x_ads"),
        ("bing", "microsoft_ads"),
        ("tiktok", "tiktok_ads"),
    ],
)
def test_resolve_ad_family_maps_brand_and_boundary_aliases(raw: str, expected: str) -> None:
    assert L.resolve_ad_family(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["snapchat_ads", "pinterest_ads", "google_analytics", "email", "", None, "  "],
)
def test_resolve_ad_family_rejects_unbacked_non_ad(raw: str | None) -> None:
    assert L.resolve_ad_family(raw) is None


# ── Idempotent connect ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_is_idempotent_per_active_family() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-idem"

    first = await _connect_google(repo, tenant_id)
    # A brand alias for the same family must resolve to the same active source.
    second = await L.connect_ad_source(
        repo, tenant_id=tenant_id, platform="adwords", config=GOOGLE_FULL_CONFIG
    )
    assert second["already_connected"] is True
    assert second["source"]["connector_id"] == first

    active = await repo.list_by_tenant(tenant_id, status="active", connector_type="google_ads")
    assert len(active) == 1
    assert active[0]["connector_id"] == first


@pytest.mark.asyncio
async def test_connect_stores_canonical_family_for_boundary_alias() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-twitter"
    result = await L.connect_ad_source(
        repo,
        tenant_id=tenant_id,
        platform="twitter_ads",
        config={"access_token": "tok", "account_id": "x-1"},
    )
    assert result["platform"] == "x_ads"
    assert result["source"]["platform"] == "x_ads"
    assert result["source"]["account_id"] == "x-1"


@pytest.mark.asyncio
async def test_connect_rejects_incomplete_credential_set() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-incomplete"
    with pytest.raises(ValueError, match="Incomplete meta_ads credential set"):
        await L.connect_ad_source(
            repo, tenant_id=tenant_id, platform="meta_ads", config={"access_token": "tok"}
        )
    # A blank account id is also an incomplete single-account source.
    with pytest.raises(ValueError, match="Incomplete meta_ads credential set"):
        await L.connect_ad_source(
            repo, tenant_id=tenant_id, platform="meta_ads",
            config={"access_token": "tok", "ad_account_id": ""},
        )
    assert await repo.list_for_tenant(tenant_id) == []


@pytest.mark.asyncio
async def test_connect_rejects_unbacked_platforms() -> None:
    repo = MeasurementConnectorRepository()
    for platform in ("snapchat_ads", "google_analytics", "not-a-platform"):
        with pytest.raises(ValueError, match="not a measurement-backed ad family"):
            await L.connect_ad_source(
                repo, tenant_id="tenant-bad", platform=platform, config=GOOGLE_FULL_CONFIG
            )
    assert await repo.list_for_tenant("tenant-bad") == []


# ── Overview / read-model redaction ─────────────────────────────────────

@pytest.mark.asyncio
async def test_overview_never_leaks_config_or_secret_values() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-redact"
    await _connect_google(repo, tenant_id)

    overview = await L.overview_sources(repo, tenant_id=tenant_id)
    assert len(overview["items"]) == 1
    assert overview["counts"] == {"total": 1, "active": 1, "disabled": 0, "ad_families": 1}
    item = overview["items"][0]
    assert "config" not in item
    assert "cursor_state" not in item
    assert item["secret_configured"] is True
    assert item["missing_secrets"] == []
    assert item["secrets_total"] == 3
    assert item["account_id"] == "123-456"

    # The stored secret value must not appear anywhere in the projected JSON.
    dumped = str(overview)
    assert "client-secret" not in dumped
    assert "dev-token" not in dumped
    assert "rt-secret" not in dumped


@pytest.mark.asyncio
async def test_project_source_handles_non_ad_rows_without_fabrication() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-nonad"
    await repo.create(tenant_id=tenant_id, connector_type="file_import", name="Manual upload")

    overview = await L.overview_sources(repo, tenant_id=tenant_id)
    item = overview["items"][0]
    assert item["is_ad_platform"] is False
    assert item["account_field"] is None
    assert item["account_id"] is None
    assert item["secret_configured"] is None
    assert item["platform"] == "file_import"
    assert "config" not in item


@pytest.mark.asyncio
async def test_disabled_rows_stay_visible_as_history() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-history"
    connector_id = await _connect_google(repo, tenant_id)
    await L.set_source_enabled(repo, tenant_id=tenant_id, connector_id=connector_id, enabled=False)

    overview = await L.overview_sources(repo, tenant_id=tenant_id)
    assert overview["counts"] == {"total": 1, "active": 0, "disabled": 1, "ad_families": 1}
    assert overview["items"][0]["enabled"] is False


# ── Disable / enable ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enable_refused_when_another_active_row_exists_for_family() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-guard"
    first = await _connect_google(repo, tenant_id)
    await L.set_source_enabled(repo, tenant_id=tenant_id, connector_id=first, enabled=False)
    second = await _connect_google(repo, tenant_id, account="987-654")

    with pytest.raises(ValueError, match="Cannot enable"):
        await L.set_source_enabled(repo, tenant_id=tenant_id, connector_id=first, enabled=True)

    # Both rows remain; exactly one is active.
    rows = await repo.list_by_tenant(tenant_id)
    active = [r for r in rows if r.get("status") == "active"]
    assert len(active) == 1
    assert active[0]["connector_id"] == second


@pytest.mark.asyncio
async def test_disable_enable_is_unchanged_idempotent() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-toggle"
    connector_id = await _connect_google(repo, tenant_id)
    disabled = await L.set_source_enabled(repo, tenant_id=tenant_id, connector_id=connector_id, enabled=False)
    assert disabled["status"] == "disabled"
    unchanged = await L.set_source_enabled(repo, tenant_id=tenant_id, connector_id=connector_id, enabled=False)
    assert unchanged["unchanged"] is True
    reenabled = await L.set_source_enabled(repo, tenant_id=tenant_id, connector_id=connector_id, enabled=True)
    assert reenabled["status"] == "active"


# ── Account selection (rotation) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_account_rotation_archives_old_and_carries_secrets_forward() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-rotate"
    old_id = await _connect_google(repo, tenant_id)

    rotated = await L.set_source_account(
        repo, tenant_id=tenant_id, connector_id=old_id, account_id="NEW-999"
    )
    assert rotated["account_rotated"] is True
    assert rotated["account_id"] == "NEW-999"
    new_id = rotated["connector_id"]
    assert new_id != old_id

    # Old row archived (disabled), new row active with the same credentials.
    old_row = await repo.get(tenant_id, old_id)
    assert old_row["status"] == "disabled"
    new_row = await repo.get(tenant_id, new_id)
    assert new_row["status"] == "active"
    assert new_row["config"]["customer_id"] == "NEW-999"
    assert new_row["config"]["refresh_token"] == "rt-secret"
    assert new_row["config"]["developer_token"] == "dev-token"

    overview = await L.overview_sources(repo, tenant_id=tenant_id)
    assert overview["counts"]["active"] == 1
    active_item = next(i for i in overview["items"] if i["enabled"])
    assert active_item["connector_id"] == new_id
    assert active_item["account_id"] == "NEW-999"


@pytest.mark.asyncio
async def test_account_selection_same_account_is_noop() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-sameacc"
    connector_id = await _connect_google(repo, tenant_id)
    result = await L.set_source_account(
        repo, tenant_id=tenant_id, connector_id=connector_id, account_id="123-456"
    )
    assert result["unchanged"] is True
    assert result["connector_id"] == connector_id
    rows = await repo.list_by_tenant(tenant_id)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_account_selection_rejects_missing_or_non_ad_source() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-badacc"
    with pytest.raises(ValueError, match="not found"):
        await L.set_source_account(repo, tenant_id=tenant_id, connector_id="nope", account_id="x")
    non_ad = await repo.create(tenant_id=tenant_id, connector_type="file_import", name="Upload")
    with pytest.raises(ValueError, match="not an ad-platform source"):
        await L.set_source_account(
            repo, tenant_id=tenant_id, connector_id=non_ad["connector_id"], account_id="x"
        )


# ── Ad connect options ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ad_connect_options_shape_and_connect_state() -> None:
    from shared.integration_contracts.catalog import manifest_from_ad_platform

    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-options"
    await _connect_google(repo, tenant_id)

    options = await L.ad_connect_options(repo, tenant_id=tenant_id)
    assert [o["family"] for o in options] == list(AD_ACCOUNT_FAMILIES)

    for opt in options:
        family = opt["family"]
        assert opt["account_discovery"] is False
        schema = manifest_from_ad_platform(family).authentication.credential_schema
        expected = {(f.name, f.type, f.secret, f.required) for f in schema}
        actual = {
            (f["name"], f["type"], f["secret"], f["required"]) for f in opt["credential_fields"]
        }
        assert actual == expected, family

    google = next(o for o in options if o["family"] == "google_ads")
    assert google["already_connected"] is True
    meta = next(o for o in options if o["family"] == "meta_ads")
    assert meta["already_connected"] is False
