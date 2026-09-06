"""DB-free tests for the M7 data-exchange ops jobs (``services/data_exchange/jobs_ops.py``).

Follows the established DB-free pattern (``test_storage_migration.py`` /
``test_import_envelope.py``): the ``get_pool`` seams across
``repositories.repos`` and ``repositories.data_artifacts`` are pinned to an
async no-op returning None (so the artifact repo uses its module-local
in-memory store), in-memory stores are reset before/after every test, and each
test builds fresh ``InMemoryObjectStore`` + ``DataArtifactRepository`` instances
and injects them (plus injected policies / legal-hold checkers / job loaders) so
no sweep ever touches a real pool, real ObjectStore, policy YAML, or jobs table.

Coverage maps 1:1 to the milestone scenarios: expire flips / untouched rows /
cross-tenant isolation; reconcile missing-object + orphan + consistent cases and
its read-only idempotence; cleanup orphan / flagged-row / cross-tenant refusal;
finalize only terminal-ready stragglers while leaving in-flight and
no-job-record rows alone, plus idempotence; retention decision matrix
(hard_delete vs tombstone vs preserve vs legal-hold).
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from repositories.data_artifacts import (  # noqa: E402
    DataArtifactRepository,
    reset_data_artifact_in_memory_store,
)
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.data_exchange import jobs_ops as ops  # noqa: E402
from services.data_exchange.retention import (  # noqa: E402
    ACTION_HARD_DELETE,
    ACTION_NONE,
    ACTION_PRESERVE,
    ACTION_TOMBSTONE,
    decide_artifact_retention,
)
from services.data_exchange.storage import (  # noqa: E402
    object_key_for,
    tenant_object_prefix,
)
from shared.common.common import (  # noqa: E402
    BadRequestError,
    ConflictError,
)
from shared.storage.object_store import InMemoryObjectStore  # noqa: E402

TENANT = "tnt_jobs_a"


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch):
    async def _no_pool() -> Any:  # noqa: ANN401 — matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    reset_data_artifact_in_memory_store()
    reset_in_memory_stores()
    yield
    reset_data_artifact_in_memory_store()
    reset_in_memory_stores()


# ── local helpers ─────────────────────────────────────────────────────────────


def _utc(days: float = 0.0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _policy(behavior: str = "hard_delete", retention_class: str = "standard") -> dict:
    return {
        "resource_type": "data_artifacts",
        "retention_class": retention_class,
        "delete_behavior": behavior,
        "legal_hold_supported": True,
    }


async def _no_hold(tenant_id: str) -> bool:  # noqa: ARG001
    return False


async def _hold(tenant_id: str) -> bool:  # noqa: ARG001
    return True


async def _put(
    repo: DataArtifactRepository,
    store: InMemoryObjectStore,
    tenant_id: str,
    artifact_id: str,
    *,
    direction: str = "ingress",
    artifact_type: str = "csv",
    status: str = "uploaded",
    expires_at: Any = None,
    created_at: Any = None,
    job_id: Optional[str] = None,
    object_key: Optional[str] = None,
    with_bytes: bool = True,
) -> dict:
    if object_key is None:
        object_key = object_key_for(
            tenant_id, direction=direction, artifact_id=artifact_id
        )
    data = f"data:{artifact_id}".encode()
    if with_bytes:
        store.put(object_key, data)
    return await repo.create_artifact(
        artifact_id=artifact_id,
        tenant_id=tenant_id,
        direction=direction,
        artifact_type=artifact_type,
        object_key=object_key,
        filename=f"{artifact_id}.bin",
        format="csv",
        content_type="text/csv",
        size_bytes=len(data),
        sha256="a" * 64,
        classification="none",
        status=status,
        job_id=job_id,
        expires_at=expires_at,
        created_at=created_at,
    )


def _tenant_report(result: dict) -> dict:
    return result["tenants"][0]


# ═════════════════════════════════════════════════════════════════════════════
# data_exchange.expire_artifacts
# ═════════════════════════════════════════════════════════════════════════════


class TestExpireArtifacts:
    async def test_flips_past_expiry_row_and_deletes_bytes(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(
            repo, store, TENANT, "exp1", status="uploaded", expires_at=_utc(-1)
        )
        result = await ops.expire_artifacts(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        rep = _tenant_report(result)
        assert rep["expired"] == 1
        assert rep["objects_deleted"] == 1
        assert rep["refused"] == 0
        got = await repo.get(TENANT, "exp1")
        assert got["status"] == "expired"
        assert store.head(row["object_key"]) is None

    async def test_expires_past_expiry_available_row_but_leaves_future_and_tombstones(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT, "future", status="uploaded", expires_at=_utc(+2))
        term = await _put(repo, store, TENANT, "term", status="available", expires_at=_utc(-1))
        await _put(repo, store, TENANT, "nokey", status="uploaded", expires_at=_utc(+2))
        await _put(repo, store, TENANT, "tomb", status="expired", expires_at=_utc(-1))
        result = await ops.expire_artifacts(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        rep = _tenant_report(result)
        # A durable-byte ``available`` row past its expires_at IS an expiry
        # candidate: it flips to ``expired`` and its bytes are removed.  Future
        # rows stay put; absorbing tombstones are never re-expired.
        assert rep["expired"] == 1
        assert rep["objects_deleted"] == 1
        assert rep["already_terminal"] == 1
        assert rep["not_eligible"] == 2
        assert (await repo.get(TENANT, "future"))["status"] == "uploaded"
        assert (await repo.get(TENANT, "term"))["status"] == "expired"
        assert store.head(term["object_key"]) is None
        assert (await repo.get(TENANT, "tomb"))["status"] == "expired"
        # Expire never touches absorbing tombstones — its lingering bytes remain
        # for cleanup/reconcile to report as an orphan.
        assert store.head(
            object_key_for(TENANT, direction="ingress", artifact_id="tomb")
        ) is not None

    async def test_expiry_flips_row_to_expired_before_deleting_bytes(self):
        """Ordering doctrine: an ``available`` row never loses bytes while still
        advertising them — the row is tombstoned first, bytes removed second."""

        class _DeleteRaisesStore:
            def __init__(self, inner: InMemoryObjectStore) -> None:
                self._inner = inner

            def head(self, key: str) -> Any:
                return self._inner.head(key)

            def list(self, prefix: str = "") -> list[str]:
                return self._inner.list(prefix)

            def delete(self, key: str) -> bool:  # noqa: ARG002
                raise RuntimeError("simulated delete fault")

        inner = InMemoryObjectStore()
        store = _DeleteRaisesStore(inner)
        repo = DataArtifactRepository()
        row = await _put(
            repo, inner, TENANT, "flipfirst", status="available", expires_at=_utc(-1)
        )
        result = await ops.expire_artifacts(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        rep = _tenant_report(result)
        # The store fault aborts the tenant sweep AFTER the flip: the row must
        # already be ``expired`` (flip-then-bytes), never still ``available``
        # with its durable bytes gone.
        assert "error" in rep
        assert rep.get("expired", 0) == 0
        assert (await repo.get(TENANT, "flipfirst"))["status"] == "expired"
        assert inner.head(row["object_key"]) is not None  # bytes only orphaned

    async def test_never_expires_across_tenants(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, "tnt_a", "a1", status="uploaded", expires_at=_utc(-1))
        await _put(repo, store, "tnt_b", "b1", status="uploaded", expires_at=_utc(-1))
        result = await ops.expire_artifacts(
            "tnt_a",
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        assert result["tenants"][0]["expired"] == 1
        assert (await repo.get("tnt_b", "b1"))["status"] == "uploaded"
        assert store.head(
            object_key_for("tnt_b", direction="ingress", artifact_id="b1")
        )

    async def test_refuses_row_whose_key_escapes_tenant_prefix(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        foreign_key = object_key_for("tnt_b", direction="ingress", artifact_id="bsecret")
        store.put(foreign_key, b"bytes")
        # A tnt_a row that (wrongly) points at a tnt_b object key.
        await _put(
            repo,
            store,
            "tnt_a",
            "sneaky",
            status="uploaded",
            expires_at=_utc(-1),
            object_key=foreign_key,
        )
        result = await ops.expire_artifacts(
            "tnt_a",
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        rep = _tenant_report(result)
        assert rep["expired"] == 0
        assert rep["refused"] == 1
        assert (await repo.get("tnt_a", "sneaky"))["status"] == "uploaded"
        assert store.head(foreign_key) is not None  # foreign bytes untouched

    async def test_legal_hold_blocks_expiry(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT, "held1", status="uploaded", expires_at=_utc(-1))
        result = await ops.expire_artifacts(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_hold,
            policy=_policy(),
        )
        rep = _tenant_report(result)
        assert rep["held"] == 1
        assert rep["expired"] == 0
        assert (await repo.get(TENANT, "held1"))["status"] == "uploaded"
        assert store.head(
            object_key_for(TENANT, direction="ingress", artifact_id="held1")
        )

    async def test_preserve_policy_never_sweeps_and_tombstone_policy_still_expires(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT, "pres", status="uploaded", expires_at=_utc(-1))
        result = await ops.expire_artifacts(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(behavior="preserve"),
        )
        assert _tenant_report(result)["expired"] == 0
        assert (await repo.get(TENANT, "pres"))["status"] == "uploaded"

        # Tombstone delete_behavior still expires past-expiry rows.  The
        # in-memory repo store is module-global, so this second sweep sees both
        # "pres" (still uploaded after the preserve sweep) and "tomb".
        await _put(repo, store, TENANT, "tomb", status="uploaded", expires_at=_utc(-1))
        result = await ops.expire_artifacts(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(behavior="tombstone"),
        )
        rep = _tenant_report(result)
        assert rep["expired"] == 2
        assert rep["objects_deleted"] == 2
        assert (await repo.get(TENANT, "tomb"))["status"] == "expired"
        assert (await repo.get(TENANT, "pres"))["status"] == "expired"

    async def test_row_without_object_bytes_is_still_tombstoned(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(
            repo,
            store,
            TENANT,
            "nobytes",
            status="uploaded",
            expires_at=_utc(-1),
            with_bytes=False,
        )
        result = await ops.expire_artifacts(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        rep = _tenant_report(result)
        assert rep["expired"] == 1
        assert rep["objects_missing"] == 1
        assert (await repo.get(TENANT, "nobytes"))["status"] == "expired"

    async def test_dry_run_mutates_nothing(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "dry1", status="uploaded", expires_at=_utc(-1))
        result = await ops.expire_artifacts(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
            dry_run=True,
        )
        rep = _tenant_report(result)
        assert rep["expired"] == 1  # predicted
        assert (await repo.get(TENANT, "dry1"))["status"] == "uploaded"
        assert store.head(row["object_key"]) is not None


# ═════════════════════════════════════════════════════════════════════════════
# data_exchange.reconcile_artifacts  (read-only)
# ═════════════════════════════════════════════════════════════════════════════


class TestReconcileArtifacts:
    async def test_reports_missing_object_for_live_row(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "miss", status="uploaded")
        store.delete(row["object_key"])  # bytes vanished after the metadata row
        result = await ops.reconcile_artifacts(TENANT, artifact_repo=repo, object_store=store)
        rep = _tenant_report(result)
        assert rep["missing_objects"] == 1
        assert rep["missing_artifact_ids"][0]["artifact_id"] == "miss"
        assert rep["orphan_objects"] == 0
        assert rep["consistent"] == 0

    async def test_reports_orphan_object_with_no_row(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        orphan_key = f"{tenant_object_prefix(TENANT)}ingress/orphan1"
        store.put(orphan_key, b"orphan-bytes")
        result = await ops.reconcile_artifacts(TENANT, artifact_repo=repo, object_store=store)
        rep = _tenant_report(result)
        assert rep["orphan_objects"] == 1
        assert orphan_key in rep["orphan_object_keys"]
        assert rep["missing_objects"] == 0
        assert store.head(orphan_key) is not None  # read-only

    async def test_consistent_row_not_flagged(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT, "good", status="uploaded")
        result = await ops.reconcile_artifacts(TENANT, artifact_repo=repo, object_store=store)
        rep = _tenant_report(result)
        assert rep["consistent"] == 1
        assert rep["missing_objects"] == 0
        assert rep["orphan_objects"] == 0

    async def test_tombstone_row_without_bytes_is_informational_not_missing(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(
            repo, store, TENANT, "gone", status="expired", with_bytes=False
        )
        result = await ops.reconcile_artifacts(TENANT, artifact_repo=repo, object_store=store)
        rep = _tenant_report(result)
        assert rep["missing_objects"] == 0
        assert rep["tombstoned_without_bytes"] == 1

    async def test_available_row_without_bytes_is_a_missing_anomaly(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "availmiss", status="available")
        store.delete(row["object_key"])  # durable bytes vanished
        result = await ops.reconcile_artifacts(TENANT, artifact_repo=repo, object_store=store)
        rep = _tenant_report(result)
        assert rep["missing_objects"] == 1
        assert rep["missing_artifact_ids"][0]["artifact_id"] == "availmiss"
        assert rep["tombstoned_without_bytes"] == 0  # NOT hidden as a tombstone

    async def test_tombstone_with_lingering_bytes_is_reported_orphan(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "ling", status="expired")  # bytes remain
        result = await ops.reconcile_artifacts(TENANT, artifact_repo=repo, object_store=store)
        rep = _tenant_report(result)
        assert rep["orphan_objects"] == 1
        assert row["object_key"] in rep["orphan_object_keys"]
        assert rep["missing_objects"] == 0
        assert rep["consistent"] == 0  # a tombstone owns no bytes

    async def test_reconcile_is_idempotent_and_read_only(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "miss", status="uploaded")
        store.delete(row["object_key"])
        store.put(f"{tenant_object_prefix(TENANT)}ingress/orphan_x", b"o")
        before_status = (await repo.get(TENANT, "miss"))["status"]
        first = await ops.reconcile_artifacts(
            TENANT, artifact_repo=repo, object_store=store
        )
        second = await ops.reconcile_artifacts(
            TENANT, artifact_repo=repo, object_store=store
        )
        assert first["totals"] == second["totals"]
        assert (await repo.get(TENANT, "miss"))["status"] == before_status
        assert store.head(row["object_key"]) is None


# ═════════════════════════════════════════════════════════════════════════════
# data_exchange.cleanup_artifacts
# ═════════════════════════════════════════════════════════════════════════════


class TestCleanupArtifacts:
    async def test_deletes_explicit_orphan_key(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        orphan_key = f"{tenant_object_prefix(TENANT)}ingress/orphan1"
        store.put(orphan_key, b"o")
        result = await ops.cleanup_artifacts(
            TENANT,
            orphan_keys=[orphan_key],
            artifact_repo=repo,
            object_store=store,
        )
        assert result["orphans_deleted"] == 1
        assert store.head(orphan_key) is None

    async def test_scans_and_deletes_orphans_but_keeps_referenced_rows(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT, "keep", status="uploaded")
        store.put(f"{tenant_object_prefix(TENANT)}ingress/stray1", b"o")
        store.put(f"{tenant_object_prefix(TENANT)}ingress/stray2", b"o")
        result = await ops.cleanup_artifacts(TENANT, artifact_repo=repo, object_store=store)
        assert result["orphans_deleted"] == 2
        assert store.head(
            object_key_for(TENANT, direction="ingress", artifact_id="keep")
        ) is not None
        assert (await repo.get(TENANT, "keep"))["status"] == "uploaded"

    async def test_tombstones_flagged_row_and_removes_bytes(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "flag1", status="uploaded")
        result = await ops.cleanup_artifacts(
            TENANT,
            artifact_ids=["flag1"],
            artifact_repo=repo,
            object_store=store,
        )
        assert result["rows_deleted"] == 1
        assert (await repo.get(TENANT, "flag1"))["status"] == "deleted"
        assert store.head(row["object_key"]) is None

    async def test_unknown_and_foreign_flagged_rows_reported_not_deleted(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, "tnt_b", "brow", status="uploaded")
        result = await ops.cleanup_artifacts(
            TENANT,
            artifact_ids=["no_such_id", "brow"],  # "brow" belongs to tnt_b
            artifact_repo=repo,
            object_store=store,
        )
        assert "no_such_id" in result["not_found_rows"]
        assert "brow" in result["not_found_rows"]
        assert result["rows_deleted"] == 0
        assert (await repo.get("tnt_b", "brow"))["status"] == "uploaded"

    async def test_refuses_cross_tenant_and_crafted_keys(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        foreign_key = object_key_for("tnt_b", direction="ingress", artifact_id="x")
        store.put(foreign_key, b"foreign-bytes")
        for bad in ("../escape", "/etc/passwd", "data-exchange/other/ingress/y"):
            store.put(bad, b"crafted")
        result = await ops.cleanup_artifacts(
            TENANT,
            orphan_keys=[foreign_key, "../escape", "/etc/passwd"],
            artifact_repo=repo,
            object_store=store,
        )
        assert result["orphans_deleted"] == 0
        assert len(result["refused_keys"]) == 3
        assert store.head(foreign_key) is not None
        assert store.head("../escape") is not None
        assert store.head("/etc/passwd") is not None
        # A crafted key under OUR prefix that is not scheme-shaped is refused too.
        result2 = await ops.cleanup_artifacts(
            TENANT,
            orphan_keys=["data-exchange/other/ingress/y"],
            artifact_repo=repo,
            object_store=store,
        )
        assert result2["orphans_deleted"] == 0
        assert store.head("data-exchange/other/ingress/y") is not None

    async def test_cleanup_does_not_touch_other_tenants(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, "tnt_b", "b1", status="uploaded")
        store.put(f"{tenant_object_prefix('tnt_b')}ingress/bstray", b"o")
        await _put(repo, store, TENANT, "a1", status="uploaded")
        result = await ops.cleanup_artifacts(TENANT, artifact_repo=repo, object_store=store)
        assert result["orphans_deleted"] == 0  # nothing stray under tnt_a
        assert store.head(
            object_key_for("tnt_b", direction="ingress", artifact_id="b1")
        )
        assert store.head(f"{tenant_object_prefix('tnt_b')}ingress/bstray")
        assert (await repo.get("tnt_b", "b1"))["status"] == "uploaded"

    async def test_purges_lingering_payload_under_tombstone_row(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "ling", status="expired")
        # Simulate an interrupted earlier delete: row tombstoned, bytes remain.
        assert store.head(row["object_key"]) is not None
        result = await ops.cleanup_artifacts(TENANT, artifact_repo=repo, object_store=store)
        assert result["lingering_payloads_purged"] == 1
        assert store.head(row["object_key"]) is None

    async def test_cleanup_never_purges_durable_or_transient_payloads(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        avail = await _put(repo, store, TENANT, "avail", status="available")
        trans = await _put(repo, store, TENANT, "trans", status="uploaded")
        ling = await _put(repo, store, TENANT, "ling", status="expired")  # tombstone w/ bytes
        result = await ops.cleanup_artifacts(TENANT, artifact_repo=repo, object_store=store)
        # Only the absorbing tombstone's lingering payload is purged.
        assert result["lingering_payloads_purged"] == 1
        assert result["orphans_deleted"] == 0
        assert store.head(avail["object_key"]) is not None
        assert store.head(trans["object_key"]) is not None
        assert store.head(ling["object_key"]) is None
        assert (await repo.get(TENANT, "avail"))["status"] == "available"
        assert (await repo.get(TENANT, "trans"))["status"] == "uploaded"

    async def test_cleanup_flagged_durable_row_is_tombstoned_and_bytes_removed(self):
        # An explicitly-flagged durable row IS deletable (operator intent):
        # tombstone to ``deleted`` first, then purge its bytes.
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "flagavail", status="available")
        result = await ops.cleanup_artifacts(
            TENANT,
            artifact_ids=["flagavail"],
            artifact_repo=repo,
            object_store=store,
        )
        assert result["rows_deleted"] == 1
        assert (await repo.get(TENANT, "flagavail"))["status"] == "deleted"
        assert store.head(row["object_key"]) is None

    async def test_cleanup_flagged_already_tombstoned_row_purges_without_retransition(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "expflag", status="expired")  # bytes remain
        result = await ops.cleanup_artifacts(
            TENANT,
            artifact_ids=["expflag"],
            artifact_repo=repo,
            object_store=store,
        )
        assert result["rows_already_tombstoned"] == 1
        assert result["rows_deleted"] == 0
        # An absorbing tombstone is not re-transitioned (no outgoing moves); its
        # bytes are still purged as lingering payload.
        assert (await repo.get(TENANT, "expflag"))["status"] == "expired"
        assert store.head(row["object_key"]) is None

    async def test_dry_run_mutates_nothing(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        row = await _put(repo, store, TENANT, "flag2", status="uploaded")
        orphan_key = f"{tenant_object_prefix(TENANT)}ingress/stray3"
        store.put(orphan_key, b"o")
        result = await ops.cleanup_artifacts(
            TENANT,
            orphan_keys=[orphan_key],
            artifact_ids=["flag2"],
            artifact_repo=repo,
            object_store=store,
            dry_run=True,
        )
        assert result["orphans_deleted"] == 1
        assert result["rows_deleted"] == 1
        assert store.head(orphan_key) is not None
        assert (await repo.get(TENANT, "flag2"))["status"] == "uploaded"


# ═════════════════════════════════════════════════════════════════════════════
# data_exchange.finalize_pending_egress
# ═════════════════════════════════════════════════════════════════════════════


def _job_loader(status_by_job: dict[str, str]) -> Callable[[str, str], Any]:
    async def _loader(tenant_id: str, job_id: str) -> Optional[str]:
        return status_by_job.get(job_id)

    return _loader


def _egress(
    repo: DataArtifactRepository,
    store: InMemoryObjectStore,
    artifact_id: str,
    *,
    artifact_type: str = "report",
    status: str = "generating",
    job_id: Optional[str] = "job-1",
    with_bytes: bool = True,
) -> Any:
    return _put(
        repo,
        store,
        TENANT,
        artifact_id,
        direction="egress",
        artifact_type=artifact_type,
        status=status,
        job_id=job_id,
        with_bytes=with_bytes,
    )


class TestFinalizePendingEgress:
    async def test_flips_succeeded_with_bytes_to_available(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _egress(repo, store, "eg1", artifact_type="report", job_id="job-s1")
        result = await ops.finalize_pending_egress(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            job_loader=_job_loader({"job-s1": "succeeded"}),
        )
        assert result["finalized_available"] == 1
        assert (await repo.get(TENANT, "eg1"))["status"] == "available"

    async def test_flips_failed_and_cancelled_to_failed(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _egress(repo, store, "egf", job_id="job-f1")
        await _egress(repo, store, "egc", job_id="job-c1")
        result = await ops.finalize_pending_egress(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            job_loader=_job_loader({"job-f1": "failed", "job-c1": "cancelled"}),
        )
        assert result["finalized_failed"] == 2
        assert (await repo.get(TENANT, "egf"))["status"] == "failed"
        assert (await repo.get(TENANT, "egc"))["status"] == "failed"

    async def test_leaves_in_flight_success_without_bytes_and_no_job_record(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _egress(repo, store, "live", job_id="job-live")          # running
        await _egress(
            repo, store, "nobytes", job_id="job-s2", with_bytes=False  # succeeded, no bytes
        )
        await _egress(repo, store, "nostatus", job_id="job-nope")      # no job record
        result = await ops.finalize_pending_egress(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            job_loader=_job_loader(
                {"job-live": "running", "job-s2": "succeeded", "job-nope": "whatever"}
            ),
        )
        assert result["in_flight"] == 1
        assert result["success_without_bytes"] == 1
        assert result["no_job_record"] == 1
        assert result["finalized_available"] == 0
        assert (await repo.get(TENANT, "live"))["status"] == "generating"
        assert (await repo.get(TENANT, "nobytes"))["status"] == "generating"
        assert (await repo.get(TENANT, "nostatus"))["status"] == "generating"

    async def test_job_record_missing_or_no_job_id_left_for_review(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _egress(repo, store, "none1", job_id="job-ghost")  # loader returns None
        await _egress(repo, store, "none2", job_id=None)
        result = await ops.finalize_pending_egress(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            job_loader=_job_loader({}),  # loader itself returns None for everything
        )
        assert result["no_job_record"] == 2
        assert result["finalized_available"] == 0
        assert (await repo.get(TENANT, "none1"))["status"] == "generating"
        assert (await repo.get(TENANT, "none2"))["status"] == "generating"

    async def test_idempotent_second_run_scans_nothing(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _egress(repo, store, "eg2", artifact_type="export", job_id="job-s3")
        loader = _job_loader({"job-s3": "succeeded"})
        first = await ops.finalize_pending_egress(
            TENANT, artifact_repo=repo, object_store=store, job_loader=loader
        )
        second = await ops.finalize_pending_egress(
            TENANT, artifact_repo=repo, object_store=store, job_loader=loader
        )
        assert first["finalized_available"] == 1
        assert second["rows_scanned"] == 0  # row is terminal now — no stragglers
        assert second["finalized_available"] == 0

    async def test_flip_to_available_backfills_verified_size_and_sha(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _egress(repo, store, "egv", artifact_type="report", job_id="job-sv")
        result = await ops.finalize_pending_egress(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            job_loader=_job_loader({"job-sv": "succeeded"}),
        )
        assert result["finalized_available"] == 1
        got = await repo.get(TENANT, "egv")
        assert got["status"] == "available"
        content = b"data:egv"
        assert got["size_bytes"] == len(content)
        assert got["sha256"] == hashlib.sha256(content).hexdigest()
        # Real metadata is back-filled via verified mark_available — the flip is
        # never a bare update_status that would leave the sentinel sha behind.
        assert got["sha256"] != "a" * 64

    async def test_succeeded_job_with_out_of_scope_key_never_fabricates_available(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        foreign_key = object_key_for("tnt_other", direction="egress", artifact_id="rogue")
        store.put(foreign_key, b"bytes")
        await _put(
            repo,
            store,
            TENANT,
            "rogue",
            direction="egress",
            artifact_type="export",
            status="generating",
            job_id="job-rogue",
            object_key=foreign_key,  # a row pointing OUTSIDE its tenant prefix
        )
        result = await ops.finalize_pending_egress(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            job_loader=_job_loader({"job-rogue": "succeeded"}),
        )
        assert result["finalized_available"] == 0
        assert result["success_without_bytes"] == 1
        assert (await repo.get(TENANT, "rogue"))["status"] == "generating"
        assert store.head(foreign_key) is not None  # foreign bytes untouched

    async def test_never_touches_non_egress_or_other_types(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT, "ing1", direction="ingress", status="uploaded")
        await _egress(repo, store, "other", artifact_type="ingress_thing", job_id="j-x")
        result = await ops.finalize_pending_egress(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            job_loader=_job_loader({"j-x": "succeeded"}),
        )
        assert result["rows_scanned"] == 0
        assert (await repo.get(TENANT, "ing1"))["status"] == "uploaded"
        assert (await repo.get(TENANT, "other"))["status"] == "generating"

    async def test_dry_run_mutates_nothing(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _egress(repo, store, "eg3", job_id="job-s4")
        result = await ops.finalize_pending_egress(
            TENANT,
            artifact_repo=repo,
            object_store=store,
            job_loader=_job_loader({"job-s4": "succeeded"}),
            dry_run=True,
        )
        assert result["finalized_available"] == 1
        assert (await repo.get(TENANT, "eg3"))["status"] == "generating"


# ═════════════════════════════════════════════════════════════════════════════
# pure retention decision matrix  (services/data_exchange/retention.py)
# ═════════════════════════════════════════════════════════════════════════════


class TestRetentionDecisions:
    def _row(self, artifact_id: str = "r1", status: str = "uploaded", **extra: Any) -> dict:
        row: dict[str, Any] = {
            "artifact_id": artifact_id,
            "status": status,
            "created_at": _utc(-10),
        }
        row.update(extra)
        return row

    def test_past_expiry_hard_delete(self):
        d = decide_artifact_retention(
            self._row(expires_at=_utc(-1)), policy=_policy(), now=_utc()
        )
        assert d["expire_eligible"] is True
        assert d["action"] == ACTION_HARD_DELETE
        assert d["reason"] == "expires_at_past"

    def test_future_expiry_not_eligible(self):
        d = decide_artifact_retention(
            self._row(expires_at=_utc(+5)), policy=_policy(), now=_utc()
        )
        assert d["expire_eligible"] is False
        assert d["action"] == ACTION_NONE
        assert d["reason"] == "not_past_retention"

    def test_absorbing_tombstone_never_eligible(self):
        for tombstone in ("expired", "deleted", "failed", "revoked"):
            d = decide_artifact_retention(
                self._row(status=tombstone, expires_at=_utc(-1)),
                policy=_policy(),
                now=_utc(),
            )
            assert d["expire_eligible"] is False
            assert d["action"] == ACTION_NONE
            assert d["reason"] == "already_terminal"

    def test_durable_byte_row_past_expiry_is_eligible(self):
        for durable in ("available", "committed", "partially_committed"):
            d = decide_artifact_retention(
                self._row(status=durable, expires_at=_utc(-1)),
                policy=_policy(),
                now=_utc(),
            )
            assert d["expire_eligible"] is True
            assert d["action"] == ACTION_HARD_DELETE
            assert d["reason"] == "expires_at_past"

    def test_durable_byte_row_future_expiry_not_eligible(self):
        d = decide_artifact_retention(
            self._row(status="available", expires_at=_utc(+5)),
            policy=_policy(),
            now=_utc(),
        )
        assert d["expire_eligible"] is False
        assert d["action"] == ACTION_NONE
        assert d["reason"] == "not_past_retention"

    def test_legal_hold_blocks_even_when_past(self):
        d = decide_artifact_retention(
            self._row(expires_at=_utc(-1)),
            policy=_policy(),
            now=_utc(),
            legal_hold_blocked=True,
        )
        assert d["expire_eligible"] is False
        assert d["action"] == ACTION_NONE
        assert d["reason"] == "legal_hold"

    def test_preserve_policy_never_swept(self):
        d = decide_artifact_retention(
            self._row(expires_at=_utc(-1)),
            policy=_policy(behavior="preserve"),
            now=_utc(),
        )
        assert d["action"] == ACTION_PRESERVE
        assert d["reason"] == "preserve_never_swept"

    def test_legal_retention_class_compliance_owned(self):
        d = decide_artifact_retention(
            self._row(expires_at=_utc(-1)),
            policy=_policy(retention_class="legal"),
            now=_utc(),
        )
        assert d["expire_eligible"] is False
        assert d["reason"] == "legal_retention_compliance_owned"

    def test_tombstone_behavior_gives_tombstone_action(self):
        d = decide_artifact_retention(
            self._row(expires_at=_utc(-1)),
            policy=_policy(behavior="tombstone"),
            now=_utc(),
        )
        assert d["action"] == ACTION_TOMBSTONE
        assert d["expire_eligible"] is True

    def test_policy_default_ttl_window_for_expires_at_less_rows(self):
        row = self._row(created_at=_utc(-400))  # no expires_at, older than a year
        d = decide_artifact_retention(
            row,
            policy=_policy(),
            now=_utc(),
            apply_policy_default_ttl=True,
            standard_retention_days=365,
        )
        assert d["expire_eligible"] is True
        assert d["reason"] == "past_policy_window"
        # Without opt-in the same row is NOT eligible.
        d2 = decide_artifact_retention(row, policy=_policy(), now=_utc())
        assert d2["expire_eligible"] is False

    def test_unparseable_expires_at_never_triggers_delete(self):
        d = decide_artifact_retention(
            self._row(expires_at="not-a-timestamp"),
            policy=_policy(),
            now=_utc(),
        )
        assert d["expire_eligible"] is False
        assert d["action"] == ACTION_NONE


# ═════════════════════════════════════════════════════════════════════════════
# data_artifacts update_status / mark_available doctrine
# ═════════════════════════════════════════════════════════════════════════════


class TestArtifactStatusDoctrine:
    async def test_update_status_rejects_resurrection_from_tombstone(self):
        repo = DataArtifactRepository()
        for tomb in ("deleted", "expired", "failed", "revoked"):
            aid = f"t-{tomb}"
            await _put(repo, InMemoryObjectStore(), TENANT, aid, status=tomb)
            # No resurrection to a durable-byte state …
            with pytest.raises(ConflictError):
                await repo.update_status(TENANT, aid, "available")
            # … and no outgoing transition to a live transient either.
            with pytest.raises(ConflictError):
                await repo.update_status(TENANT, aid, "uploaded")

    async def test_update_status_rejects_promotion_to_durable_by_flip(self):
        repo = DataArtifactRepository()
        await _put(repo, InMemoryObjectStore(), TENANT, "gen1", status="generating")
        with pytest.raises(ConflictError):
            await repo.update_status(TENANT, "gen1", "available")

    async def test_update_status_durable_only_tombstones_not_failed_or_live(self):
        repo = DataArtifactRepository()
        await _put(repo, InMemoryObjectStore(), TENANT, "du1", status="available")
        with pytest.raises(ConflictError):
            await repo.update_status(TENANT, "du1", "failed")
        with pytest.raises(ConflictError):
            await repo.update_status(TENANT, "du1", "uploaded")
        deleted = await repo.update_status(TENANT, "du1", "deleted")
        assert deleted["status"] == "deleted"

    async def test_update_status_failed_moves_only_to_deleted(self):
        repo = DataArtifactRepository()
        await _put(repo, InMemoryObjectStore(), TENANT, "f1", status="failed")
        with pytest.raises(ConflictError):
            await repo.update_status(TENANT, "f1", "expired")
        gone = await repo.update_status(TENANT, "f1", "deleted")
        assert gone["status"] == "deleted"

    async def test_mark_available_refuses_tombstones(self):
        repo = DataArtifactRepository()
        for tomb in ("deleted", "expired", "failed", "revoked"):
            aid = f"mk-{tomb}"
            await _put(repo, InMemoryObjectStore(), TENANT, aid, status=tomb)
            with pytest.raises(ConflictError):
                await repo.mark_available(TENANT, aid, size_bytes=3, sha256="a" * 64)

    async def test_mark_available_requires_verified_sha_and_is_idempotent(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT, "mk3", status="generating")
        with pytest.raises(BadRequestError):
            await repo.mark_available(TENANT, "mk3", size_bytes=3, sha256="")
        with pytest.raises(BadRequestError):
            await repo.mark_available(TENANT, "mk3", size_bytes=-1, sha256="a" * 64)

        got = await repo.mark_available(TENANT, "mk3", size_bytes=7, sha256="b" * 64)
        assert got["status"] == "available"
        assert got["size_bytes"] == 7
        assert got["sha256"] == "b" * 64
        assert got["source_or_destination"].get("materialized") is True

        # Idempotent on an already-available row: real metadata is never clobbered.
        again = await repo.mark_available(TENANT, "mk3", size_bytes=99, sha256="c" * 64)
        assert again["size_bytes"] == 7
        assert again["sha256"] == "b" * 64


# ═════════════════════════════════════════════════════════════════════════════
# handlers + registration
# ═════════════════════════════════════════════════════════════════════════════


class TestHandlerAdapters:
    async def test_register_is_idempotent(self):
        ops.register()
        ops.register()  # must not raise on duplicate registration
        from services.jobs.handlers import HANDLER_REGISTRY

        assert all(jt in HANDLER_REGISTRY for jt in ops.DATA_EXCHANGE_OPS_JOB_TYPES)

    async def test_expire_handler_adapter_routes_payload(self, monkeypatch: pytest.MonkeyPatch):
        captured: list[tuple[Any, dict]] = []

        async def _fake(tenant_ids: Any, **kwargs: Any) -> dict:
            captured.append((tenant_ids, kwargs))
            return {"fake": True}

        monkeypatch.setattr(ops, "expire_artifacts", _fake)
        ctx = SimpleNamespace(tenant_id=TENANT, heartbeat=None)
        out = await ops.expire_artifacts_job({"tenant_id": TENANT}, ctx)
        assert out.status == "succeeded"
        assert captured[0][0] == [TENANT]

    async def test_cleanup_handler_adapter_routes_payload(self, monkeypatch: pytest.MonkeyPatch):
        captured: list[tuple[Any, dict]] = []

        async def _fake(tenant_id: str, **kwargs: Any) -> dict:
            captured.append((tenant_id, kwargs))
            return {"fake": True}

        monkeypatch.setattr(ops, "cleanup_artifacts", _fake)
        ctx = SimpleNamespace(tenant_id=TENANT, heartbeat=None)
        out = await ops.cleanup_artifacts_job(
            {"tenant_id": TENANT, "orphan_keys": ["k1"]}, ctx
        )
        assert out.status == "succeeded"
        assert captured[0][0] == TENANT
        assert captured[0][1]["orphan_keys"] == ["k1"]

    async def test_reconcile_and_finalize_handlers_return_job_outcome(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from services.jobs.handlers import JobOutcome

        captured_r: list[tuple[Any, dict]] = []
        captured_f: list[tuple[Any, dict]] = []

        async def _fake_reconcile(tenant_ids: Any, **kwargs: Any) -> dict:
            captured_r.append((tenant_ids, kwargs))
            return {"totals": {"missing_objects": 0, "orphan_objects": 0}}

        async def _fake_finalize(tenant_id: str, **kwargs: Any) -> dict:
            captured_f.append((tenant_id, kwargs))
            return {"rows_scanned": 0, "dry_run": False}

        monkeypatch.setattr(ops, "reconcile_artifacts", _fake_reconcile)
        monkeypatch.setattr(ops, "finalize_pending_egress", _fake_finalize)
        ctx = SimpleNamespace(tenant_id="tnt_empty", heartbeat=None)
        out_r = await ops.reconcile_artifacts_job({"tenant_id": "tnt_empty"}, ctx)
        assert isinstance(out_r, JobOutcome)
        assert out_r.status == "succeeded"
        assert captured_r[0][0] == ["tnt_empty"]
        out_f = await ops.finalize_pending_egress_job({"tenant_id": "tnt_empty"}, ctx)
        assert out_f.status == "succeeded"
        assert out_f.result["rows_scanned"] == 0
        assert captured_f[0][0] == "tnt_empty"
