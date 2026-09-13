"""DB-free tests for the Data Exchange Plane M1 storage migration.

Covers the M1 deliverables without any Postgres:

- the object-key scheme is tenant-scoped and traversal-safe;
- ``ObjectStoreImportStorage`` satisfies the ``ImportStorageAdapter`` protocol
  (round-trips bytes through an in-memory ObjectStore + in-memory
  ``data_artifacts`` repository) and refuses cross-tenant reads;
- ``DataArtifactRepository`` CRUD, per-tenant scoping and status transitions
  against the Data Exchange terminal-status vocabulary;
- ``data_exchange.migrate_legacy_artifact`` is idempotent (running it twice
  produces exactly one artifact row and one object, and a crash-window orphan
  object — bytes with no row — is self-healed on retry: a matching orphan gets
  its row back-filled, a stale one is rewritten).

The legacy BYTEA source is exercised through the *canonical* seam
(``PostgresImportStorage``) with its own in-memory backend, so the migration
reads exactly what the import engine would hand it in local mode.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from repositories.data_artifacts import (
    DataArtifactRepository,
    reset_data_artifact_in_memory_store,
)
from repositories.repos import reset_in_memory_stores
from services.data_exchange.contracts import DATA_ARTIFACT_TERMINAL_STATUSES
from services.data_exchange.jobs_migrate import (
    migrate_artifact_id,
    migrate_legacy_artifact,
)
from services.data_exchange.storage import (
    ObjectStoreImportStorage,
    get_data_exchange_import_storage,
    infer_ingress_format,
    object_key_for,
    tenant_object_prefix,
)
from services.imports.storage import PostgresImportStorage, get_import_storage
from shared.common.common import BadRequestError, ConflictError, NotFoundError
from shared.storage.object_store import InMemoryObjectStore

TENANT_A = "tnt_a"
TENANT_B = "tnt_b"


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch):
    """Guarantee the in-memory repository/object-store backends regardless of
    DATABASE_URL / boto3 presence in the surrounding environment."""

    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    monkeypatch.setattr("repositories.import_files.get_pool", _no_pool)
    reset_data_artifact_in_memory_store()
    reset_in_memory_stores()
    yield
    reset_data_artifact_in_memory_store()
    reset_in_memory_stores()


def _dt(day_offset: int) -> datetime:
    return datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=day_offset)


def _row_kwargs(aid: str, tenant_id: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "direction": "ingress",
        "artifact_type": "import_source",
        "object_key": f"data-exchange/{tenant_id}/ingress/{aid}",
        "filename": f"{aid}.csv",
        "format": "csv",
        "content_type": "text/csv",
        "size_bytes": 3,
        "sha256": "a" * 64,
        "classification": "none",
        "status": "uploaded",
        "canonical_id": None,
    }
    base.update(overrides)
    return base


async def _make(
    repo: DataArtifactRepository, aid: str, tenant_id: str, **overrides: Any
) -> dict:
    return await repo.create_artifact(
        aid, tenant_id, **_row_kwargs(aid, tenant_id, **overrides)
    )


# ── object-key scheme ───────────────────────────────────────────────────────


def test_object_key_scheme_is_tenant_scoped() -> None:
    key_a = object_key_for(TENANT_A, direction="ingress", artifact_id="art_1")
    key_b = object_key_for(TENANT_B, direction="ingress", artifact_id="art_1")
    assert key_a.startswith("data-exchange/tnt_a/ingress/")
    assert key_a == "data-exchange/tnt_a/ingress/art_1"
    assert key_b != key_a
    # direction is part of the scheme
    egress = object_key_for(TENANT_A, direction="egress", artifact_id="art_1")
    assert egress == "data-exchange/tnt_a/egress/art_1"

    # trailing-slash tenant prefix: listing tenant A never sees tenant B.
    store = InMemoryObjectStore()
    store.put(key_a, b"a")
    store.put(key_b, b"b")
    store.put(object_key_for(TENANT_A, direction="egress", artifact_id="z"), b"z")
    keys = store.list(tenant_object_prefix(TENANT_A))
    assert keys == [
        "data-exchange/tnt_a/egress/z",
        "data-exchange/tnt_a/ingress/art_1",
    ]
    assert not any(k.startswith("data-exchange/tnt_b/") for k in keys)


def test_object_key_scheme_rejects_traversal() -> None:
    for bad in ("../../etc/passwd", "a/b", "..", ".", ""):
        with pytest.raises(BadRequestError):
            object_key_for(TENANT_A, direction="ingress", artifact_id=bad)
    with pytest.raises(BadRequestError):
        object_key_for("", direction="ingress", artifact_id="art_1")
    with pytest.raises(BadRequestError):
        object_key_for(TENANT_A, direction="sideways", artifact_id="art_1")
    with pytest.raises(BadRequestError):
        tenant_object_prefix("tnt_a/../")


def test_infer_ingress_format_prefers_extension() -> None:
    assert infer_ingress_format("rows.csv", "application/octet-stream") == "csv"
    assert infer_ingress_format("rows.jsonl", "application/octet-stream") == "jsonl"
    assert infer_ingress_format("rows.bin", "application/vnd.apache.parquet") == "parquet"
    assert infer_ingress_format("rows.unknown", "text/csv") == "csv"
    assert infer_ingress_format("rows.bin", "application/json") == "json"


# ── ObjectStoreImportStorage (adapter protocol) ─────────────────────────────


@pytest.mark.asyncio
async def test_object_store_import_storage_round_trips() -> None:
    object_store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    adapter = ObjectStoreImportStorage(object_store=object_store, artifact_repo=repo)

    content = b"id,name\n1,a\n2,b\n"
    meta = await adapter.put(
        TENANT_A,
        import_id="imp_1",
        filename="people.csv",
        content=content,
        content_type="text/csv",
    )
    file_id = meta["id"]
    assert file_id.startswith("impf_")
    assert meta["tenant_id"] == TENANT_A
    assert meta["size_bytes"] == len(content)
    assert meta["sha256"] == hashlib.sha256(content).hexdigest()
    assert meta["object_key"].startswith(f"data-exchange/{TENANT_A}/ingress/")

    # get_meta
    meta2 = await adapter.get_meta(TENANT_A, file_id)
    assert meta2["id"] == file_id
    assert meta2["filename"] == "people.csv"
    assert meta2["format"] == "csv"

    # get_content round-trips the exact bytes
    g_meta, data = await adapter.get_content(TENANT_A, file_id)
    assert data == content
    assert g_meta["sha256"] == meta["sha256"]

    # size is observable through the object store head
    stat = object_store.head(meta["object_key"])
    assert stat is not None and stat.size_bytes == len(content)

    # list_for_import groups files of one import (canonical_id = import_id)
    files = await adapter.list_for_import(TENANT_A, "imp_1")
    assert len(files) == 1
    assert files[0]["id"] == file_id

    # delete removes bytes + tombstones the metadata row
    deleted = await adapter.delete(TENANT_A, file_id)
    assert deleted is True
    assert object_store.head(meta["object_key"]) is None
    with pytest.raises(NotFoundError):
        await adapter.get_content(TENANT_A, file_id)


@pytest.mark.asyncio
async def test_object_store_import_storage_refuses_cross_tenant() -> None:
    object_store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    adapter = ObjectStoreImportStorage(object_store=object_store, artifact_repo=repo)

    meta = await adapter.put(
        TENANT_A,
        import_id="imp_1",
        filename="f.csv",
        content=b"x",
        content_type="text/csv",
    )
    file_id = meta["id"]

    with pytest.raises(NotFoundError):
        await adapter.get_meta(TENANT_B, file_id)
    with pytest.raises(NotFoundError):
        await adapter.get_content(TENANT_B, file_id)
    assert await adapter.list_for_import(TENANT_B, "imp_1") == []
    # No bytes are reachable under tenant B's prefix.
    assert object_store.head(object_key_for(TENANT_B, direction="ingress", artifact_id=file_id)) is None
    # Deleting as the wrong tenant is a no-op that leaves tenant A intact.
    assert await adapter.delete(TENANT_B, file_id) is False
    assert await adapter.get_meta(TENANT_A, file_id) is not None


# ── DataArtifactRepository ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artifact_repo_crud_and_tenant_scoping() -> None:
    repo = DataArtifactRepository()

    a1 = await _make(repo, "a1", TENANT_A, canonical_id="file_1", created_at=_dt(1))
    assert a1["artifact_id"] == "a1"
    assert a1["canonical_id"] == "file_1"
    assert a1["status"] == "uploaded"
    assert a1["source_or_destination"] == {}
    assert a1["deleted_at"] is None

    got = await repo.get(TENANT_A, "a1")
    assert got["artifact_id"] == "a1"
    assert got["canonical_id"] == "file_1"

    # Cross-tenant reads fail closed.
    with pytest.raises(NotFoundError):
        await repo.get(TENANT_B, "a1")
    assert await repo.get_by_canonical_id(TENANT_B, "file_1") is None
    assert (await repo.get_by_canonical_id(TENANT_A, "file_1"))["artifact_id"] == "a1"

    # list is scoped and newest-first.
    await _make(repo, "a2", TENANT_A, direction="egress", artifact_type="export",
                canonical_id="file_2", created_at=_dt(2))
    await _make(repo, "a3", TENANT_B, direction="ingress", canonical_id="file_3",
                created_at=_dt(3))

    tenant_rows = await repo.list_for_tenant(TENANT_A)
    assert {r["artifact_id"] for r in tenant_rows} == {"a1", "a2"}
    assert tenant_rows[0]["artifact_id"] == "a2"  # newest first

    ingress_only = await repo.list_for_tenant(TENANT_A, direction="ingress")
    assert [r["artifact_id"] for r in ingress_only] == ["a1"]

    egress_type = await repo.list_for_tenant(TENANT_A, artifact_type="export")
    assert [r["artifact_id"] for r in egress_type] == ["a2"]

    status_filtered = await repo.list_for_tenant(TENANT_B, status="uploaded")
    assert [r["artifact_id"] for r in status_filtered] == ["a3"]


@pytest.mark.asyncio
async def test_artifact_repo_enforces_envelope_vocabulary() -> None:
    repo = DataArtifactRepository()
    with pytest.raises(BadRequestError):
        await _make(repo, "bad_dir", TENANT_A, direction="diagonal")
    with pytest.raises(BadRequestError):
        await _make(repo, "bad_cls", TENANT_A, classification="ultra_secret")
    with pytest.raises(BadRequestError):
        await _make(repo, "bad_status", TENANT_A, status="draft")
    with pytest.raises(BadRequestError):
        await repo.list_for_tenant(TENANT_A, direction="diagonal")


@pytest.mark.asyncio
async def test_artifact_status_transitions_respect_terminal_vocabulary() -> None:
    """``update_status`` enforces the byte-ownership doctrine (finding #2).

    A durable-byte state (``available``/``committed``/``partially_committed``)
    is never reachable by a status flip — only ``mark_available`` (verified
    size/sha) or direct creation reaches one.  Tombstones are absorbing; a
    durable-byte source may only tombstone to ``expired``/``deleted``/
    ``revoked`` (never ``failed``); a ``failed`` row may only move to
    ``deleted``.
    """
    repo = DataArtifactRepository()

    # Transient → transient is fine (uploaded → scanning).
    await _make(repo, "a1", TENANT_A)
    live = await repo.update_status(TENANT_A, "a1", "scanning")
    assert live["status"] == "scanning"

    # …but a status flip can NEVER promote into a durable-byte state.
    with pytest.raises(ConflictError):
        await repo.update_status(TENANT_A, "a1", "committed")
    with pytest.raises(ConflictError):
        await repo.update_status(TENANT_A, "a1", "available")

    # Direct creation is the other legal way into a durable-byte state; a
    # directly-created ``committed`` row is terminal and absorbing.
    committed = await _make(
        repo, "a1c", TENANT_A, status="committed", canonical_id="file_c1"
    )
    assert committed["status"] == "committed"
    assert committed["status"] in DATA_ARTIFACT_TERMINAL_STATUSES
    with pytest.raises(ConflictError):  # no resurrection back to a live status
        await repo.update_status(TENANT_A, "a1c", "uploaded")
    with pytest.raises(ConflictError):  # durable-byte → failed is never legal
        await repo.update_status(TENANT_A, "a1c", "failed")

    # A durable-byte source may still be tombstoned (durable → tombstone)…
    deleted = await repo.update_status(TENANT_A, "a1c", "deleted")
    assert deleted["status"] == "deleted"
    # …and a tombstone is absorbing: no outgoing transitions at all.
    with pytest.raises(ConflictError):
        await repo.update_status(TENANT_A, "a1c", "expired")

    # A ``failed`` row may only move to ``deleted``.
    await _make(repo, "a1f", TENANT_A, status="failed")
    with pytest.raises(ConflictError):
        await repo.update_status(TENANT_A, "a1f", "revoked")
    failed_deleted = await repo.update_status(TENANT_A, "a1f", "deleted")
    assert failed_deleted["status"] == "deleted"

    # Unknown statuses are rejected up front.
    with pytest.raises(BadRequestError):
        await repo.update_status(TENANT_A, "a1", "not_a_status")

    # Cross-tenant transitions fail closed.
    await _make(repo, "a2", TENANT_B)
    with pytest.raises(NotFoundError):
        await repo.update_status(TENANT_A, "a2", "deleted")


@pytest.mark.asyncio
async def test_mark_available_is_the_only_path_to_available() -> None:
    """``mark_available`` records verified bytes; nothing else reaches ``available``.

    Idempotent on an already-available row; refuses tombstones (no
    resurrection) and durable-byte siblings (no silent re-flip).
    """
    repo = DataArtifactRepository()
    await _make(repo, "g1", TENANT_A, status="generating", sha256="0" * 64)

    available = await repo.mark_available(
        TENANT_A, "g1", size_bytes=3, sha256="a" * 64
    )
    assert available["status"] == "available"
    assert available["size_bytes"] == 3
    assert available["sha256"] == "a" * 64
    assert available["source_or_destination"].get("materialized") is True

    # Idempotent: already-available is returned untouched (bytes preserved).
    again = await repo.mark_available(TENANT_A, "g1", size_bytes=999, sha256="b" * 64)
    assert again["sha256"] == "a" * 64
    assert again["size_bytes"] == 3

    # Tombstones can never be resurrected to available.
    await _make(repo, "g2", TENANT_A, status="deleted")
    with pytest.raises(ConflictError):
        await repo.mark_available(TENANT_A, "g2", size_bytes=3, sha256="a" * 64)

    # A durable-byte sibling (committed) is never silently re-flipped.
    await _make(repo, "g3", TENANT_A, status="committed", sha256="a" * 64)
    with pytest.raises(ConflictError):
        await repo.mark_available(TENANT_A, "g3", size_bytes=3, sha256="a" * 64)


@pytest.mark.asyncio
async def test_same_artifact_id_coexists_across_tenants() -> None:
    """``data_artifacts`` PK is composite ``(tenant_id, artifact_id)`` (#14).

    Egress artifacts reuse a client-supplied export_id as artifact_id, so two
    tenants may LEGALLY hold the same artifact_id — tenant A's export ``exp_42``
    must not make tenant B's ``exp_42`` a PK collision.  All reads and lifecycle
    moves stay tenant-scoped.
    """
    repo = DataArtifactRepository()
    a_row = await _make(
        repo, "exp_42", TENANT_A, canonical_id="file_a", filename="a.csv"
    )
    b_row = await _make(
        repo, "exp_42", TENANT_B, canonical_id="file_b", filename="b.csv"
    )
    assert a_row["artifact_id"] == b_row["artifact_id"] == "exp_42"

    # Each tenant reads back its OWN row under the shared artifact_id…
    assert (await repo.get(TENANT_A, "exp_42"))["filename"] == "a.csv"
    assert (await repo.get(TENANT_B, "exp_42"))["filename"] == "b.csv"
    # …and reads still fail closed for a tenant/id combo that does not exist.
    with pytest.raises(NotFoundError):
        await repo.get(TENANT_A, "missing_id")

    # list stays scoped: each tenant sees exactly its own artifact.
    assert [r["artifact_id"] for r in await repo.list_for_tenant(TENANT_A)] == ["exp_42"]
    assert [r["artifact_id"] for r in await repo.list_for_tenant(TENANT_B)] == ["exp_42"]

    # Lifecycle moves on one tenant's row never touch the other's.
    await repo.mark_deleted(TENANT_A, "exp_42")
    assert (await repo.get(TENANT_B, "exp_42"))["status"] == "uploaded"
    assert (await repo.get(TENANT_A, "exp_42"))["status"] == "deleted"


@pytest.mark.asyncio
async def test_artifact_tombstone_helpers() -> None:
    repo = DataArtifactRepository()
    await _make(repo, "a1", TENANT_A, expires_at=_dt(-1))

    expired = await repo.mark_expired(TENANT_A, "a1")
    assert expired["status"] == "expired"

    await _make(repo, "a2", TENANT_A)
    deleted = await repo.mark_deleted(TENANT_A, "a2")
    assert deleted["status"] == "deleted"
    assert deleted["deleted_at"] is not None


# ── migration job idempotency ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migrate_legacy_artifact_is_idempotent() -> None:
    source = PostgresImportStorage()
    stored = await source.put(
        TENANT_A,
        import_id="imp_legacy",
        filename="rows.csv",
        content=b"a,b\n1,2\n",
        content_type="text/csv",
    )
    file_id = stored["id"]
    object_store = InMemoryObjectStore()
    repo = DataArtifactRepository()

    first = await migrate_legacy_artifact(
        TENANT_A,
        file_id,
        source_storage=source,
        object_store=object_store,
        artifact_repo=repo,
        correlation_id="corr-1",
    )
    assert first["skipped"] is False
    assert first["canonical_id"] == file_id
    assert first["artifact_id"] == migrate_artifact_id(TENANT_A, file_id)
    assert object_store.get(first["object_key"]) == b"a,b\n1,2\n"
    assert first["object_key"].startswith(f"data-exchange/{TENANT_A}/ingress/")

    rows = await repo.list_for_tenant(TENANT_A)
    assert len(rows) == 1
    assert rows[0]["canonical_id"] == file_id
    assert rows[0]["direction"] == "ingress"
    assert rows[0]["filename"] == "rows.csv"

    # A retry must not duplicate the row or the object.
    second = await migrate_legacy_artifact(
        TENANT_A,
        file_id,
        source_storage=source,
        object_store=object_store,
        artifact_repo=repo,
        correlation_id="corr-2",
    )
    assert second["skipped"] is True
    assert second["reason"] == "already_migrated"
    assert second["artifact_id"] == first["artifact_id"]
    assert len(await repo.list_for_tenant(TENANT_A)) == 1
    assert len(object_store.list(f"data-exchange/{TENANT_A}/")) == 1


@pytest.mark.asyncio
async def test_migrate_legacy_artifact_self_heals_matching_orphan() -> None:
    """Crash between the byte write and create_artifact → retry back-fills the row.

    The object at the deterministic key already equals the current legacy source
    (bytes-then-row was satisfied), so the migration keeps the bytes, creates
    the metadata row and reports not-skipped — no permanent byte-only orphan and
    no duplicate object.
    """
    source = PostgresImportStorage()
    stored = await source.put(
        TENANT_A,
        import_id="imp_orphan",
        filename="b.csv",
        content=b"c\n1\n",
        content_type="text/csv",
    )
    file_id = stored["id"]
    object_store = InMemoryObjectStore()
    repo = DataArtifactRepository()

    artifact_id = migrate_artifact_id(TENANT_A, file_id)
    key = object_key_for(TENANT_A, direction="ingress", artifact_id=artifact_id)
    object_store.put(key, b"c\n1\n")  # orphan bytes == current source

    result = await migrate_legacy_artifact(
        TENANT_A,
        file_id,
        source_storage=source,
        object_store=object_store,
        artifact_repo=repo,
    )
    assert result["skipped"] is False
    assert result["reason"] is None
    assert result["artifact_id"] == artifact_id
    rows = await repo.list_for_tenant(TENANT_A)
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == artifact_id
    assert rows[0]["sha256"] == hashlib.sha256(b"c\n1\n").hexdigest()
    # Exactly one object — the orphan was NOT duplicated.
    assert object_store.list(f"data-exchange/{TENANT_A}/") == [key]


@pytest.mark.asyncio
async def test_migrate_legacy_artifact_replaces_stale_orphan_object() -> None:
    """A stale orphan (bytes ≠ current legacy source) is rewritten, not stranded.

    The old behavior no-op'd with ``reason="object_exists"`` forever — the row
    was never back-filled and the object could never match a source that had
    changed since the crash.  Now the retry drops the stale bytes, rewrites the
    current content and completes the migration.
    """
    source = PostgresImportStorage()
    stored = await source.put(
        TENANT_A,
        import_id="imp_stale",
        filename="c.csv",
        content=b"c\n1\n",
        content_type="text/csv",
    )
    file_id = stored["id"]
    object_store = InMemoryObjectStore()
    repo = DataArtifactRepository()

    artifact_id = migrate_artifact_id(TENANT_A, file_id)
    key = object_key_for(TENANT_A, direction="ingress", artifact_id=artifact_id)
    object_store.put(key, b"stale-old-bytes")

    result = await migrate_legacy_artifact(
        TENANT_A,
        file_id,
        source_storage=source,
        object_store=object_store,
        artifact_repo=repo,
    )
    assert result["skipped"] is False
    assert result["reason"] is None
    assert await repo.list_for_tenant(TENANT_A) != []
    # The object at the deterministic key is exactly the current source.
    assert object_store.get(key) == b"c\n1\n"
    assert len(object_store.list(f"data-exchange/{TENANT_A}/")) == 1


@pytest.mark.asyncio
async def test_migrate_legacy_artifact_records_envelope_metadata() -> None:
    source = PostgresImportStorage()
    stored = await source.put(
        TENANT_A,
        import_id="imp_env",
        filename="people.jsonl",
        content=b'{"x":1}\n',
        content_type="application/jsonl",
    )
    result = await migrate_legacy_artifact(
        TENANT_A,
        stored["id"],
        source_storage=source,
        object_store=InMemoryObjectStore(),
        artifact_repo=DataArtifactRepository(),
        created_by="operator@aether",
    )
    row = await DataArtifactRepository().get(TENANT_A, result["artifact_id"])
    assert row["format"] == "jsonl"
    assert row["content_type"] == "application/jsonl"
    assert row["sha256"] == stored["sha256"]
    assert row["size_bytes"] == stored["size_bytes"]
    assert row["created_by"] == "operator@aether"
    assert row["source_or_destination"]["legacy_file_id"] == stored["id"]
    assert row["source_or_destination"]["import_id"] == "imp_env"


# ── factory flag selection ──────────────────────────────────────────────────


def test_factory_returns_canonical_when_object_store_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = SimpleNamespace(
        data_exchange=SimpleNamespace(object_store_enabled=False),
        runtime=SimpleNamespace(object_backend="memory"),
    )
    monkeypatch.setattr("config.settings.settings", fake)
    assert get_data_exchange_import_storage() is get_import_storage()


def test_factory_returns_object_store_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = SimpleNamespace(
        data_exchange=SimpleNamespace(object_store_enabled=True),
        runtime=SimpleNamespace(object_backend="memory"),
    )
    monkeypatch.setattr("config.settings.settings", fake)
    adapter = get_data_exchange_import_storage()
    assert isinstance(adapter, ObjectStoreImportStorage)
