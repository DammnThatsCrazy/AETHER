"""Measurement Integrity Plane repository — immutable insert, supersession,
restatement chains, tenant isolation, and DDL parity with the migration.

Runs against the in-memory backend (AETHER_ENV=local, get_pool() -> None). The
module-level ``_repo`` singleton is reset per test via monkeypatch so each test
starts from an empty store.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AETHER_ENV", "local")

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from repositories import measurement_results_repo as mrr  # noqa: E402
from repositories.measurement_results_repo import (  # noqa: E402
    MEASUREMENT_RESTATEMENTS_DDL,
    MEASUREMENT_RESULTS_DDL,
    MeasurementResultsRepository,
    get_measurement_results_repository,
)
from shared.common.common import BadRequestError, NotFoundError  # noqa: E402

MIGRATION_PATH = (
    BACKEND / "alembic" / "versions" / "20260716_measurement_integrity.py"
)


@pytest.fixture()
def repo(monkeypatch):
    """Fresh singleton per test (empty in-memory stores)."""
    monkeypatch.setattr(mrr, "_repo", None)
    r = get_measurement_results_repository()
    assert isinstance(r, MeasurementResultsRepository)
    yield r
    monkeypatch.setattr(mrr, "_repo", None)


def _record(tenant="tenant-a", *, value=1.0, state="measured", ctx="ctx-1", **kw):
    return {
        "tenant_id": tenant,
        "metric_name": kw.pop("metric_name", "active_wallets"),
        "metric_version": kw.pop("metric_version", "v1"),
        "context_hash": ctx,
        "value": value,
        "value_state": state,
        "unit": kw.pop("unit", "count"),
        "lineage": kw.pop("lineage", {"sources": ["silver.tx"]}),
        "sufficiency": kw.pop("sufficiency", {"score": 0.9}),
        "uncertainty": kw.pop("uncertainty", None),
        **kw,
    }


# ── insert + get ────────────────────────────────────────────────────────────

async def test_insert_assigns_ids_and_get_roundtrips(repo):
    rec = await repo.insert_result(_record())
    assert rec["id"].startswith("mr_")
    assert rec["created_at"] and rec["computed_at"]
    assert rec["superseded_by"] is None
    assert rec["value"] == 1.0 and rec["unit"] == "count"
    assert rec["lineage"] == {"sources": ["silver.tx"]}

    fetched = await repo.get("tenant-a", rec["id"])
    assert fetched == rec


async def test_insert_defaults_optional_fields(repo):
    rec = await repo.insert_result(
        {
            "tenant_id": "tenant-a",
            "metric_name": "m",
            "metric_version": "v1",
            "context_hash": "c",
            "value_state": "insufficient",
        }
    )
    assert rec["value"] is None
    assert rec["unit"] == "count"
    assert rec["lineage"] == {} and rec["sufficiency"] == {}
    assert rec["uncertainty"] is None


async def test_insert_requires_core_keys(repo):
    with pytest.raises(BadRequestError):
        await repo.insert_result({"metric_name": "m", "metric_version": "v1"})


# ── active-duplicate handling ───────────────────────────────────────────────

async def test_active_duplicate_rejected(repo):
    await repo.insert_result(_record())
    with pytest.raises(BadRequestError):
        await repo.insert_result(_record())


async def test_same_coords_allowed_after_supersede(repo):
    first = await repo.insert_result(_record(value=1.0))
    # Superseding frees the active slot, so the superseding row is fine...
    await repo.supersede(
        "tenant-a", first["id"], _record(value=2.0), reason="late data"
    )
    # ...but a brand-new active insert on the same coords now clashes with the
    # new active row.
    with pytest.raises(BadRequestError):
        await repo.insert_result(_record(value=3.0))


# ── supersede ───────────────────────────────────────────────────────────────

async def test_supersede_flips_prior_inserts_new_and_writes_restatement(repo):
    prior = await repo.insert_result(_record(value=10.0))
    new = await repo.supersede(
        "tenant-a", prior["id"], _record(value=12.0), reason="backfill correction"
    )

    # prior is now superseded, pointing at the new row
    prior_after = await repo.get("tenant-a", prior["id"])
    assert prior_after["superseded_by"] == new["id"]

    # new row is active
    assert new["superseded_by"] is None
    assert new["value"] == 12.0

    # get_active returns the new row, not the prior
    active = await repo.get_active("tenant-a", "active_wallets", "v1", "ctx-1")
    assert active["id"] == new["id"]

    # a restatement audit row was written
    restatements = await repo.list_restatements("tenant-a")
    assert len(restatements) == 1
    r = restatements[0]
    assert r["prior_result_id"] == prior["id"]
    assert r["new_result_id"] == new["id"]
    assert r["reason"] == "backfill correction"
    assert r["restated_at"]


async def test_supersede_missing_prior_raises(repo):
    with pytest.raises(NotFoundError):
        await repo.supersede(
            "tenant-a", "mr_nope", _record(), reason="x"
        )


async def test_supersede_cross_tenant_prior_raises(repo):
    prior = await repo.insert_result(_record(tenant="tenant-a"))
    with pytest.raises(NotFoundError):
        await repo.supersede(
            "tenant-b", prior["id"], _record(tenant="tenant-b"), reason="x"
        )


async def test_supersede_already_superseded_raises(repo):
    prior = await repo.insert_result(_record(value=1.0))
    await repo.supersede("tenant-a", prior["id"], _record(value=2.0), reason="r1")
    with pytest.raises(BadRequestError):
        await repo.supersede(
            "tenant-a", prior["id"], _record(value=3.0), reason="r2"
        )


async def test_supersede_requires_reason(repo):
    prior = await repo.insert_result(_record())
    with pytest.raises(BadRequestError):
        await repo.supersede("tenant-a", prior["id"], _record(value=2.0), reason="  ")


# ── restatement chain ───────────────────────────────────────────────────────

async def test_restatement_chain_orders_oldest_to_newest(repo):
    a = await repo.insert_result(_record(value=1.0))
    b = await repo.supersede("tenant-a", a["id"], _record(value=2.0), reason="r1")
    c = await repo.supersede("tenant-a", b["id"], _record(value=3.0), reason="r2")

    expected = [a["id"], b["id"], c["id"]]
    # Chain is identical regardless of which node we start from.
    for start in (a["id"], b["id"], c["id"]):
        chain = await repo.restatement_chain("tenant-a", start)
        assert [row["id"] for row in chain] == expected
        assert [row["value"] for row in chain] == [1.0, 2.0, 3.0]


async def test_restatement_chain_single_element(repo):
    a = await repo.insert_result(_record())
    chain = await repo.restatement_chain("tenant-a", a["id"])
    assert [row["id"] for row in chain] == [a["id"]]


async def test_restatement_chain_missing_returns_empty(repo):
    assert await repo.restatement_chain("tenant-a", "mr_missing") == []


# ── list_for_tenant filters ─────────────────────────────────────────────────

async def test_list_for_tenant_active_vs_history(repo):
    a = await repo.insert_result(_record(value=1.0))
    b = await repo.supersede("tenant-a", a["id"], _record(value=2.0), reason="r1")
    # a different metric, independent active row
    other = await repo.insert_result(_record(metric_name="fees", ctx="ctx-2"))

    active = await repo.list_for_tenant("tenant-a")
    active_ids = {r["id"] for r in active}
    assert active_ids == {b["id"], other["id"]}  # superseded 'a' excluded

    full = await repo.list_for_tenant("tenant-a", include_superseded=True)
    assert {r["id"] for r in full} == {a["id"], b["id"], other["id"]}

    wallets = await repo.list_for_tenant(
        "tenant-a", metric_name="active_wallets", include_superseded=True
    )
    assert {r["id"] for r in wallets} == {a["id"], b["id"]}


async def test_list_for_tenant_limit(repo):
    for i in range(5):
        await repo.insert_result(_record(metric_name=f"m{i}", ctx=f"ctx-{i}"))
    limited = await repo.list_for_tenant("tenant-a", limit=2)
    assert len(limited) == 2


# ── cross-tenant isolation ──────────────────────────────────────────────────

async def test_tenant_isolation(repo):
    a = await repo.insert_result(_record(tenant="tenant-a"))
    # cross-tenant get is None
    assert await repo.get("tenant-b", a["id"]) is None
    # cross-tenant active lookup is None
    assert await repo.get_active("tenant-b", "active_wallets", "v1", "ctx-1") is None
    # tenant-b sees no results / chain
    assert await repo.list_for_tenant("tenant-b") == []
    assert await repo.restatement_chain("tenant-b", a["id"]) == []
    # tenant-b may hold its OWN active row for the same coords (no collision)
    b = await repo.insert_result(_record(tenant="tenant-b"))
    assert b["id"] != a["id"]
    assert (await repo.get("tenant-b", b["id"]))["id"] == b["id"]


# ── DDL parity ──────────────────────────────────────────────────────────────

class TestDdlParity:
    def _migration_text(self) -> str:
        assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"
        return MIGRATION_PATH.read_text(encoding="utf-8")

    def test_results_ddl_matches_migration(self):
        migration = self._migration_text()
        match = re.search(
            r'MEASUREMENT_RESULTS_DDL = """\n(.*?)"""', migration, re.DOTALL
        )
        assert match, "migration lost its MEASUREMENT_RESULTS_DDL constant"
        assert match.group(1).strip() == MEASUREMENT_RESULTS_DDL.strip()

    def test_restatements_ddl_matches_migration(self):
        migration = self._migration_text()
        match = re.search(
            r'MEASUREMENT_RESTATEMENTS_DDL = """\n(.*?)"""', migration, re.DOTALL
        )
        assert match, "migration lost its MEASUREMENT_RESTATEMENTS_DDL constant"
        assert match.group(1).strip() == MEASUREMENT_RESTATEMENTS_DDL.strip()

    def test_migration_revision_wiring(self):
        migration = self._migration_text()
        assert 'revision = "20260716_measurement_integrity"' in migration
        assert (
            'down_revision = "20260715_identity_merge_correctness"' in migration
        )

    def test_repo_ddl_contains_key_invariants(self):
        # The active-uniqueness partial index and both tables are load-bearing.
        assert "ux_measurement_results_active" in MEASUREMENT_RESULTS_DDL
        assert "WHERE superseded_by IS NULL" in MEASUREMENT_RESULTS_DDL
        assert "CREATE TABLE IF NOT EXISTS measurement_results" in MEASUREMENT_RESULTS_DDL
        assert (
            "CREATE TABLE IF NOT EXISTS measurement_restatements"
            in MEASUREMENT_RESTATEMENTS_DDL
        )
