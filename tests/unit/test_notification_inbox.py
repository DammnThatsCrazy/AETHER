"""Tenant in-app notification inbox: create, list, unread, read, archive, dedupe, isolation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))

from services.notification_intelligence import inbox as inbox_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_store():
    # Clear the exact store the singleton repo uses (all inbox functions go
    # through get_inbox_repository()), so each test starts from empty.
    inbox_mod.get_inbox_repository()._store.clear()
    yield
    inbox_mod.get_inbox_repository()._store.clear()


async def test_create_and_list():
    await inbox_mod.create_inbox_notification(
        "tenant-a", category="export_ready", severity="info", title="Export ready", body="Your export is ready"
    )
    items = await inbox_mod.list_inbox_notifications("tenant-a")
    assert len(items) == 1
    assert items[0]["title"] == "Export ready"
    assert items[0]["read"] is False


async def test_unread_count_and_mark_read():
    n = await inbox_mod.create_inbox_notification(
        "tenant-a", category="system_incident", severity="warning", title="t", body="b"
    )
    assert await inbox_mod.unread_notification_count("tenant-a") == 1
    await inbox_mod.mark_notification_read("tenant-a", n["id"])
    assert await inbox_mod.unread_notification_count("tenant-a") == 0


async def test_mark_all_read():
    for i in range(3):
        await inbox_mod.create_inbox_notification(
            "tenant-a", category="data_quality", severity="info", title=f"t{i}", body="b"
        )
    assert await inbox_mod.unread_notification_count("tenant-a") == 3
    changed = await inbox_mod.mark_all_notifications_read("tenant-a")
    assert changed == 3
    assert await inbox_mod.unread_notification_count("tenant-a") == 0


async def test_archive():
    n = await inbox_mod.create_inbox_notification(
        "tenant-a", category="billing", severity="info", title="t", body="b"
    )
    archived = await inbox_mod.archive_notification("tenant-a", n["id"])
    assert archived["archived"] is True


async def test_dedupe_increments_count():
    a = await inbox_mod.create_inbox_notification(
        "tenant-a", category="delivery_failure", severity="warning", title="t", body="b",
        dedupe_key="dk-1",
    )
    b = await inbox_mod.create_inbox_notification(
        "tenant-a", category="delivery_failure", severity="warning", title="t", body="b",
        dedupe_key="dk-1",
    )
    assert a["id"] == b["id"]
    items = await inbox_mod.list_inbox_notifications("tenant-a")
    assert len(items) == 1
    assert items[0].get("count", 1) >= 2


async def test_tenant_isolation():
    await inbox_mod.create_inbox_notification(
        "tenant-a", category="security", severity="critical", title="secret", body="b"
    )
    assert await inbox_mod.unread_notification_count("tenant-b") == 0
    assert await inbox_mod.list_inbox_notifications("tenant-b") == []
