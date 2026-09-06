"""DB-free tests for the M3 ``/v1/data-exchange/usage`` read adapter.

Covers the aggregation that previously fed ``list_for_tenant(limit=100000)``
into every row (finding #13): per-tenant imports/exports/reports counts, the
rolling 30-day window, cross-tenant isolation, and — via the new projected
``DataArtifactRepository.usage_rows`` — that the scan is UNCAPMED and pages a
Postgres backend to exhaustion instead of truncating at an arbitrary limit.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from repositories.data_artifacts import (  # noqa: E402
    DataArtifactRepository,
    get_data_artifact_repository,
    reset_data_artifact_in_memory_store,
)
from services.data_exchange.capabilities import data_exchange_usage  # noqa: E402
from shared.auth.auth import Role, TenantContext  # noqa: E402

TENANT_A = "tnt_a"
TENANT_B = "tnt_b"


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch):
    """Pin every artifact store to the in-memory backend and bind the route to a
    FRESH repository, so a prior Postgres-branch test's pooled singleton never
    leaks across cases."""

    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.data_exchange.capabilities.get_data_artifact_repository",
        lambda: DataArtifactRepository(),
    )
    reset_data_artifact_in_memory_store()
    yield
    reset_data_artifact_in_memory_store()


def _dt(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _seed_kwargs(aid: str, tenant_id: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "direction": "ingress",
        "artifact_type": "import_source",
        "object_key": f"data-exchange/{tenant_id}/ingress/{aid}",
        "filename": f"{aid}.csv",
        "format": "csv",
        "content_type": "text/csv",
        "size_bytes": 10,
        "sha256": "a" * 64,
        "classification": "none",
        "status": "uploaded",
    }
    base.update(overrides)
    return base


async def _seed(repo: DataArtifactRepository, aid: str, tenant_id: str, **o: Any) -> None:
    await repo.create_artifact(aid, tenant_id, **_seed_kwargs(aid, tenant_id, **o))


async def _seed_both_tenants(repo: DataArtifactRepository) -> None:
    """One import artifact per tenant + an old/new export and a report (A)."""
    # ── tenant A: imports (one inside, one outside the 30-day window) ──────
    await _seed(
        repo,
        "imp_old",
        TENANT_A,
        source_or_destination={"import_id": "imp_old_id"},
        created_at=_dt(40),
    )
    await _seed(
        repo,
        "imp_new",
        TENANT_A,
        source_or_destination={"import_id": "imp_new_id"},
        created_at=_dt(2),
    )
    # ── tenant A: egress exports + one PDF report row ──────────────────────
    await _seed(
        repo,
        "exp_old",
        TENANT_A,
        direction="egress",
        artifact_type="export",
        size_bytes=100,
        created_at=_dt(40),
    )
    await _seed(
        repo,
        "exp_new",
        TENANT_A,
        direction="egress",
        artifact_type="export",
        size_bytes=250,
        created_at=_dt(1),
    )
    await _seed(
        repo,
        "rep_new",
        TENANT_A,
        direction="egress",
        artifact_type="report",
        size_bytes=60,
        created_at=_dt(1),
    )
    # ── tenant B: an ingress import must never leak into A's aggregation ───
    await _seed(
        repo,
        "b_imp",
        TENANT_B,
        source_or_destination={"import_id": "b_imp_id"},
        created_at=_dt(1),
    )


class _Request:
    def __init__(self, tenant: TenantContext) -> None:
        self.state = SimpleNamespace(tenant=tenant, request_id="req-1")


def _admin_request() -> _Request:
    return _Request(TenantContext(tenant_id=TENANT_A, role=Role.ADMIN, permissions=[]))


@pytest.mark.asyncio
async def test_usage_route_counts_families_per_tenant_with_window() -> None:
    repo = get_data_artifact_repository()
    await _seed_both_tenants(repo)

    body = await data_exchange_usage(_admin_request())

    assert body["tenant_id"] == TENANT_A
    # imports = 2 for A; B's row excluded.
    assert body["imports"] == {"count": 2, "last_30_days": 1}
    # exports aggregate every egress artifact incl. the report row.
    assert body["exports"] == {
        "count": 3,
        "bytes": 410,
        "last_30_days": 2,
        "last_30_days_bytes": 310,
    }
    # reports is the report-only slice.
    assert body["reports"] == {"count": 1}


@pytest.mark.asyncio
async def test_usage_ignores_zero_byte_rows_outside_window() -> None:
    repo = get_data_artifact_repository()
    await _seed_both_tenants(repo)

    # A zero-byte report from long ago neither inflates byte totals nor the
    # rolling window (it still counts toward the report/egress tallies).
    await _seed(
        repo,
        "rep_zero_old",
        TENANT_A,
        direction="egress",
        artifact_type="report",
        size_bytes=0,
        created_at=_dt(90),
    )

    body = await data_exchange_usage(_admin_request())
    assert body["reports"] == {"count": 2}
    assert body["exports"]["count"] == 4
    assert body["exports"]["bytes"] == 410  # zero-byte adds nothing
    assert body["exports"]["last_30_days"] == 2
    assert body["exports"]["last_30_days_bytes"] == 310  # 90-day-old excluded


@pytest.mark.asyncio
async def test_usage_rows_projects_only_aggregation_columns_and_is_uncapped() -> None:
    """usage_rows returns ONLY the five aggregation columns, for EVERY row.

    Regression for finding #13: the old adapter pulled ``list_for_tenant`` which
    returned all 24 envelope columns and capped the feed at 100k rows.
    """
    repo = get_data_artifact_repository()
    await _seed_both_tenants(repo)
    for i in range(150):
        await _seed(
            repo,
            f"bulk_{i:04d}",
            TENANT_A,
            source_or_destination={"import_id": f"bulk_{i}"},
            created_at=_dt(0),
        )

    rows = await repo.usage_rows(TENANT_A)
    # tenant A rows only: 2 imports + 2 exports + 1 report + 150 bulk.
    assert len(rows) == 155
    assert all(
        set(r) == {
            "direction",
            "artifact_type",
            "size_bytes",
            "created_at",
            "source_or_destination",
        }
        for r in rows
    )
    # A's rows carry correct projected values (spot-check the report row).
    report = next(r for r in rows if r["artifact_type"] == "report")
    assert report["direction"] == "egress"
    assert report["size_bytes"] == 60
    assert isinstance(report["created_at"], str)
    # Cross-tenant leak check on the projected scan.
    assert not any(
        r["source_or_destination"].get("import_id", "").startswith("b_")
        for r in rows
    )


# ── Postgres page-loop regression (finding #13) ──────────────────────────────


class _PagePool:
    """Minimal asyncpg-like pool honoring LIMIT/OFFSET so ``usage_rows``'
    page-loop branch is exercised for real."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def execute(self, sql: str, *args: Any) -> str:  # noqa: ANN401
        return "CREATE TABLE"

    async def fetch(self, sql: str, *args: Any) -> list:  # noqa: ANN401
        limit, offset = int(args[1]), int(args[2])  # (tenant_id, $2, $3)
        return self._rows[offset : offset + limit]


@pytest.mark.asyncio
async def test_usage_rows_pages_postgres_to_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the Postgres branch usage_rows must not stop at one page.

    More rows than one 10k page forces multiple LIMIT/OFFSET fetches; every
    seeded row — not just the first page — must come back, and the loop must
    terminate exactly when a short page signals the end.
    """
    rows = [
        {
            "direction": "ingress",
            "artifact_type": "import_source",
            "size_bytes": 10,
            "created_at": _dt(i % 29),  # every row inside the 30-day window
            "source_or_destination": {"import_id": f"imp_{i:05d}"},
        }
        for i in range(25000)
    ]
    fake = _PagePool(rows)

    async def _pool() -> _PagePool:
        return fake

    repo = DataArtifactRepository()
    monkeypatch.setattr("repositories.data_artifacts.get_pool", _pool)
    monkeypatch.setattr(
        "services.data_exchange.capabilities.get_data_artifact_repository",
        lambda: repo,
    )

    body = await data_exchange_usage(_admin_request())
    assert body["imports"]["count"] == 25000
    assert body["imports"]["last_30_days"] == 25000
    assert body["exports"] == {
        "count": 0,
        "bytes": 0,
        "last_30_days": 0,
        "last_30_days_bytes": 0,
    }
