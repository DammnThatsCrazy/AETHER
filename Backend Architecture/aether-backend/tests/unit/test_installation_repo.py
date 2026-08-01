"""In-memory behaviour of the mobile installation repository."""
from __future__ import annotations

import asyncio

import pytest

from repositories.installation_repo import (
    get_installation_repository,
    reset_installation_memory,
)

A = "t:tenant-a"
B = "t:tenant-b"


def _run(coro):
    return asyncio.run(coro)


def _register(repo, scope=A, principal="user-1", iid=None, bundle="com.aether.app"):
    return repo.register(
        tenant_scope=scope, principal_id=principal, installation_id=iid,
        app_kind="aether", platform="ios", bundle_id=bundle, environment="production",
        device_name="iPhone",
    )


@pytest.fixture(autouse=True)
def _clean():
    reset_installation_memory()
    yield
    reset_installation_memory()


def test_register_mints_id():
    repo = get_installation_repository()
    row = _run(_register(repo))
    assert row["id"].startswith("inst_")
    assert row["trust_state"] == "registered"
    assert row["app_kind"] == "aether"
    assert row["device_name"] == "iPhone"


def test_register_upserts_by_id():
    repo = get_installation_repository()
    _run(_register(repo, iid="dev-1", bundle="com.aether.app"))
    updated = _run(_register(repo, iid="dev-1", bundle="com.aether.v2"))
    assert updated["id"] == "dev-1"
    assert updated["bundle_id"] == "com.aether.v2"
    assert len(_run(repo.list_for_principal(A, "user-1"))) == 1  # no duplicate


def test_get_and_list_scoped():
    repo = get_installation_repository()
    _run(_register(repo, iid="dev-1"))
    assert _run(repo.get(A, "dev-1")) is not None
    assert _run(repo.get(B, "dev-1")) is None  # cross-scope absent
    assert len(_run(repo.list_for_principal(A, "user-1"))) == 1


def test_revoke_deactivates_subscriptions():
    repo = get_installation_repository()
    _run(_register(repo, iid="dev-1"))
    _run(repo.add_subscription(tenant_scope=A, installation_id="dev-1", principal_id="user-1",
                               platform="ios", provider="apns", token_hash="h1", environment="production"))
    revoked = _run(repo.revoke(A, "dev-1"))
    assert revoked["trust_state"] == "revoked"
    subs = _run(repo.list_subscriptions(A, "dev-1"))
    assert subs[0]["active"] is False


def test_add_subscription_dedupes_by_token_hash():
    repo = get_installation_repository()
    _run(_register(repo, iid="dev-1"))
    a = _run(repo.add_subscription(tenant_scope=A, installation_id="dev-1", principal_id="user-1",
                                   platform="ios", provider="apns", token_hash="tok", environment="production"))
    b = _run(repo.add_subscription(tenant_scope=A, installation_id="dev-1", principal_id="user-1",
                                   platform="ios", provider="apns", token_hash="tok", environment="production"))
    assert a["id"] == b["id"]  # deduped
    assert len(_run(repo.list_subscriptions(A, "dev-1"))) == 1


def test_scope_isolation_on_revoke():
    repo = get_installation_repository()
    _run(_register(repo, iid="dev-1"))
    assert _run(repo.revoke(B, "dev-1")) is None  # cannot revoke from another scope
    assert _run(repo.get(A, "dev-1"))["trust_state"] == "registered"


def test_delete_by_principal_dsr():
    repo = get_installation_repository()
    _run(_register(repo, iid="dev-1", principal="user-1"))
    _run(repo.add_subscription(tenant_scope=A, installation_id="dev-1", principal_id="user-1",
                               platform="ios", provider="apns", token_hash="h1", environment="production"))
    _run(_register(repo, iid="dev-2", principal="user-2"))
    removed = _run(repo.delete_by_principal(A, "user-1"))
    assert removed == 2  # 1 installation + 1 subscription
    assert _run(repo.get(A, "dev-1")) is None
    assert _run(repo.get(A, "dev-2")) is not None
