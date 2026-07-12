"""Tests for Metering Evidence (§3.16) — record, dedupe, and tenant isolation."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.repos import reset_in_memory_stores
from services.metering_evidence.service import (
    EXCLUDED_DUPLICATE,
    MeteredEvent,
    MeteringEvidenceService,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def test_record_first_event_is_billable():
    svc = MeteringEvidenceService()
    rec = await svc.record(
        tenant_id="tenant-a",
        source_path="/v1/ingest/events",
        source_provider="sdk",
        event_id="evt-1",
        dedupe_key="dk-1",
        usage_dimension="events",
        quantity=1,
    )
    assert rec["billable"] is True
    assert rec["excluded_reason"] is None
    assert rec["billing_reason"] == "metered"
    assert rec["tenant_id"] == "tenant-a"
    assert rec["metered_event_id"]
    assert rec["metered_at"]
    assert rec["received_at"]
    assert rec["usage_dimension"] == "events"
    assert rec["quantity"] == 1
    # Record carries every MeteredEvent field.
    for f in MeteredEvent.__dataclass_fields__:
        assert f in rec


async def test_duplicate_dedupe_key_is_excluded_and_non_billable():
    svc = MeteringEvidenceService()
    first = await svc.record(
        tenant_id="tenant-a",
        source_path="/v1/ingest/events",
        event_id="evt-1",
        dedupe_key="dk-dup",
    )
    second = await svc.record(
        tenant_id="tenant-a",
        source_path="/v1/ingest/events",
        event_id="evt-2",
        dedupe_key="dk-dup",  # same dedupe key, same tenant
    )

    # Original stays billable.
    assert first["billable"] is True
    assert first["excluded_reason"] is None
    # Duplicate is excluded and non-billable, referencing the original.
    assert second["billable"] is False
    assert second["excluded_reason"] == EXCLUDED_DUPLICATE
    assert second["billing_reason"] == f"duplicate_of:{first['metered_event_id']}"
    assert second["metered_event_id"] != first["metered_event_id"]


async def test_explain_returns_record():
    svc = MeteringEvidenceService()
    rec = await svc.record(
        tenant_id="tenant-a",
        source_path="/v1/ingest/events",
        event_id="evt-1",
        dedupe_key="dk-1",
    )
    explained = await svc.explain(rec["metered_event_id"])
    assert explained is not None
    assert explained["metered_event_id"] == rec["metered_event_id"]
    assert explained["event_id"] == "evt-1"

    # Unknown id -> None.
    assert await svc.explain("does-not-exist") is None


async def test_explain_is_tenant_isolated():
    svc = MeteringEvidenceService()
    rec = await svc.record(
        tenant_id="tenant-a",
        source_path="/v1/ingest/events",
        event_id="evt-1",
        dedupe_key="dk-1",
    )
    mid = rec["metered_event_id"]

    # Wrong tenant cannot read it.
    assert await svc.explain(mid, tenant_id="tenant-b") is None
    # Owning tenant can.
    owned = await svc.explain(mid, tenant_id="tenant-a")
    assert owned is not None
    assert owned["metered_event_id"] == mid


async def test_dedupe_is_scoped_per_tenant():
    svc = MeteringEvidenceService()
    a = await svc.record(
        tenant_id="tenant-a",
        source_path="/v1/ingest/events",
        event_id="evt-a",
        dedupe_key="shared-key",
    )
    b = await svc.record(
        tenant_id="tenant-b",
        source_path="/v1/ingest/events",
        event_id="evt-b",
        dedupe_key="shared-key",  # same key, different tenant
    )
    # No cross-tenant dedupe: both are billable originals.
    assert a["billable"] is True
    assert b["billable"] is True
    assert b["excluded_reason"] is None
