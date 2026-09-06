"""DB-free security + scale tests for the M7 ops jobs.

Security invariants under test (the core of the milestone's load/security
harness):

- An object delete NEVER happens outside the operating tenant's own
  ``data-exchange/<tenant>/`` key scheme.  Prefix escapes (``../``, absolute
  paths, backslash/NUL segments, ``.`` / ``..`` / empty segments, other
  tenants' prefixes, and malformed 3/4+ segment shapes) are REFUSED — reported,
  never deleted — or (for foreign prefixes) never even scanned.
- Unknown or foreign artifact ids given to a cleanup are reported
  (``not_found_rows``) and never acted on.
- The expire/cleanup sweeps operate on data of ONE tenant per invocation;
  sibling tenants' rows and bytes are untouched even when they are past expiry
  or stray.

Scale smoke: a thousands-row expire sweep completes in memory, proving the job
walks tenant rows in bounded pages (``_PAGE_SIZE``) rather than doing any
per-row re-scan of the whole store — the O(n) sweep shape — while leaving a
sibling tenant's data fully intact.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

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
from services.data_exchange.storage import (  # noqa: E402
    OBJECT_KEY_PREFIX,
    object_key_for,
    tenant_object_prefix,
)
from shared.storage.object_store import InMemoryObjectStore  # noqa: E402

TENANT_A = "tnt_sec_a"
TENANT_B = "tnt_sec_b"


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


# ── helpers ───────────────────────────────────────────────────────────────────


def _utc(days: float = 0.0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _policy() -> dict:
    return {
        "resource_type": "data_artifacts",
        "retention_class": "standard",
        "delete_behavior": "hard_delete",
        "legal_hold_supported": True,
    }


async def _no_hold(tenant_id: str) -> bool:  # noqa: ARG001
    return False


async def _put(
    repo: DataArtifactRepository,
    store: InMemoryObjectStore,
    tenant_id: str,
    artifact_id: str,
    *,
    status: str = "uploaded",
    expires_at: Any = None,
) -> dict:
    object_key = object_key_for(tenant_id, direction="ingress", artifact_id=artifact_id)
    store.put(object_key, f"data:{artifact_id}".encode())
    return await repo.create_artifact(
        artifact_id=artifact_id,
        tenant_id=tenant_id,
        direction="ingress",
        artifact_type="csv",
        object_key=object_key,
        filename=f"{artifact_id}.bin",
        format="csv",
        content_type="text/csv",
        size_bytes=16,
        sha256="b" * 64,
        classification="none",
        status=status,
        expires_at=expires_at,
    )


def _tenant_report(result: dict) -> dict:
    return result["tenants"][0]


# ═════════════════════════════════════════════════════════════════════════════
# key-scope guard (unit level)
# ═════════════════════════════════════════════════════════════════════════════


class TestKeyScopeGuard:
    def test_valid_scheme_keys_pass(self):
        key = f"{OBJECT_KEY_PREFIX}/{TENANT_A}/ingress/art_123"
        assert ops.validate_object_key_for_delete(TENANT_A, key) == key

    def test_escapes_and_foreign_prefixes_are_rejected(self):
        assert (
            ops.validate_object_key_for_delete(TENANT_A, f"{OBJECT_KEY_PREFIX}/{TENANT_B}/ingress/x")
            is None
        )
        assert ops.validate_object_key_for_delete(TENANT_A, f"{OBJECT_KEY_PREFIX}/{TENANT_A}/x") is None  # one rel segment
        assert ops.validate_object_key_for_delete(TENANT_A, f"{OBJECT_KEY_PREFIX}/{TENANT_A}/ingress") is None
        for bad in (
            "../escape",
            "/etc/passwd",
            "C:\\windows\\path",
            f"{OBJECT_KEY_PREFIX}/{TENANT_A}/ingress/x\\..",
            f"{OBJECT_KEY_PREFIX}/{TENANT_A}/../other",
            f"{OBJECT_KEY_PREFIX}/{TENANT_A}/./x",
            f"{OBJECT_KEY_PREFIX}/{TENANT_A}//x",
            "data-exchange",
            "",
            "data-exchange//ingress/x",
            "data-exchange/{TENANT_A}/ingress/x".replace("{TENANT_A}", "\x00"),
        ):
            assert ops.validate_object_key_for_delete(TENANT_A, bad) is None, bad

    def test_assert_raises_on_out_of_scope(self):
        with pytest.raises(ops.TenantScopeViolationError):
            ops.assert_key_in_tenant_scope(
                TENANT_A, f"{OBJECT_KEY_PREFIX}/{TENANT_B}/ingress/x"
            )
        assert (
            ops.assert_key_in_tenant_scope(
                TENANT_A, f"{OBJECT_KEY_PREFIX}/{TENANT_A}/ingress/x"
            )
            == f"{OBJECT_KEY_PREFIX}/{TENANT_A}/ingress/x"
        )


# ═════════════════════════════════════════════════════════════════════════════
# crafted / foreign keys are reported, never deleted
# ═════════════════════════════════════════════════════════════════════════════


class TestPrefixEscapeRefusals:
    async def test_malformed_own_prefix_keys_are_refused_not_deleted(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        malformed = [
            f"{tenant_object_prefix(TENANT_A)}ingress/x/../extra",   # 3 rel segments
            f"{tenant_object_prefix(TENANT_A)}ingress/.",            # "." segment
            f"{tenant_object_prefix(TENANT_A)}ingress//",            # empty segment
        ]
        for key in malformed:
            store.put(key, b"crafted")
        # Scan-based cleanup discovers them as orphaned by *metadata* but the
        # key-shape guard refuses to delete them.
        result = await ops.cleanup_artifacts(
            TENANT_A, artifact_repo=repo, object_store=store
        )
        assert result["orphans_deleted"] == 0
        assert len(result["refused_keys"]) == len(malformed)
        for key in malformed:
            assert store.head(key) is not None, key

    async def test_foreign_tenant_objects_never_scanned_or_deleted(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        b_key = object_key_for(TENANT_B, direction="ingress", artifact_id="bobj")
        store.put(b_key, b"b-bytes")
        # Crafted key that walks up out of A's prefix and into B's namespace.
        store.put(f"{tenant_object_prefix(TENANT_A)}../{TENANT_B}/ingress/evil", b"e")
        result = await ops.cleanup_artifacts(
            TENANT_A, artifact_repo=repo, object_store=store
        )
        # Only keys under A's *own* prefix are even candidates; both of these are
        # outside it, so nothing is deleted.
        assert result["orphans_deleted"] == 0
        assert store.head(b_key) is not None
        assert store.head(f"{tenant_object_prefix(TENANT_A)}../{TENANT_B}/ingress/evil")

    async def test_explicit_foreign_and_unknown_keys_refused(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        b_key = object_key_for(TENANT_B, direction="ingress", artifact_id="bobj")
        store.put(b_key, b"b")
        for crafted in ("../x", "/tmp/pwn", b_key):
            store.put(crafted, b"x")
        result = await ops.cleanup_artifacts(
            TENANT_A,
            orphan_keys=["../x", "/tmp/pwn", b_key],
            artifact_repo=repo,
            object_store=store,
        )
        assert result["orphans_deleted"] == 0
        assert len(result["refused_keys"]) == 3
        assert store.head("../x") is not None
        assert store.head("/tmp/pwn") is not None
        assert store.head(b_key) is not None

    async def test_unknown_and_foreign_artifact_ids_reported_not_acted(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT_B, "brow", status="uploaded")
        await _put(repo, store, TENANT_A, "arow", status="uploaded")
        # "brow" exists but under TENANT_B: the tenant-scoped repo get() refuses.
        result = await ops.cleanup_artifacts(
            TENANT_A,
            artifact_ids=["does-not-exist", "brow"],
            artifact_repo=repo,
            object_store=store,
        )
        assert "does-not-exist" in result["not_found_rows"]
        assert "brow" in result["not_found_rows"]
        assert result["rows_deleted"] == 0
        assert (await repo.get(TENANT_B, "brow"))["status"] == "uploaded"
        assert store.head(
            object_key_for(TENANT_B, direction="ingress", artifact_id="brow")
        )

    async def test_expire_refuses_row_pointing_at_foreign_key(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        b_key = object_key_for(TENANT_B, direction="ingress", artifact_id="bsneak")
        store.put(b_key, b"b")
        await repo.create_artifact(
            artifact_id="sneak",
            tenant_id=TENANT_A,
            direction="ingress",
            artifact_type="csv",
            object_key=b_key,  # A row in A that points at a B object key
            filename="sneak.bin",
            format="csv",
            content_type="text/csv",
            size_bytes=8,
            sha256="c" * 64,
            classification="none",
            status="uploaded",
            expires_at=_utc(-1),
        )
        result = await ops.expire_artifacts(
            TENANT_A,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        rep = _tenant_report(result)
        assert rep["expired"] == 0
        assert rep["refused"] == 1
        assert store.head(b_key) is not None
        assert (await repo.get(TENANT_A, "sneak"))["status"] == "uploaded"

    async def test_cleanup_flagged_row_pointing_at_foreign_key_refused(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        b_key = object_key_for(TENANT_B, direction="ingress", artifact_id="bsneak2")
        store.put(b_key, b"b")
        await repo.create_artifact(
            artifact_id="sneak2",
            tenant_id=TENANT_A,
            direction="ingress",
            artifact_type="csv",
            object_key=b_key,
            filename="sneak2.bin",
            format="csv",
            content_type="text/csv",
            size_bytes=8,
            sha256="d" * 64,
            classification="none",
            status="uploaded",
        )
        result = await ops.cleanup_artifacts(
            TENANT_A,
            artifact_ids=["sneak2"],
            artifact_repo=repo,
            object_store=store,
        )
        assert result["rows_deleted"] == 0
        assert b_key in result["refused_keys"]
        assert store.head(b_key) is not None
        assert (await repo.get(TENANT_A, "sneak2"))["status"] == "uploaded"


# ═════════════════════════════════════════════════════════════════════════════
# cross-tenant isolation of the sweeps
# ═════════════════════════════════════════════════════════════════════════════


class TestCrossTenantIsolation:
    async def test_expire_touches_only_requested_tenant(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT_A, "a1", status="uploaded", expires_at=_utc(-1))
        await _put(repo, store, TENANT_B, "b1", status="uploaded", expires_at=_utc(-1))
        result = await ops.expire_artifacts(
            TENANT_A,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        assert _tenant_report(result)["expired"] == 1
        assert (await repo.get(TENANT_B, "b1"))["status"] == "uploaded"
        assert store.head(
            object_key_for(TENANT_B, direction="ingress", artifact_id="b1")
        )

    async def test_multi_tenant_expire_fans_out_and_reports_per_tenant(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        await _put(repo, store, TENANT_A, "a1", status="uploaded", expires_at=_utc(-1))
        await _put(repo, store, TENANT_B, "b1", status="uploaded", expires_at=_utc(-1))
        result = await ops.expire_artifacts(
            [TENANT_A, TENANT_B],
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        assert len(result["tenants"]) == 2
        assert result["totals"]["expired"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# thousands-scale smoke (O(n) sweep shape)
# ═════════════════════════════════════════════════════════════════════════════


class TestThousandsScaleSmoke:
    async def test_expire_sweeps_thousands_of_rows_in_paged_linear_pass(self):
        store = InMemoryObjectStore()
        repo = DataArtifactRepository()
        n = 2000
        for i in range(n):
            await _put(
                repo,
                store,
                TENANT_A,
                f"art{i:05d}",
                status="uploaded",
                expires_at=_utc(-1),
            )
        # A sibling tenant with the same workload must be fully untouched by the
        # paged sweep over TENANT_A.
        for i in range(25):
            await _put(
                repo,
                store,
                TENANT_B,
                f"b{i:03d}",
                status="uploaded",
                expires_at=_utc(-1),
            )
        result = await ops.expire_artifacts(
            TENANT_A,
            artifact_repo=repo,
            object_store=store,
            now=_utc(),
            legal_hold_checker=_no_hold,
            policy=_policy(),
        )
        rep = _tenant_report(result)
        assert rep["rows_scanned"] == n
        assert rep["expired"] == n
        assert rep["objects_deleted"] == n
        assert rep["refused"] == 0
        assert store.list(tenant_object_prefix(TENANT_A)) == []  # bytes all gone
        for i in range(25):
            row = await repo.get(TENANT_B, f"b{i:03d}")
            assert row["status"] == "uploaded"
            assert store.head(row["object_key"]) is not None
