"""Silver projection of committed tenant imports.

Proves the commit fans out its primitive records into silver_import_facts: the
projector builds one row per (commit, file, row, primitive) with a replay-safe
idempotency key, the writer persists idempotently, and a real commit reports the
Silver row count and populates the local Silver table.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from services.imports import commit as cm  # noqa: E402
from services.imports import service as svc  # noqa: E402
from services.silver.projectors.import_projector import (  # noqa: E402
    SILVER_IMPORT_TABLE,
    ImportProjector,
)

TENANT = "tenant-silver"

CSV = (
    b"user_id,email,friend_id\n"
    b"alice,alice@example.com,bob\n"
    b"bob,bob@example.com,alice\n"
)
MAPPING = [
    {"source_column": "user_id", "primitive": "entity", "target_field": "external_id",
     "transform": "trim", "required": True},
    {"source_column": "email", "primitive": "identifier", "target_field": "value",
     "transform": "lowercase", "required": True},
    {"source_column": "user_id", "primitive": "identifier", "target_field": "entity_ref",
     "transform": "trim", "required": True},
    {"source_column": "user_id", "primitive": "relationship", "target_field": "from_ref",
     "transform": "trim", "required": True},
    {"source_column": "friend_id", "primitive": "relationship", "target_field": "to_ref",
     "transform": "trim", "required": True},
]


@contextmanager
def raises_named(*names: str):
    with pytest.raises(Exception) as excinfo:  # noqa: PT011
        yield excinfo
    assert type(excinfo.value).__name__ in names


# ── pure projector ───────────────────────────────────────────────────────────


def test_project_records_row_shape():
    records = [
        {"primitive": "entity", "row": 0, "fields": {"external_id": "e1"}, "file_id": "f1"},
        {"primitive": "identifier", "row": 0, "fields": {"value": "e1@x"}, "file_id": "f1"},
    ]
    result = ImportProjector().project_records(
        tenant_id="t1", commit_id="impc_x", import_id="imp1",
        mapping_version=1, occurred_at="2026-07-20T00:00:00+00:00", records=records,
    )
    assert result.table == SILVER_IMPORT_TABLE
    assert len(result.rows) == 2
    r0 = result.rows[0]
    assert r0["commit_id"] == "impc_x" and r0["primitive"] == "entity"
    assert r0["idempotency_key"] == "impc_x:f1:0:entity"
    assert r0["bronze_record_id"] == "f1:0"
    assert r0["payload"] == {"external_id": "e1"}


async def test_writer_persists_and_dedupes():
    from services.silver.writer import SilverFactWriter, _local_tables, reset_local_tables

    reset_local_tables()
    result = ImportProjector().project_records(
        tenant_id="t1", commit_id="impc_y", import_id="imp1", mapping_version=1,
        occurred_at="2026-07-20T00:00:00+00:00",
        records=[{"primitive": "entity", "row": 0, "fields": {}, "file_id": "f1"}],
    )
    n = await SilverFactWriter().persist([result])
    assert n == 1
    assert len(_local_tables.get(SILVER_IMPORT_TABLE, {})) == 1
    # Re-persisting the same key is a no-op in the local first-write-wins store.
    await SilverFactWriter().persist([result])
    assert len(_local_tables[SILVER_IMPORT_TABLE]) == 1


# ── end-to-end through commit ────────────────────────────────────────────────


@pytest.fixture()
def clean(monkeypatch):
    from repositories.import_files import get_import_file_repository
    from repositories.imports_repo import get_imports_repository
    from repositories.lake import BronzeRepository
    from services.silver.writer import reset_local_tables
    from shared.graph.graph import get_graph_client

    r = get_imports_repository()
    for attr in ("sessions", "schemas", "mappings", "templates", "validations",
                 "row_errors", "commits", "rollbacks"):
        getattr(r, attr)._store.clear()
    get_import_file_repository()._store.clear()
    BronzeRepository(cm.BRONZE_DOMAIN)._store.clear()
    reset_local_tables()
    backend = getattr(get_graph_client(), "_backend", None)
    if backend is not None:
        for name in ("_vertices", "_edges"):
            store = getattr(backend, name, None)
            if hasattr(store, "clear"):
                store.clear()
    monkeypatch.setattr(svc, "get_imports_repository", lambda: r)
    monkeypatch.setattr(cm, "get_imports_repository", lambda: r)
    return r


async def _seed_approved() -> str:
    session = await svc.create_import(TENANT, created_by="u1")
    import_id = session["id"]
    await svc.store_file(TENANT, import_id, filename="rel.csv", content=CSV, content_type="text/csv")
    await svc.analyze_import(TENANT, import_id)
    await svc.set_mapping(TENANT, import_id, MAPPING)
    await svc.validate_import(TENANT, import_id)
    await svc.approve_import(TENANT, import_id, approver="admin1")
    return import_id


async def test_commit_populates_silver(clean):
    from services.silver.writer import _local_tables

    import_id = await _seed_approved()
    record = await cm.commit_import(TENANT, import_id)
    # 2 rows x 3 primitives (entity, identifier, relationship) = 6 records.
    assert record["counts"]["silver_rows"] == 6
    facts = _local_tables.get(SILVER_IMPORT_TABLE, {})
    assert len([k for k in facts if k.startswith(f"{TENANT}:")]) == 6
    # every fact carries the commit lineage
    assert all(v["commit_id"] == record["commit_id"] for v in facts.values())
