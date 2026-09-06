"""DB-free tests for the Data Exchange Plane M4 export envelope + history.

Covers the M4 deliverables without any Postgres, ObjectStore or durable-job
runtime (mirrors the M1 ``test_storage_migration.py`` style):

- ``create_export`` enqueues via the canonical-export seam and registers the
  egress ``data_artifacts`` envelope row with the tenant-scoped egress object
  key, ``artifact_type="export"``, status ``generating`` and correct
  format/content-type; duplicate envelope ids and disabled parquet are refused;
- envelope create → list → get → delete round trip;
- the registered exporters are idempotent and the envelope exporter projects
  rows / delegates / rejects unknown resources cleanly;
- unified artifact history (``/artifacts``) filters by direction, artifact_type
  and status and returns DataArtifactContract-shaped meta.

DB-free contract: the artifact repository's ``get_pool`` is patched to None so
every repository read/write lands in the in-memory fallback; the canonical
``request_export`` seam is replaced by an injected fake ``enqueue``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from repositories.data_artifacts import (
    DataArtifactRepository,
    reset_data_artifact_in_memory_store,
)
from services.data_exchange.contracts import ExportSpecContract
from services.data_exchange.exporters import (
    EXPORT_TYPE_DATA_EXCHANGE,
    EXPORT_TYPE_DATA_EXCHANGE_PARQUET,
    data_exchange_export,
    data_exchange_parquet_export,
    register_data_exchange_exporters,
)
from services.data_exchange.history import (
    get_artifact_history,
    list_artifacts_history,
)
from services.data_exchange.routes_export import (
    create_export,
    delete_export_artifact,
    get_export_artifact,
    list_export_artifacts,
)
from services.data_exchange.storage import object_key_for
from shared.common.common import BadRequestError, NotFoundError
from services.export.service import EXPORTERS

TENANT_A = "tnt_a"
TENANT_B = "tnt_b"


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch):
    """Guarantee the in-memory data_artifacts backend regardless of DATABASE_URL."""

    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    reset_data_artifact_in_memory_store()
    yield
    reset_data_artifact_in_memory_store()


def _dt(day_offset: int) -> datetime:
    return datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=day_offset)


def _spec(export_id: str, tenant_id: str = TENANT_A, **overrides: Any) -> ExportSpecContract:
    base: dict[str, Any] = {
        "export_id": export_id,
        "tenant_id": tenant_id,
        "resource": "audit_log",
        "fields": ["id", "ts", "actor"],
        "format": "json",
    }
    base.update(overrides)
    return ExportSpecContract(**base)


async def _fake_enqueue(tenant_id: str, *, export_type: str, params: dict, requested_by=None, correlation_id=None) -> dict:
    return {
        "job_id": f"job_{export_id_for(params)}",
        "status": "queued",
        "status_url": "/v1/jobs/job_x",
        "replayed": False,
    }


def export_id_for(params: dict) -> str:
    return str((params or {}).get("export_id", "x"))


def _row_kwargs_repo_create(aid: str, tenant_id: str, **overrides: Any) -> dict:
    base: dict[str, Any] = {
        "direction": "egress",
        "artifact_type": "export",
        "object_key": f"data-exchange/{tenant_id}/egress/{aid}",
        "filename": f"{aid}.json",
        "format": "json",
        "content_type": "application/json",
        "size_bytes": 12,
        "sha256": "b" * 64,
        "classification": "none",
        "status": "available",
        "canonical_id": f"art_{aid}",
        "source_or_destination": {"export_id": aid},
        "created_at": _dt(1),
    }
    base.update(overrides)
    return base


async def _make_row(repo: DataArtifactRepository, aid: str, tenant_id: str, **overrides: Any) -> dict:
    return await repo.create_artifact(aid, tenant_id, **_row_kwargs_repo_create(aid, tenant_id, **overrides))


# ── create → list → get round trip ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_export_returns_envelope_and_registers_egress_row() -> None:
    repo = DataArtifactRepository()
    spec = _spec("exp_001")
    result = await create_export(
        TENANT_A, spec, artifact_repo=repo, enqueue=_fake_enqueue, created_by="user-1"
    )
    assert result == {
        "export_id": "exp_001",
        "artifact_id": "exp_001",
        "job_id": "job_exp_001",
        "status": "generating",
    }

    row = await repo.get(TENANT_A, "exp_001")
    assert row["direction"] == "egress"
    assert row["artifact_type"] == "export"
    assert row["format"] == "json"
    assert row["content_type"] == "application/json"
    assert row["status"] == "generating"
    assert row["size_bytes"] == 0  # bytes materialize when the job completes
    assert row["job_id"] == "job_exp_001"
    assert row["created_by"] == "user-1"
    # Object key follows the M1 tenant-scoped egress scheme.
    assert row["object_key"] == object_key_for(TENANT_A, direction="egress", artifact_id="exp_001")
    assert row["source_or_destination"]["export_id"] == "exp_001"
    assert row["source_or_destination"]["materialized"] is False
    # The row is invisible to any other tenant.
    with pytest.raises(NotFoundError):
        await repo.get(TENANT_B, "exp_001")


@pytest.mark.asyncio
async def test_export_list_and_detail_round_trip() -> None:
    repo = DataArtifactRepository()
    await create_export(TENANT_A, _spec("exp_001"), artifact_repo=repo, enqueue=_fake_enqueue)
    await create_export(TENANT_A, _spec("exp_002", resource="targeting_package", format="csv"), artifact_repo=repo, enqueue=_fake_enqueue)

    listed = await list_export_artifacts(TENANT_A, artifact_repo=repo)
    assert listed["count"] == 2
    assert {a["artifact_id"] for a in listed["artifacts"]} == {"exp_001", "exp_002"}
    assert all(a["direction"] == "egress" and a["artifact_type"] == "export" for a in listed["artifacts"])
    assert all("updated_at" not in a for a in listed["artifacts"])

    # Non-export egress rows (e.g. future report artifacts) are not exports.
    await _make_row(repo, "rpt_001", TENANT_A, artifact_type="report", status="generating")
    still = await list_export_artifacts(TENANT_A, artifact_repo=repo)
    assert still["count"] == 2

    detail = await get_export_artifact(TENANT_A, "exp_001", artifact_repo=repo)
    assert detail["artifact_id"] == "exp_001"
    assert detail["status"] == "generating"
    assert detail["canonical"]["job_id"] == "job_exp_001"
    assert detail["canonical"]["status_url"] == "/v1/jobs/job_exp_001"
    # csv spec picked the canonical targeting_package exporter through the envelope.
    detail2 = await get_export_artifact(TENANT_A, "exp_002", artifact_repo=repo)
    assert detail2["canonical"]["export_type"] == "targeting_package"
    assert detail2["canonical"]["registered"] is True


@pytest.mark.asyncio
async def test_list_status_filter() -> None:
    repo = DataArtifactRepository()
    await create_export(TENANT_A, _spec("exp_001"), artifact_repo=repo, enqueue=_fake_enqueue)
    await _make_row(repo, "exp_old", TENANT_A, status="available", created_at=_dt(0))
    only_available = await list_export_artifacts(TENANT_A, status_filter="available", artifact_repo=repo)
    assert [a["artifact_id"] for a in only_available["artifacts"]] == ["exp_old"]
    only_generating = await list_export_artifacts(TENANT_A, status_filter="generating", artifact_repo=repo)
    assert {a["artifact_id"] for a in only_generating["artifacts"]} == {"exp_001"}


# ── validation ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_export_rejects_duplicate_envelope_id() -> None:
    repo = DataArtifactRepository()
    await create_export(TENANT_A, _spec("exp_001"), artifact_repo=repo, enqueue=_fake_enqueue)
    with pytest.raises(BadRequestError, match="already exists"):
        await create_export(TENANT_A, _spec("exp_001"), artifact_repo=repo, enqueue=_fake_enqueue)


@pytest.mark.asyncio
async def test_parquet_egress_is_availability_flag_gated() -> None:
    repo = DataArtifactRepository()
    spec = _spec("exp_pq", format="parquet", compression="zstd")
    # Flag off → refused.
    with pytest.raises(BadRequestError, match="parquet egress is disabled"):
        await create_export(TENANT_A, spec, artifact_repo=repo, enqueue=_fake_enqueue, parquet_enabled=False)
    # Flag on → registered as a parquet egress artifact.
    created = await create_export(TENANT_A, spec, artifact_repo=repo, enqueue=_fake_enqueue, parquet_enabled=True)
    assert created["status"] == "generating"
    row = await repo.get(TENANT_A, "exp_pq")
    assert row["format"] == "parquet"
    assert row["content_type"] == "application/vnd.apache.parquet"
    assert row["object_key"].endswith("/egress/exp_pq")


@pytest.mark.asyncio
async def test_create_export_rejects_traversal_export_id() -> None:
    repo = DataArtifactRepository()
    with pytest.raises(BadRequestError):
        await create_export(TENANT_A, _spec("../../etc/passwd"), artifact_repo=repo, enqueue=_fake_enqueue)


# ── delete / revoke ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_export_tombstones_row() -> None:
    repo = DataArtifactRepository()
    await create_export(TENANT_A, _spec("exp_001"), artifact_repo=repo, enqueue=_fake_enqueue)
    result = await delete_export_artifact(TENANT_A, "exp_001", artifact_repo=repo)
    assert result["deleted"] is True
    assert result["artifact_id"] == "exp_001"
    row = await repo.get(TENANT_A, "exp_001")
    assert row["status"] == "deleted"
    assert row["deleted_at"] is not None
    # Cross-tenant delete is a no-op 404.
    with pytest.raises(NotFoundError):
        await delete_export_artifact(TENANT_B, "exp_001", artifact_repo=repo)


# ── exporter registration + envelope exporter ───────────────────────────────


@pytest.mark.asyncio
async def test_register_data_exchange_exporters_is_idempotent() -> None:
    for name in (EXPORT_TYPE_DATA_EXCHANGE, EXPORT_TYPE_DATA_EXCHANGE_PARQUET):
        EXPORTERS.pop(name, None)
    register_data_exchange_exporters()
    register_data_exchange_exporters()  # second call must not raise
    assert EXPORT_TYPE_DATA_EXCHANGE in EXPORTERS
    assert EXPORT_TYPE_DATA_EXCHANGE_PARQUET in EXPORTERS


@pytest.mark.asyncio
async def test_data_exchange_export_uses_injected_rows_and_projects_fields() -> None:
    payload = await data_exchange_export(
        TENANT_A,
        {
            "resource": "ad_hoc",
            "fields": ["id", "name"],
            "rows": [
                {"id": 1, "name": "a", "secret": "x"},
                {"id": 2, "name": "b", "secret": "y"},
            ],
        },
    )
    assert payload.rows == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert payload.columns == ["id", "name"]
    assert payload.per_source == {"rows": 2}


@pytest.mark.asyncio
async def test_data_exchange_export_rejects_unknown_resource() -> None:
    with pytest.raises(BadRequestError, match="not supported"):
        await data_exchange_export(TENANT_A, {"resource": "does_not_exist"})


@pytest.mark.asyncio
async def test_parquet_exporter_forces_parquet_format() -> None:
    with pytest.raises(BadRequestError, match="only supports format"):
        await data_exchange_parquet_export(TENANT_A, {"resource": "x", "format": "csv"})
    payload = await data_exchange_parquet_export(
        TENANT_A, {"resource": "x", "format": "parquet", "rows": [{"a": 1}]}
    )
    assert payload.rows == [{"a": 1}]


# ── unified artifact history ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unified_history_lists_across_directions_and_filters() -> None:
    repo = DataArtifactRepository()
    # Ingress import artifact, egress export artifact, egress report artifact.
    await _make_row(repo, "imp_1", TENANT_A, direction="ingress", artifact_type="import_source",
                    status="uploaded", created_at=_dt(3))
    await _make_row(repo, "exp_1", TENANT_A, direction="egress", artifact_type="export",
                    status="available", created_at=_dt(2))
    await _make_row(repo, "rpt_1", TENANT_A, direction="egress", artifact_type="report",
                    status="generating", created_at=_dt(1))

    all_rows = await list_artifacts_history(TENANT_A, artifact_repo=repo)
    assert all_rows["count"] == 3
    assert [a["artifact_id"] for a in all_rows["artifacts"]] == ["imp_1", "exp_1", "rpt_1"]  # newest first

    ingress = await list_artifacts_history(TENANT_A, direction="ingress", artifact_repo=repo)
    assert [a["artifact_id"] for a in ingress["artifacts"]] == ["imp_1"]

    egress_exports = await list_artifacts_history(TENANT_A, direction="egress", artifact_type="export", artifact_repo=repo)
    assert [a["artifact_id"] for a in egress_exports["artifacts"]] == ["exp_1"]

    generating = await list_artifacts_history(TENANT_A, status_filter="generating", artifact_repo=repo)
    assert [a["artifact_id"] for a in generating["artifacts"]] == ["rpt_1"]

    paginated = await list_artifacts_history(TENANT_A, limit=2, offset=0, artifact_repo=repo)
    assert paginated["count"] == 2

    # Another tenant never sees tenant A's history.
    other = await list_artifacts_history(TENANT_B, artifact_repo=repo)
    assert other == {"artifacts": [], "count": 0}


@pytest.mark.asyncio
async def test_artifact_history_get_is_contract_shaped_and_tenant_scoped() -> None:
    repo = DataArtifactRepository()
    await _make_row(repo, "exp_1", TENANT_A)
    meta = await get_artifact_history(TENANT_A, "exp_1", artifact_repo=repo)
    assert meta["artifact_id"] == "exp_1"
    assert meta["tenant_id"] == TENANT_A
    assert meta["direction"] == "egress"
    assert meta["canonical_id"] == "art_exp_1"  # additive envelope extension
    assert "updated_at" not in meta
    with pytest.raises(NotFoundError):
        await get_artifact_history(TENANT_B, "exp_1", artifact_repo=repo)


# ── egress payloads keep correct object-key scheme at the row level ─────────


@pytest.mark.asyncio
async def test_egress_row_object_keys_are_tenant_scoped() -> None:
    repo = DataArtifactRepository()
    # artifact_id is a globally-unique primary key, so tenant scoping is carried
    # by the row tenant_id and the object key's tenant segment — never by
    # re-using one id across two tenants (that would PK-violate in Postgres).
    await _make_row(repo, "exp_a", TENANT_A)
    await _make_row(repo, "exp_b", TENANT_B)
    key_a = object_key_for(TENANT_A, direction="egress", artifact_id="exp_a")
    key_b = object_key_for(TENANT_B, direction="egress", artifact_id="exp_b")
    assert (await repo.get(TENANT_A, "exp_a"))["object_key"] == key_a
    assert (await repo.get(TENANT_B, "exp_b"))["object_key"] == key_b
    assert key_a != key_b
    assert key_a.startswith("data-exchange/tnt_a/egress/")
    assert key_b.startswith("data-exchange/tnt_b/egress/")
    # A row created by tenant A is unreadable (and untombstonable) by tenant B.
    with pytest.raises(NotFoundError):
        await repo.get(TENANT_B, "exp_a")
