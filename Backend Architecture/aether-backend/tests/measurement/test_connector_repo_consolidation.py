"""Connector repository consolidation (Item C).

Two repositories used to target ``measurement_connectors`` with independent
in-memory local-mode stores: the old ``ConnectorRepository`` (keyed by
``connector_id`` only, used by the kyber/quality read paths) and the new
``MeasurementConnectorRepository`` (keyed ``"tenant_id:connector_id"``, used
by the campaign-sources connect path). A source connected through the new
repo was invisible to the old repo's readers — a connector that visibly
existed to one half of the system and silently did not exist to the other.

The fix ports the old repo's read/write surface (``set_status``,
``update_cursor``, ``record_sync``, filtered ``list_by_tenant``) onto
``MeasurementConnectorRepository`` and repoints every former
``ConnectorRepository`` call site at it, so there is exactly one store.

These tests exercise the repository directly in local (in-memory) mode —
the same technique used by the sibling
``tests/measurement/test_touchpoint_persist.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.measurement.repositories.measurement_connector_repo import (
    MeasurementConnectorRepository,
    _reset_local_connectors,
)


@pytest.fixture(autouse=True)
def reset_local_store(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    # Force the in-memory branch regardless of the ambient AETHER_ENV/
    # DATABASE_URL, so this file is hermetic even outside AETHER_ENV=local.
    monkeypatch.setattr(
        "services.measurement.repositories.measurement_connector_repo.get_pool",
        no_pool,
    )
    _reset_local_connectors()
    yield
    _reset_local_connectors()


@pytest.mark.asyncio
async def test_connector_created_via_create_is_visible_to_list_and_get() -> None:
    """A source connected through the campaign-sources path (``create``) must
    be visible to the kyber/quality read paths (``list_by_tenant`` / ``get``)
    against the *same* repository instance — proving there is now a single
    store, not two independent ones."""
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-consolidation"

    created = await repo.create(
        tenant_id=tenant_id, connector_type="google_ads", name="GAds",
    )
    connector_id = created["connector_id"]
    assert connector_id

    # Visible via get() — the kyber restart/backfill read path.
    fetched = await repo.get(tenant_id, connector_id)
    assert fetched is not None
    assert fetched["connector_id"] == connector_id

    # Visible via list_by_tenant() — the kyber overview / quality read path.
    listed = await repo.list_by_tenant(tenant_id)
    ids = [c["connector_id"] for c in listed]
    assert connector_id in ids


@pytest.mark.asyncio
async def test_connector_created_via_separate_repo_instance_is_still_visible() -> None:
    """Simulates the real defect scenario: one call site (campaign-sources
    routes) using one ``MeasurementConnectorRepository()`` instance to create
    a connector, and another call site (kyber/quality routes) using a
    *different* instance to read it. Because the store is module-level, both
    instances share it — the reader must see the writer's connector."""
    writer = MeasurementConnectorRepository()
    reader = MeasurementConnectorRepository()
    tenant_id = "tenant-cross-instance"

    created = await writer.create(
        tenant_id=tenant_id, connector_type="meta_ads", name="Meta",
    )
    connector_id = created["connector_id"]

    listed = await reader.list_by_tenant(tenant_id)
    ids = [c["connector_id"] for c in listed]
    assert connector_id in ids

    fetched = await reader.get(tenant_id, connector_id)
    assert fetched is not None
    assert fetched["connector_id"] == connector_id


@pytest.mark.asyncio
async def test_list_by_tenant_is_tenant_scoped() -> None:
    """The tenant-namespaced key ("tenant_id:connector_id") must isolate
    tenants — the property the old ConnectorRepository (keyed by
    connector_id alone) did not guarantee."""
    repo = MeasurementConnectorRepository()
    created_a = await repo.create(tenant_id="tenant-a", connector_type="google_ads")
    await repo.create(tenant_id="tenant-b", connector_type="google_ads")

    listed_a = await repo.list_by_tenant("tenant-a")
    ids_a = [c["connector_id"] for c in listed_a]
    assert created_a["connector_id"] in ids_a
    assert len(listed_a) == 1

    # tenant-a's reader must never see tenant-b's connector via get() either.
    cross = await repo.get("tenant-a", created_a["connector_id"])
    assert cross is not None
    other_tenant_read = await repo.get("tenant-b", created_a["connector_id"])
    assert other_tenant_read is None


@pytest.mark.asyncio
async def test_list_by_tenant_filters_by_status_and_connector_type() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-filters"
    active = await repo.create(tenant_id=tenant_id, connector_type="google_ads")
    paused = await repo.create(tenant_id=tenant_id, connector_type="meta_ads")
    await repo.set_status(tenant_id, paused["connector_id"], "paused")

    only_active = await repo.list_by_tenant(tenant_id, status="active")
    assert [c["connector_id"] for c in only_active] == [active["connector_id"]]

    only_meta = await repo.list_by_tenant(tenant_id, connector_type="meta_ads")
    assert [c["connector_id"] for c in only_meta] == [paused["connector_id"]]

    only_paused_meta = await repo.list_by_tenant(
        tenant_id, status="paused", connector_type="meta_ads",
    )
    assert [c["connector_id"] for c in only_paused_meta] == [paused["connector_id"]]


@pytest.mark.asyncio
async def test_list_for_tenant_alias_matches_unfiltered_list_by_tenant() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-alias"
    created = await repo.create(tenant_id=tenant_id, connector_type="google_ads")

    via_alias = await repo.list_for_tenant(tenant_id)
    via_filtered = await repo.list_by_tenant(tenant_id)
    assert [c["connector_id"] for c in via_alias] == [c["connector_id"] for c in via_filtered]
    assert [c["connector_id"] for c in via_alias] == [created["connector_id"]]


# ─────────────────────────────────────────────────────────────────────────────
# Ported write operations — set_status / update_cursor / record_sync
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_status_updates_and_is_read_back() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-status"
    created = await repo.create(tenant_id=tenant_id, connector_type="google_ads")
    connector_id = created["connector_id"]
    assert created["status"] == "active"

    ok = await repo.set_status(tenant_id, connector_id, "paused")
    assert ok is True

    fetched = await repo.get(tenant_id, connector_id)
    assert fetched["status"] == "paused"


@pytest.mark.asyncio
async def test_set_status_returns_false_for_missing_connector() -> None:
    repo = MeasurementConnectorRepository()
    ok = await repo.set_status("tenant-missing", "does-not-exist", "paused")
    assert ok is False


@pytest.mark.asyncio
async def test_update_cursor_persists_cursor_state() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-cursor"
    created = await repo.create(tenant_id=tenant_id, connector_type="google_ads")
    connector_id = created["connector_id"]
    assert created["cursor_state"] == {}

    ok = await repo.update_cursor(tenant_id, connector_id, {"page_token": "abc123"})
    assert ok is True

    fetched = await repo.get(tenant_id, connector_id)
    assert fetched["cursor_state"] == {"page_token": "abc123"}


@pytest.mark.asyncio
async def test_update_cursor_returns_false_for_missing_connector() -> None:
    repo = MeasurementConnectorRepository()
    ok = await repo.update_cursor("tenant-missing", "does-not-exist", {"x": 1})
    assert ok is False


@pytest.mark.asyncio
async def test_record_sync_success_updates_health_and_success_timestamp() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-sync-ok"
    created = await repo.create(tenant_id=tenant_id, connector_type="google_ads")
    connector_id = created["connector_id"]
    assert created["last_sync_at"] is None
    assert created["last_success_at"] is None

    next_sync = datetime.now(timezone.utc) + timedelta(hours=1)
    ok = await repo.record_sync(
        tenant_id, connector_id,
        success=True, next_sync_at=next_sync, health_status="healthy",
    )
    assert ok is True

    fetched = await repo.get(tenant_id, connector_id)
    assert fetched["health_status"] == "healthy"
    assert fetched["last_sync_at"] is not None
    assert fetched["last_success_at"] is not None
    assert fetched["next_sync_at"] is not None


@pytest.mark.asyncio
async def test_record_sync_failure_updates_health_without_success_timestamp() -> None:
    repo = MeasurementConnectorRepository()
    tenant_id = "tenant-sync-fail"
    created = await repo.create(tenant_id=tenant_id, connector_type="google_ads")
    connector_id = created["connector_id"]

    ok = await repo.record_sync(tenant_id, connector_id, success=False, health_status="error")
    assert ok is True

    fetched = await repo.get(tenant_id, connector_id)
    assert fetched["health_status"] == "error"
    assert fetched["last_sync_at"] is not None
    assert fetched["last_success_at"] is None


@pytest.mark.asyncio
async def test_record_sync_returns_false_for_missing_connector() -> None:
    repo = MeasurementConnectorRepository()
    ok = await repo.record_sync("tenant-missing", "does-not-exist", success=True)
    assert ok is False
