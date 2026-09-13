"""DB-free tests for Data Exchange Plane M2 — signed transfers.

Covers the M2 security contract from ``docs/plans/data-exchange-api.md`` M2 with
no Postgres (in-memory ``data_artifacts`` repository + ``InMemoryObjectStore``,
matching the M1 test harness):

- signed/unforgeable transfer URLs (tampering the object scope breaks the
  signature);
- token/tenant binding (a URL is minted only from a tenant-owned row; a second
  tenant or a different artifact cannot reuse it; re-targeting is refused);
- expiry enforcement (the signed window is honored by the store);
- upload-complete server-side verify (size + sha256 match required; mismatch
  and absent bytes rejected);
- revoked/expired/deleted artifacts refuse download; downloads are minted only
  for ``available``/``committed`` artifacts;
- availability: a non-presign-capable store surfaces the canonical 503;
- route shape + permission gates (``data_exchange`` grants, fail-closed).

The event seam (``transfers._emit``) and the canonical audit sink
(``audit_ledger.record``) are stubbed with recorders so assertions stay DB-free
and bus-free; the service's real ``_record_download_audit`` runs so the captured
audit record carries the canonical ledger field names (``resource_id``, …).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from repositories.data_artifacts import (
    DataArtifactRepository,
    reset_data_artifact_in_memory_store,
)
from repositories.repos import reset_in_memory_stores
from services.data_exchange import transfers as transfers_mod
from services.data_exchange.routes_transfer import (
    DOWNLOAD_REQUIRED_GRANTS,
    UPLOAD_REQUIRED_GRANTS,
    UploadCompleteBody,
    upload_complete,
    upload_url,
)
from services.data_exchange.routes_transfer import download_url as route_download_url
from services.data_exchange.transfers import (
    DOWNLOAD_URL_ISSUED_TOPIC,
    UPLOAD_COMPLETE_TOPIC,
    ObjectTransferService,
)
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError, ServiceUnavailableError
from shared.storage.object_store import InMemoryObjectStore, PresignableObjectStore

TENANT_A = "tnt_a"
TENANT_B = "tnt_b"

_BASE = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key(tenant_id: str, direction: str, artifact_id: str) -> str:
    return f"data-exchange/{tenant_id}/{direction}/{artifact_id}"


class _MutableClock:
    """Test clock: presigned-window + service-time controls in one object."""

    def __init__(self, start: Optional[datetime] = None) -> None:
        self.now = start or _BASE

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


class _PlainObjectStore:
    """An ObjectStore that cannot presign (for the availability gate test)."""

    def __init__(self) -> None:
        self._inner = InMemoryObjectStore()

    def put(self, key: str, data: bytes) -> None:
        self._inner.put(key, data)

    def get(self, key: str) -> bytes:
        return self._inner.get(key)

    def head(self, key: str):  # noqa: ANN201 - mirrors protocol
        return self._inner.head(key)

    def delete(self, key: str) -> bool:
        return self._inner.delete(key)

    def list(self, prefix: str = "") -> list[str]:
        return self._inner.list(prefix)


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Guarantee in-memory backends + silent audit/event sinks per test.

    The audit seam spies at the canonical sink (``audit_ledger.record``) rather
    than stubbing ``transfers._record_download_audit`` so the real helper runs
    and the captured record uses the canonical ledger field names (resource_id,
    action, outcome, …) — consistent with how audit records are asserted across
    the suite.
    """

    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)

    emitted: list[tuple[str, str, dict]] = []
    audited: list[dict] = []

    async def _emit_spy(topic_name: str, tenant_id: str, payload: dict) -> None:
        emitted.append((topic_name, tenant_id, payload))

    async def _audit_spy(**kwargs: Any) -> None:
        # Captures the canonical audit_ledger.record(**kwargs) shape.
        audited.append(kwargs)

    monkeypatch.setattr(transfers_mod, "_emit", _emit_spy)
    monkeypatch.setattr(
        "services.security.audit_ledger.audit_ledger.record", _audit_spy
    )

    reset_data_artifact_in_memory_store()
    reset_in_memory_stores()
    yield SimpleNamespace(emitted=emitted, audited=audited)
    reset_data_artifact_in_memory_store()
    reset_in_memory_stores()


async def _make(
    repo: DataArtifactRepository,
    artifact_id: str,
    tenant_id: str,
    *,
    direction: str = "ingress",
    status: str = "created",
    size_bytes: int = 0,
    sha256: Optional[str] = None,
    object_key: Optional[str] = None,
    artifact_type: str = "import_source",
    expires_at: Any = None,
) -> dict:
    return await repo.create_artifact(
        artifact_id,
        tenant_id,
        direction=direction,
        artifact_type=artifact_type,
        object_key=object_key or _key(tenant_id, direction, artifact_id),
        filename=f"{artifact_id}.csv",
        format="csv",
        content_type="text/csv",
        size_bytes=size_bytes,
        sha256=sha256 or "0" * 64,
        classification="none",
        status=status,
        expires_at=expires_at,
    )


# ── presigned-URL seam: unforgeable + bound + expiring ──────────────────────


def test_presigned_put_url_is_signed_bound_and_unforgeable() -> None:
    store = InMemoryObjectStore(clock=_MutableClock())
    assert isinstance(store, PresignableObjectStore)

    key = _key(TENANT_A, "ingress", "art1")
    transfer = store.create_presigned_put_url(key, tenant_id=TENANT_A, expires_in_seconds=900)
    assert transfer.method == "PUT"
    assert transfer.expires_at
    assert transfer.url.startswith("aether-memory-put://local/")

    # Tampering the object scope invalidates the signature (cannot re-target to
    # a different artifact).
    tampered = transfer.url.replace("art1", "art2")
    with pytest.raises(ValueError):
        store.perform_presigned_put(tampered, b"x")

    # Re-targeting the tenant scope is equally refused.
    tenant_tampered = transfer.url.replace(f"x-aether-tenant={TENANT_A}", f"x-aether-tenant={TENANT_B}")
    with pytest.raises(ValueError):
        store.perform_presigned_put(tenant_tampered, b"x")

    # An expired window is refused even with a valid signature.
    clock = _MutableClock()
    short = InMemoryObjectStore(clock=clock)
    t2 = short.create_presigned_put_url(key, tenant_id=TENANT_A, expires_in_seconds=60)
    clock.advance(61)
    with pytest.raises(ValueError):
        short.perform_presigned_put(t2.url, b"x")

    # A fresh URL performs exactly the bound write.
    clock2 = _MutableClock()
    ok = InMemoryObjectStore(clock=clock2)
    t3 = ok.create_presigned_put_url(key, tenant_id=TENANT_A, expires_in_seconds=60)
    resolved = ok.perform_presigned_put(t3.url, b"payload")
    assert resolved == key
    assert ok.get(key) == b"payload"


def test_presigned_get_url_round_trips_and_expires() -> None:
    clock = _MutableClock()
    store = InMemoryObjectStore(clock=clock)
    key = _key(TENANT_A, "egress", "exp1")
    store.put(key, b"data")
    transfer = store.create_presigned_get_url(key, tenant_id=TENANT_A, expires_in_seconds=60)
    assert store.perform_presigned_get(transfer.url) == b"data"
    clock.advance(61)
    with pytest.raises(ValueError):
        store.perform_presigned_get(transfer.url)


# ── issue_upload_url ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_upload_url_returns_put_and_moves_to_upload_pending() -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)
    await _make(repo, "art1", TENANT_A, status="created")

    result = await svc.issue_upload_url(TENANT_A, "art1")
    assert result["artifact_id"] == "art1"
    assert result["object_key"] == _key(TENANT_A, "ingress", "art1")
    assert result["upload_method"] == "PUT"
    assert result["status"] == "upload_pending"
    assert result["expires_at"]
    row = await repo.get(TENANT_A, "art1")
    assert row["status"] == "upload_pending"

    # Re-issue from upload_pending is allowed and stays put.
    again = await svc.issue_upload_url(TENANT_A, "art1", expires_in_seconds=60)
    assert again["status"] == "upload_pending"


@pytest.mark.asyncio
async def test_issue_upload_url_refuses_wrong_states() -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)

    # Artifacts that already have durable bytes cannot accept a signed upload.
    await _make(repo, "up", TENANT_A, status="uploaded", size_bytes=4, sha256=_sha(b"data"))
    with pytest.raises(BadRequestError):
        await svc.issue_upload_url(TENANT_A, "up")

    # Terminal tombstones refuse.
    await _make(repo, "gone", TENANT_A, status="deleted")
    with pytest.raises(BadRequestError):
        await svc.issue_upload_url(TENANT_A, "gone")

    # Cross-tenant issuance fails closed (NotFound, never reveals the row).
    await _make(repo, "owned", TENANT_B, status="created")
    with pytest.raises(NotFoundError):
        await svc.issue_upload_url(TENANT_A, "owned")

    # A tenant-owned row whose object key escaped the tenant prefix is refused.
    await repo.create_artifact(
        "escaped",
        TENANT_A,
        direction="ingress",
        artifact_type="import_source",
        object_key=f"data-exchange/{TENANT_B}/ingress/escaped",
        filename="e.csv",
        format="csv",
        content_type="text/csv",
        size_bytes=0,
        sha256="0" * 64,
        classification="none",
        status="created",
    )
    with pytest.raises(BadRequestError):
        await svc.issue_upload_url(TENANT_A, "escaped")


@pytest.mark.asyncio
async def test_issue_upload_url_requires_presignable_store() -> None:
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=_PlainObjectStore(), artifact_repo=repo)
    await _make(repo, "art1", TENANT_A, status="created")
    with pytest.raises(ServiceUnavailableError):
        await svc.issue_upload_url(TENANT_A, "art1")


# ── verify_upload_complete ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_complete_verifies_size_and_sha256() -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)
    await _make(repo, "art1", TENANT_A, status="created")

    issued = await svc.issue_upload_url(TENANT_A, "art1")
    content = b"id,name\n1,a\n2,b\n"
    store.perform_presigned_put(issued["upload_url"], content)
    sha = _sha(content)

    verified = await svc.verify_upload_complete(
        TENANT_A,
        "art1",
        declared_size_bytes=len(content),
        declared_sha256=sha,
    )
    assert verified["artifact_id"] == "art1"
    assert verified["status"] == "uploaded"
    assert verified["verified"] == {"size_bytes": len(content), "sha256": sha}
    assert verified["stored_bytes"] == len(content)
    assert (await repo.get(TENANT_A, "art1"))["status"] == "uploaded"

    # A retry of upload-complete is an idempotent re-verify (no transition error).
    again = await svc.verify_upload_complete(TENANT_A, "art1", declared_sha256=sha)
    assert again["status"] == "uploaded"
    assert again["verified"]["sha256"] == sha


@pytest.mark.asyncio
async def test_upload_complete_rejects_mismatch_and_absent_bytes() -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)
    await _make(repo, "art1", TENANT_A, status="created")
    issued = await svc.issue_upload_url(TENANT_A, "art1")
    content = b"real bytes"
    store.perform_presigned_put(issued["upload_url"], content)

    # Size mismatch rejected.
    with pytest.raises(BadRequestError):
        await svc.verify_upload_complete(TENANT_A, "art1", declared_size_bytes=len(content) + 1)
    # Sha mismatch rejected.
    with pytest.raises(BadRequestError):
        await svc.verify_upload_complete(TENANT_A, "art1", declared_sha256="f" * 64)
    # Cross-tenant verify fails closed.
    with pytest.raises(NotFoundError):
        await svc.verify_upload_complete(TENANT_B, "art1")
    # Malformed declared sha rejected up front.
    with pytest.raises(BadRequestError):
        await svc.verify_upload_complete(TENANT_A, "art1", declared_sha256="zz")

    # No bytes ever uploaded -> verify refuses.
    await _make(repo, "art2", TENANT_A, status="created")
    await svc.issue_upload_url(TENANT_A, "art2")
    with pytest.raises(BadRequestError):
        await svc.verify_upload_complete(TENANT_A, "art2")


@pytest.mark.asyncio
async def test_upload_complete_refuses_terminal_artifact() -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)
    await _make(repo, "gone", TENANT_A, status="deleted")
    with pytest.raises(BadRequestError):
        await svc.verify_upload_complete(TENANT_A, "gone")


# ── issue_download_url ──────────────────────────────────────────────────────


async def _available_egress(
    store: InMemoryObjectStore,
    repo: DataArtifactRepository,
    artifact_id: str,
    tenant_id: str = TENANT_A,
    *,
    status: str = "available",
    content: bytes = b"export rows",
    expires_at: Any = None,
) -> str:
    key = _key(tenant_id, "egress", artifact_id)
    sha = _sha(content)
    store.put(key, content)
    await _make(
        repo,
        artifact_id,
        tenant_id,
        direction="egress",
        status=status,
        size_bytes=len(content),
        sha256=sha,
        artifact_type="export",
        expires_at=expires_at,
    )
    return sha


@pytest.mark.asyncio
async def test_download_url_only_for_available_and_committed() -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)

    await _available_egress(store, repo, "exp1", status="available")
    await _available_egress(store, repo, "exp2", status="committed")
    await _available_egress(store, repo, "draft", status="uploaded")

    d1 = await svc.issue_download_url(TENANT_A, "exp1")
    assert d1["artifact_id"] == "exp1"
    assert d1["download_url"]
    assert d1["expires_at"]
    assert d1["checksum_sha256"] == _sha(b"export rows")

    d2 = await svc.issue_download_url(TENANT_A, "exp2")
    assert d2["checksum_sha256"] == _sha(b"export rows")

    # uploaded (unverified durable set) refuses; other non-downloadable states too.
    with pytest.raises(NotFoundError):
        await svc.issue_download_url(TENANT_A, "draft")
    with pytest.raises(NotFoundError):
        await svc.issue_download_url(TENANT_B, "exp1")


@pytest.mark.asyncio
async def test_download_url_refuses_revoked_expired_deleted() -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)

    await _available_egress(store, repo, "del", status="deleted")
    await _available_egress(store, repo, "rev", status="revoked")
    await _available_egress(store, repo, "old", status="available", expires_at=_BASE - timedelta(days=1))
    await _available_egress(store, repo, "exp", status="expired")

    for artifact_id in ("del", "rev", "old", "exp"):
        with pytest.raises(NotFoundError):
            await svc.issue_download_url(TENANT_A, artifact_id)

    # Cross-tenant row is invisible (fail closed).
    await _available_egress(store, repo, "owned", tenant_id=TENANT_B)
    with pytest.raises(NotFoundError):
        await svc.issue_download_url(TENANT_A, "owned")


@pytest.mark.asyncio
async def test_download_url_records_audit_and_event(_db_free: Any) -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)
    sha = await _available_egress(store, repo, "exp1", status="available")

    await svc.issue_download_url(
        TENANT_A,
        "exp1",
        actor_id="user@aether",
        ip_address="iphmac-token",
    )
    assert len(_db_free.audited) == 1
    audit = _db_free.audited[0]
    assert audit["actor_id"] == "user@aether"
    assert audit["tenant_id"] == TENANT_A
    assert audit["resource_id"] == "exp1"
    assert audit["action"] == "download"
    assert audit["outcome"] == "allowed"
    assert audit["ip_address"] == "iphmac-token"
    assert audit["metadata"]["checksum_sha256"] == sha

    assert _db_free.emitted
    topic_name, tenant_id, payload = _db_free.emitted[-1]
    assert topic_name == DOWNLOAD_URL_ISSUED_TOPIC
    assert tenant_id == TENANT_A
    assert payload["artifact_id"] == "exp1"


@pytest.mark.asyncio
async def test_upload_complete_emits_ingress_topic(_db_free: Any) -> None:
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)
    await _make(repo, "art1", TENANT_A, status="created")
    issued = await svc.issue_upload_url(TENANT_A, "art1")
    content = b"abc"
    store.perform_presigned_put(issued["upload_url"], content)
    await svc.verify_upload_complete(TENANT_A, "art1", declared_sha256=_sha(content))

    topic_name, tenant_id, payload = _db_free.emitted[-1]
    assert topic_name == UPLOAD_COMPLETE_TOPIC
    assert tenant_id == TENANT_A
    assert payload["sha256"] == _sha(content)


@pytest.mark.asyncio
async def test_download_requires_presignable_store() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    await _available_egress(store, repo, "exp1", status="available")
    svc = ObjectTransferService(object_store=_PlainObjectStore(), artifact_repo=repo)
    with pytest.raises(ServiceUnavailableError):
        await svc.issue_download_url(TENANT_A, "exp1")


# ── route surface + permission gates ────────────────────────────────────────


class _Tenant:
    """Minimal ``request.state.tenant`` double honoring the grant gate."""

    def __init__(
        self,
        tenant_id: str,
        permissions: Optional[tuple[str, ...]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.permissions = list(permissions or ())

    def require_any_permission(self, *perms: str) -> None:
        if not any(p in self.permissions for p in perms):
            raise ForbiddenError(f"requires one of: {', '.join(perms)}")


class _Request:
    def __init__(self, tenant: _Tenant) -> None:
        self.state = SimpleNamespace(tenant=tenant)
        self.client = None


async def _route_harness(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Build an injected store/repo and point the router at one service."""
    store = InMemoryObjectStore()
    repo = DataArtifactRepository()
    svc = ObjectTransferService(object_store=store, artifact_repo=repo)
    monkeypatch.setattr("services.data_exchange.routes_transfer.get_object_transfer_service", lambda: svc)
    return store, repo


def test_route_permission_constant_names() -> None:
    assert "data_exchange.transfer.upload" in UPLOAD_REQUIRED_GRANTS
    assert "data_exchange.import.create" in UPLOAD_REQUIRED_GRANTS
    assert "data_exchange.transfer.download" in DOWNLOAD_REQUIRED_GRANTS
    assert "data_exchange.export.download" in DOWNLOAD_REQUIRED_GRANTS


@pytest.mark.asyncio
async def test_upload_url_route_shape_and_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    store, repo = await _route_harness(monkeypatch)
    await _make(repo, "art1", TENANT_A, status="created")

    tenant = _Tenant(TENANT_A, permissions=("data_exchange.transfer.upload",))
    result = await upload_url("art1", _Request(tenant))
    assert result["artifact_id"] == "art1"
    assert result["status"] == "upload_pending"
    assert result["upload_method"] == "PUT"
    assert (await repo.get(TENANT_A, "art1"))["status"] == "upload_pending"
    # bytes reachable at the signed URL
    content = b"via-route"
    store.perform_presigned_put(result["upload_url"], content)
    assert store.head(_key(TENANT_A, "ingress", "art1")).size_bytes == len(content)

    # A caller without the grant fails closed before the service is reached.
    blocked = _Tenant(TENANT_A, permissions=("data_exchange.read",))
    with pytest.raises(ForbiddenError):
        await upload_url("art1", _Request(blocked))


@pytest.mark.asyncio
async def test_upload_complete_route_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    store, repo = await _route_harness(monkeypatch)
    await _make(repo, "art1", TENANT_A, status="created")
    issued = await ObjectTransferService(
        object_store=store, artifact_repo=repo
    ).issue_upload_url(TENANT_A, "art1")
    content = b"done"
    store.perform_presigned_put(issued["upload_url"], content)
    sha = _sha(content)

    tenant = _Tenant(TENANT_A, permissions=("data_exchange.import.create",))
    body = UploadCompleteBody(declared_size_bytes=len(content), declared_sha256=sha)
    result = await upload_complete("art1", body, _Request(tenant))
    assert result["status"] == "uploaded"
    assert result["verified"] == {"size_bytes": len(content), "sha256": sha}


@pytest.mark.asyncio
async def test_download_url_route_shape_and_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    store, repo = await _route_harness(monkeypatch)
    sha = await _available_egress(store, repo, "exp1", status="available")

    tenant = _Tenant(TENANT_A, permissions=("data_exchange.transfer.download",), user_id="u1")
    result = await route_download_url("exp1", _Request(tenant))
    assert result["artifact_id"] == "exp1"
    assert result["download_url"]
    assert result["checksum_sha256"] == sha
    assert store.perform_presigned_get(result["download_url"]) == b"export rows"

    blocked = _Tenant(TENANT_A, permissions=("data_exchange.read",))
    with pytest.raises(ForbiddenError):
        await route_download_url("exp1", _Request(blocked))
