"""Unit tests: repository-level tenant isolation for the Silver/Gold lake tiers.

Regression tests for the audit's tenant-isolation findings D and E:

- ``GoldRepository.materialize`` keyed its ``record_id`` without ``tenant_id``,
  so two tenants materializing the same ``(metric, entity, type)`` collided on
  one row and silently overwrote each other (E).
- ``SilverRepository.get_entity`` / ``GoldRepository.get_metrics`` /
  ``get_highlights`` had no tenant predicate, so any tenant could read another
  tenant's rows (D).

The fix scopes reads to the caller's tenant PLUS global tenant-less rows (never
another tenant's) and includes ``tenant_id`` in the Gold ``record_id``.
``tenant_id=None`` remains an explicit cross-tenant read for ETL jobs.
"""
from __future__ import annotations

import pytest

from repositories.lake import GoldRepository, SilverRepository
from repositories.repos import reset_in_memory_stores


@pytest.mark.asyncio
async def test_two_tenants_materialize_same_metric_do_not_overwrite():
    reset_in_memory_stores()
    gold = GoldRepository(domain="iso_metric")

    await gold.materialize(metric_name="score", entity_id="wallet1",
                           entity_type="wallet", value={"n": 1}, tenant_id="tenant-a")
    await gold.materialize(metric_name="score", entity_id="wallet1",
                           entity_type="wallet", value={"n": 2}, tenant_id="tenant-b")

    a = await gold.get_metrics("wallet1", entity_type="wallet", tenant_id="tenant-a")
    b = await gold.get_metrics("wallet1", entity_type="wallet", tenant_id="tenant-b")

    # Each tenant keeps its own value — no cross-tenant overwrite.
    assert [r["value"] for r in a] == [{"n": 1}]
    assert [r["value"] for r in b] == [{"n": 2}]


@pytest.mark.asyncio
async def test_get_metrics_scopes_to_tenant_plus_global():
    reset_in_memory_stores()
    gold = GoldRepository(domain="iso_scope")

    await gold.materialize(metric_name="m", entity_id="e", entity_type="t",
                           value={"src": "a"}, tenant_id="tenant-a")
    await gold.materialize(metric_name="m", entity_id="e", entity_type="t",
                           value={"src": "b"}, tenant_id="tenant-b")
    await gold.materialize(metric_name="m", entity_id="e", entity_type="t",
                           value={"src": "global"}, tenant_id="")  # global/ETL

    rows = await gold.get_metrics("e", entity_type="t", tenant_id="tenant-a")
    # Own tenant + global tenant-less, but NEVER tenant-b.
    assert sorted(r["value"]["src"] for r in rows) == ["a", "global"]


@pytest.mark.asyncio
async def test_empty_tenant_returns_global_only_never_all_tenants():
    # Regression: an empty-string tenant_id (no owning tenant, e.g. an engine
    # invoked without a tenant) must scope to global/legacy rows only — never a
    # full cross-tenant read (which would leak every tenant's data).
    reset_in_memory_stores()
    gold = GoldRepository(domain="iso_empty")
    await gold.materialize(metric_name="m", entity_id="e", entity_type="t",
                           value={"src": "a"}, tenant_id="tenant-a")
    await gold.materialize(metric_name="m", entity_id="e", entity_type="t",
                           value={"src": "global"}, tenant_id="")

    rows = await gold.get_metrics("e", entity_type="t", tenant_id="")
    assert sorted(r["value"]["src"] for r in rows) == ["global"]


@pytest.mark.asyncio
async def test_get_metrics_cross_tenant_read_sees_all():
    reset_in_memory_stores()
    gold = GoldRepository(domain="iso_all")

    await gold.materialize(metric_name="m", entity_id="e", entity_type="t",
                           value={"src": "a"}, tenant_id="tenant-a")
    await gold.materialize(metric_name="m", entity_id="e", entity_type="t",
                           value={"src": "b"}, tenant_id="tenant-b")

    # Explicit cross-tenant read (ETL) sees every tenant.
    rows = await gold.get_metrics("e", entity_type="t", tenant_id=None)
    assert sorted(r["value"]["src"] for r in rows) == ["a", "b"]


@pytest.mark.asyncio
async def test_get_highlights_scopes_to_tenant_plus_global():
    reset_in_memory_stores()
    gold = GoldRepository(domain="iso_hl")

    await gold.materialize(metric_name="alert", entity_id="e1", entity_type="t",
                           value={"who": "a"}, tenant_id="tenant-a")
    await gold.materialize(metric_name="alert", entity_id="e2", entity_type="t",
                           value={"who": "b"}, tenant_id="tenant-b")

    rows = await gold.get_highlights("alert", tenant_id="tenant-a")
    who = sorted(r["value"]["who"] for r in rows)
    assert who == ["a"]  # tenant-b's highlight is not visible to tenant-a


@pytest.mark.asyncio
async def test_silver_get_entity_scopes_to_tenant_plus_global():
    reset_in_memory_stores()
    silver = SilverRepository("iso_silver")

    async def _write(tenant, tag):
        await silver.upsert_record(
            entity_id="wallet1", entity_type="wallet",
            source=tag, source_tag=tag, normalized={"who": tag},
            tenant_id=tenant,
        )

    await _write("tenant-a", "a")
    await _write("tenant-b", "b")
    await _write("", "global")  # tenant-less / legacy

    rows = await silver.get_entity("wallet1", "wallet", tenant_id="tenant-a")
    assert sorted(r.get("who") for r in rows) == ["a", "global"]

    # Explicit cross-tenant read sees every row.
    allrows = await silver.get_entity("wallet1", "wallet", tenant_id=None)
    assert sorted(r.get("who") for r in allrows) == ["a", "b", "global"]
