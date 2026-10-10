"""In-memory (local-mode) behaviour of the continuation repository.

get_pool() returns None under AETHER_ENV=local without DATABASE_URL, so these
exercise the in-memory paths — the same semantics the SQL paths implement:
idempotent create, compare-and-swap concurrency, tenant/operator scope isolation,
TTL sweep, DSR erase-by-principal, and selection-token mint/resolve.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from repositories.continuation_repo import (
    get_continuation_repository,
    reset_continuation_memory,
)
from shared.common.common import ConflictError, utc_now

TENANT = "t:tenant-a"
OTHER = "t:tenant-b"


def _run(coro):
    return asyncio.run(coro)


def _ctx(**over):
    base = {
        "version": "1",
        "id": over.get("id", "c1"),
        "principal_id": over.get("principal_id", "user-1"),
        "tenant_id": "tenant-a",
        "app_kind": "aether",
        "source_client": "desktop",
        "surface": "graph",
        "resource_references": [],
        "canonical_context": {"route": "/graph"},
        "summary": {"title": "Resume graph"},
        "sensitivity": "standard",
        "freshness": "live",
    }
    base.update(over)
    return base


def _create(repo, **over):
    return repo.create(
        tenant_scope=over.pop("tenant_scope", TENANT),
        continuation_id=over.get("id", "c1"),
        principal_id=over.get("principal_id", "user-1"),
        app_kind="aether",
        source_client="desktop",
        surface="graph",
        sensitivity="standard",
        freshness="live",
        context=_ctx(**over),
        idempotency_key=over.pop("idempotency_key", None),
        expires_at=over.pop("expires_at", None),
    )


@pytest.fixture(autouse=True)
def _clean():
    reset_continuation_memory()
    yield
    reset_continuation_memory()


def test_create_starts_at_revision_zero():
    repo = get_continuation_repository()
    row = _run(_create(repo))
    assert row["state_revision"] == 0
    assert row["replayed"] is False
    assert row["updated_at"] is not None


def test_create_is_idempotent_on_key():
    repo = get_continuation_repository()
    first = _run(_create(repo, idempotency_key="k1"))
    second = _run(_create(repo, id="c2", idempotency_key="k1"))
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["id"] == first["id"]  # no new row


def test_cas_update_bumps_revision():
    repo = get_continuation_repository()
    _run(_create(repo))
    updated = _run(repo.cas_update(
        tenant_scope=TENANT, continuation_id="c1", expected_revision=0,
        context=_ctx(summary={"title": "Now on mobile"}),
    ))
    assert updated["state_revision"] == 1
    assert updated["summary"]["title"] == "Now on mobile"


def test_cas_update_rejects_stale_revision():
    repo = get_continuation_repository()
    _run(_create(repo))
    with pytest.raises(ConflictError):
        _run(repo.cas_update(
            tenant_scope=TENANT, continuation_id="c1", expected_revision=5,
            context=_ctx(),
        ))


def test_cas_update_absent_id_returns_none():
    repo = get_continuation_repository()
    result = _run(repo.cas_update(
        tenant_scope=TENANT, continuation_id="nope", expected_revision=0, context=_ctx(),
    ))
    assert result is None


def test_scope_isolation_no_cross_tenant_read():
    repo = get_continuation_repository()
    _run(_create(repo))
    assert _run(repo.get_scoped(TENANT, "c1")) is not None
    # Same id, different scope: absent (404), never a cross-scope leak.
    assert _run(repo.get_scoped(OTHER, "c1")) is None
    # CAS from another scope also cannot touch it.
    assert _run(repo.cas_update(
        tenant_scope=OTHER, continuation_id="c1", expected_revision=0, context=_ctx(),
    )) is None


def test_list_recent_scoped_to_principal():
    repo = get_continuation_repository()
    _run(_create(repo, id="c1", principal_id="user-1"))
    _run(_create(repo, id="c2", principal_id="user-1"))
    _run(_create(repo, id="c3", principal_id="user-2"))
    rows = _run(repo.list_recent(TENANT, "user-1", limit=25))
    assert {r["id"] for r in rows} == {"c1", "c2"}


def test_delete_scoped():
    repo = get_continuation_repository()
    _run(_create(repo))
    assert _run(repo.delete_scoped(OTHER, "c1")) is False  # wrong scope
    assert _run(repo.delete_scoped(TENANT, "c1")) is True
    assert _run(repo.get_scoped(TENANT, "c1")) is None


def test_sweep_expired_removes_past_ttl():
    repo = get_continuation_repository()
    past = (utc_now() - timedelta(hours=1)).isoformat()
    future = (utc_now() + timedelta(hours=1)).isoformat()
    _run(_create(repo, id="c-old", expires_at=past))
    _run(_create(repo, id="c-live", expires_at=future))
    removed = _run(repo.sweep_expired())
    assert removed == 1
    assert _run(repo.get_scoped(TENANT, "c-old")) is None
    assert _run(repo.get_scoped(TENANT, "c-live")) is not None


def test_delete_by_principal_dsr():
    repo = get_continuation_repository()
    _run(_create(repo, id="c1", principal_id="user-1"))
    _run(_create(repo, id="c2", principal_id="user-1"))
    _run(_create(repo, id="c3", principal_id="user-2"))
    removed = _run(repo.delete_by_principal(TENANT, "user-1"))
    assert removed == 2
    assert _run(repo.get_scoped(TENANT, "c1")) is None
    assert _run(repo.get_scoped(TENANT, "c3")) is not None


def test_selection_mint_and_scoped_resolve():
    repo = get_continuation_repository()
    sel = _run(repo.create_selection(
        tenant_scope=TENANT, principal_id="user-1", mode="explicit",
        selection={"resource_ids": ["a", "b"]},
    ))
    token = sel["token"]
    got = _run(repo.get_selection(TENANT, token))
    assert got["resource_ids"] == ["a", "b"]
    assert got["mode"] == "explicit"
    # Cross-scope resolve is absent.
    assert _run(repo.get_selection(OTHER, token)) is None
