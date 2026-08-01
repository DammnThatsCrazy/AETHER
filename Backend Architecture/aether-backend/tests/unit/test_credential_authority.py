"""Credential authority state machine: lifecycle, overlap, concurrency, isolation."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.providers.credentials.authority import (  # noqa: E402
    CredentialAuthority,
    SlotError,
)
from services.providers.credentials.repository import CredentialVersionRepo  # noqa: E402
from shared.common.common import ConflictError, NotFoundError  # noqa: E402

T, P, E, S = "tenantA", "coinbase", "sandbox", "webhook_signing_secret"


def _fresh() -> CredentialAuthority:
    reset_in_memory_stores()
    return CredentialAuthority()


@pytest.mark.asyncio
async def test_create_test_activate_decrypt():
    a = _fresh()
    v1 = await a.create_pending(T, P, E, S, "whsec_alpha", created_by="admin")
    assert v1["state"] == "pending" and v1["credential_version"] == 1
    assert "whsec_alpha" not in str(v1)  # write-only
    t = await a.test_slot(T, P, E, S, actor="admin")
    assert t["last_test_result"] == "valid"
    act = await a.activate(T, P, E, S, credential_version=1, actor="admin")
    assert act["state"] == "active"
    assert await a.get_active_secret(T, P, E, S) == "whsec_alpha"


@pytest.mark.asyncio
async def test_rotate_overlap_keeps_previous():
    a = _fresh()
    await a.create_pending(T, P, E, S, "alpha", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    r = await a.rotate(T, P, E, S, "beta", actor="admin", expected_active_version=1)
    assert r["credential_version"] == 2 and r["state"] == "active"
    assert set(await a.get_verification_secrets(T, P, E, S)) == {"beta", "alpha"}


@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict():
    a = _fresh()
    await a.create_pending(T, P, E, S, "alpha", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    await a.rotate(T, P, E, S, "beta", actor="admin")  # active now v2
    with pytest.raises(ConflictError):
        await a.rotate(T, P, E, S, "gamma", actor="admin", expected_active_version=1)


@pytest.mark.asyncio
async def test_failed_pending_leaves_active_intact():
    a = _fresh()
    await a.create_pending(T, P, E, S, "alpha", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    bad = await a.create_pending(T, P, E, S, "beta", created_by="admin")
    repo = CredentialVersionRepo()
    rows = await repo.versions_for_slot(T, P, E, S)
    badrow = [x for x in rows if x["credential_version"] == bad["credential_version"]][0]
    await repo.update(badrow["id"], {"encrypted_value": "not-base64!!"})
    tf = await a.test_slot(T, P, E, S, actor="admin", credential_version=bad["credential_version"])
    assert tf["last_test_result"] == "decrypt_failed" and tf["state"] == "test_failed"
    assert await a.get_active_secret(T, P, E, S) == "alpha"  # untouched


@pytest.mark.asyncio
async def test_multi_slot_independent():
    a = _fresh()
    await a.create_pending(T, P, E, S, "wh", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    await a.create_pending(T, P, E, "onramp_api_key", "apikey", created_by="admin")
    await a.activate(T, P, E, "onramp_api_key", credential_version=1, actor="admin")
    assert await a.get_active_secret(T, P, E, S) == "wh"
    assert await a.get_active_secret(T, P, E, "onramp_api_key") == "apikey"


@pytest.mark.asyncio
async def test_enable_requires_complete_then_ok():
    a = _fresh()
    with pytest.raises(ConflictError):
        await a.enable_provider(T, P, E, actor="admin")  # nothing configured
    for slot in ("webhook_signing_secret", "onramp_api_key"):
        await a.create_pending(T, P, E, slot, "v", created_by="admin")
        await a.activate(T, P, E, slot, credential_version=1, actor="admin")
    en = await a.enable_provider(T, P, E, actor="admin")
    assert en["enabled"] is True
    assert await a.is_enabled(T, P, E) is True


@pytest.mark.asyncio
async def test_unknown_slot_rejected():
    a = _fresh()
    with pytest.raises(SlotError):
        await a.create_pending(T, P, E, "nope", "x", created_by="admin")
    with pytest.raises(SlotError):
        await a.create_pending(T, P, "not-an-env", S, "x", created_by="admin")


@pytest.mark.asyncio
async def test_tenant_isolation():
    a = _fresh()
    await a.create_pending(T, P, E, S, "alpha", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    conns = await a.get_connections("tenantB", environment=E)
    cb = [c for c in conns if c["provider"] == "coinbase"][0]
    assert cb["missing_slots"]  # tenantB sees nothing configured
    assert all(s["status"] is None for s in cb["slots"])
    with pytest.raises(NotFoundError):
        await a.get_active_secret("tenantB", P, E, S)


@pytest.mark.asyncio
async def test_revoke_and_tombstone():
    a = _fresh()
    await a.create_pending(T, P, E, S, "alpha", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    await a.revoke(T, P, E, S, actor="admin")
    with pytest.raises(NotFoundError):
        await a.get_active_secret(T, P, E, S)
    await a.delete(T, P, E, S, actor="admin")
    repo = CredentialVersionRepo()
    rows = await repo.versions_for_slot(T, P, E, S)
    assert rows and all(x["state"] == "tombstoned" and x["encrypted_value"] == "" for x in rows)
