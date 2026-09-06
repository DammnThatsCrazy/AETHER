"""DB-free tests for the M4 egress-completion bridge (:mod:`services.data_exchange.egress`).

Covers the coordinator delta that materializes an envelope ``generating`` export
row once the canonical ``export.generate`` job succeeds:

- happy path: verified bytes mirror onto the tenant-scoped egress object key and
  the row flips to terminal ``available`` with the real sha256/size and
  ``source_or_destination.materialized: true``;
- missing / already-available / other-terminal / object-key-mismatch rows are
  clean ``skipped`` results (never raised errors), and no bytes are ever written
  off the deterministic tenant prefix (cross-tenant safety);
- ``try_finalize_egress_envelope`` swallows any store/repo fault so the canonical
  export job that already succeeded is never failed retroactively by the bridge.

DB-free contract (mirrors ``test_export_envelope.py``): the artifact
repository's ``get_pool`` is patched to None so every read/write lands in the
in-memory fallback, and an ``InMemoryObjectStore`` is injected explicitly.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from repositories.data_artifacts import (
    DataArtifactRepository,
    reset_data_artifact_in_memory_store,
)
from services.data_exchange.egress import (
    finalize_egress_envelope,
    try_finalize_egress_envelope,
)
from services.data_exchange.storage import object_key_for
from shared.common.common import NotFoundError
from shared.storage.object_store import InMemoryObjectStore

TENANT_A = "tnt_a"
TENANT_B = "tnt_b"

# The empty-payload sentinel routes_export.py records on a pre-materialization
# ``generating`` row (must match routes_export._EMPTY_PAYLOAD_SHA256).
_EMPTY_PAYLOAD_SHA256 = hashlib.sha256(b"").hexdigest()


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch):
    """Guarantee the in-memory data_artifacts backend regardless of DATABASE_URL."""

    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    reset_data_artifact_in_memory_store()
    yield
    reset_data_artifact_in_memory_store()


def _egress_kwargs(export_id: str, tenant_id: str, **overrides: Any) -> dict:
    """Keyword args for ``create_artifact`` modeling the routes_export row."""
    base: dict[str, Any] = {
        "direction": "egress",
        "artifact_type": "export",
        "object_key": object_key_for(tenant_id, direction="egress", artifact_id=export_id),
        "filename": f"audit_log-{export_id}.json",
        "format": "json",
        "content_type": "application/json",
        "size_bytes": 0,
        "sha256": _EMPTY_PAYLOAD_SHA256,
        "classification": "none",
        "status": "generating",
        "canonical_id": None,
        "job_id": f"job_{export_id}",
        "source_or_destination": {
            "export": True,
            "export_id": export_id,
            "resource": "audit_log",
            "materialized": False,
        },
        "schema_version": "1.0",
        "created_by": "user-1",
    }
    base.update(overrides)
    return base


async def _make_row(
    repo: DataArtifactRepository,
    export_id: str,
    tenant_id: str = TENANT_A,
    **overrides: Any,
) -> dict:
    return await repo.create_artifact(
        export_id, tenant_id, **_egress_kwargs(export_id, tenant_id, **overrides)
    )


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ── happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_materializes_generating_row() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    await _make_row(repo, "exp_001")

    content = b'{"id": 1, "ts": "2026-09-01T00:00:00Z"}'
    result = await finalize_egress_envelope(
        TENANT_A,
        "exp_001",
        content=content,
        content_type="application/json",
        canonical_artifact_id="art_canon_1",
        artifact_repo=repo,
        object_store=store,
    )

    assert result["skipped"] is False
    assert result["artifact_id"] == "exp_001"
    assert result["sha256"] == _sha(content)
    assert result["size_bytes"] == len(content)
    assert result["object_key"] == object_key_for(
        TENANT_A, direction="egress", artifact_id="exp_001"
    )
    assert result["status"] == "available"

    # Bytes are durable at the envelope's own tenant-scoped key.
    assert store.get(result["object_key"]) == content

    # Row flipped to terminal available with the real sha/size + materialized.
    row = await repo.get(TENANT_A, "exp_001")
    assert row["status"] == "available"
    assert row["sha256"] == _sha(content)
    assert row["size_bytes"] == len(content)
    source = row["source_or_destination"]
    assert source["materialized"] is True
    assert source["content_type"] == "application/json"
    assert source["canonical_artifact_id"] == "art_canon_1"


@pytest.mark.asyncio
async def test_finalize_is_idempotent_on_already_available_row() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    existing = await _make_row(
        repo,
        "exp_001",
        status="available",
        size_bytes=4,
        sha256="a" * 64,
        source_or_destination={"export": True, "materialized": True},
    )
    store.put(existing["object_key"], b"old")

    result = await finalize_egress_envelope(
        TENANT_A,
        "exp_001",
        content=b"new-bytes",
        artifact_repo=repo,
        object_store=store,
    )
    assert result["skipped"] is True
    assert result["reason"] == "already_available"
    assert result["sha256"] == "a" * 64
    # Existing durable bytes and row are untouched.
    assert store.get(existing["object_key"]) == b"old"
    row = await repo.get(TENANT_A, "exp_001")
    assert row["size_bytes"] == 4 and row["sha256"] == "a" * 64


# ── skip semantics ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_skips_missing_row() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    result = await finalize_egress_envelope(
        TENANT_A, "exp_missing", content=b"x", artifact_repo=repo, object_store=store
    )
    assert result["skipped"] is True
    assert result["reason"] == "no_envelope_row"
    assert store.list("data-exchange/") == []


@pytest.mark.asyncio
async def test_finalize_cross_tenant_lookup_is_a_clean_skip() -> None:
    """Tenant B finalizing tenant A's row id must never see or write bytes."""
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    await _make_row(repo, "exp_001", TENANT_A)

    result = await finalize_egress_envelope(
        TENANT_B,
        "exp_001",
        content=b"x",
        artifact_repo=repo,
        object_store=store,
    )
    assert result["skipped"] is True
    assert result["reason"] == "no_envelope_row"
    assert store.list("data-exchange/") == []


@pytest.mark.asyncio
async def test_finalize_skips_terminal_row_without_writing_bytes() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    await _make_row(repo, "exp_001", status="deleted")

    result = await finalize_egress_envelope(
        TENANT_A, "exp_001", content=b"x", artifact_repo=repo, object_store=store
    )
    assert result["skipped"] is True
    assert result["reason"] == "terminal_status"
    assert store.list("data-exchange/") == []
    row = await repo.get(TENANT_A, "exp_001")
    assert row["status"] == "deleted"


@pytest.mark.asyncio
async def test_finalize_refuses_object_key_mismatch() -> None:
    """A stored key outside the deterministic (tenant, direction, id) scheme is
    never written — guards a row whose prefix does not match its tenant."""
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    foreign_key = object_key_for(TENANT_B, direction="egress", artifact_id="exp_001")
    await _make_row(repo, "exp_001", object_key=foreign_key)

    result = await finalize_egress_envelope(
        TENANT_A,
        "exp_001",
        content=b"x",
        artifact_repo=repo,
        object_store=store,
    )
    assert result["skipped"] is True
    assert result["reason"] == "object_key_mismatch"
    # No bytes at either the foreign or the tenant-A key.
    assert store.list("data-exchange/") == []


# ── best-effort wrapper ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_try_finalize_swallows_store_fault() -> None:
    """The canonical job's best-effort call must never propagate a bridge fault."""

    class _FailingStore:
        def put(self, key: str, data: bytes) -> None:  # noqa: ARG002
            raise RuntimeError("store unavailable")

        def list(self, prefix: str = "") -> list[str]:
            return []

    repo = DataArtifactRepository()
    await _make_row(repo, "exp_001")
    result = await try_finalize_egress_envelope(
        TENANT_A,
        "exp_001",
        content=b"x",
        content_type="application/json",
        canonical_artifact_id="art_1",
        artifact_repo=repo,
        object_store=_FailingStore(),
    )
    assert result is None
    # The row stays generating; reconcile (M7) will pick it up later.
    row = await repo.get(TENANT_A, "exp_001")
    assert row["status"] == "generating"
