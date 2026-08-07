"""Credential state-machine ORDERING-VIOLATION edge cases (gap A1/A2).

The happy-path lifecycle (create → test → activate → decrypt), rotation overlap,
optimistic-concurrency conflict (A3), tenant isolation, and revoke/tombstone are
already covered by ``test_credential_authority.py``. This file adds the still-
missing A1/A2 edges: state transitions requested OUT OF ORDER, or against the
wrong slot/environment, and the fail-closed guarantees around them.

Each test asserts the PRECISE outcome (``SlotError`` / ``NotFoundError`` /
``ConflictError`` or an idempotent no-op) AND, where a secret is in play, that the
plaintext never leaks into an error string or a safe view. The invariants these
guard:

* A botched or out-of-order operation must NEVER activate, demote, or expose a
  credential it should not (a "use-after-revoke" must fail closed).
* A failed validation of a fresh pending version must NEVER produce an active
  secret out of thin air.
* Slot/environment are part of a version's identity: an activate/test aimed at a
  different slot or environment resolves to "not found", never silently touches
  the wrong version (mirrors the KMS encryption-context binding).
"""

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
from services.providers.credentials.schema import CredentialState  # noqa: E402
from shared.common.common import ConflictError, NotFoundError  # noqa: E402

# coinbase declares two slots: webhook_signing_secret (overlap) + onramp_api_key.
T, P, E, S = "tenantEdge", "coinbase", "sandbox", "webhook_signing_secret"
APIKEY = "onramp_api_key"


def _fresh() -> CredentialAuthority:
    reset_in_memory_stores()
    return CredentialAuthority()


# ── A1: activate with nothing to activate ─────────────────────────────────────
@pytest.mark.asyncio
async def test_activate_with_no_version_is_not_found():
    """Activating a slot that has no versions at all is NotFound, not a crash."""
    a = _fresh()
    with pytest.raises(NotFoundError):
        await a.activate(T, P, E, S, credential_version=1, actor="admin")


@pytest.mark.asyncio
async def test_activate_nonexistent_version_number_is_not_found():
    """A pending v1 exists, but activating v99 (never created) is NotFound."""
    a = _fresh()
    await a.create_pending(T, P, E, S, "whsec_alpha", created_by="admin")
    with pytest.raises(NotFoundError):
        await a.activate(T, P, E, S, credential_version=99, actor="admin")
    # The real pending version is untouched — still activatable afterwards.
    act = await a.activate(T, P, E, S, credential_version=1, actor="admin")
    assert act["state"] == CredentialState.ACTIVE


# ── A1/A2: double-activate the same version is an idempotent no-op ─────────────
@pytest.mark.asyncio
async def test_double_activate_same_version_is_idempotent_no_previous():
    """Re-activating the already-active version must not demote it to `previous`.

    A naive implementation would move the current active to `previous` (opening a
    bogus rotation-overlap window) every time activate is called. Activating the
    SAME version must be a no-op: exactly one ACTIVE version, zero PREVIOUS.
    """
    a = _fresh()
    await a.create_pending(T, P, E, S, "whsec_alpha", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    again = await a.activate(T, P, E, S, credential_version=1, actor="admin")
    assert again["state"] == CredentialState.ACTIVE

    rows = await CredentialVersionRepo().versions_for_slot(T, P, E, S)
    assert [r["state"] for r in rows].count(CredentialState.ACTIVE) == 1
    assert [r["state"] for r in rows].count(CredentialState.PREVIOUS) == 0
    assert await a.get_active_secret(T, P, E, S) == "whsec_alpha"  # unchanged


# ── A2: rotate when there is no active version ────────────────────────────────
@pytest.mark.asyncio
async def test_rotate_with_no_active_creates_and_activates_fresh():
    """rotate() on an empty slot creates v1 and activates it (no prior active)."""
    a = _fresh()
    r = await a.rotate(T, P, E, S, "whsec_fresh", actor="admin")
    assert r["credential_version"] == 1 and r["state"] == CredentialState.ACTIVE
    assert await a.get_active_secret(T, P, E, S) == "whsec_fresh"


@pytest.mark.asyncio
async def test_rotate_with_no_active_but_expected_version_conflicts():
    """Asserting an expected active version when none exists is a ConflictError."""
    a = _fresh()
    with pytest.raises(ConflictError):
        await a.rotate(T, P, E, S, "whsec_x", actor="admin", expected_active_version=5)


# ── A2: activate a revoked/terminal version ───────────────────────────────────
@pytest.mark.asyncio
async def test_activate_revoked_version_conflicts_and_leaks_no_secret():
    """A revoked version can never be re-activated; the error names no secret."""
    a = _fresh()
    secret = "whsec_revoked_me"
    await a.create_pending(T, P, E, S, secret, created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    await a.revoke(T, P, E, S, actor="admin")
    with pytest.raises(ConflictError) as exc:
        await a.activate(T, P, E, S, credential_version=1, actor="admin")
    assert secret not in str(exc.value)  # fail closed, no plaintext in the error


# ── A2: use-after-revoke must fail closed ─────────────────────────────────────
@pytest.mark.asyncio
async def test_use_after_revoke_fails_closed():
    """Once revoked, neither the active secret nor a verification secret resolves."""
    a = _fresh()
    await a.create_pending(T, P, E, S, "whsec_gone", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    await a.revoke(T, P, E, S, actor="admin")
    with pytest.raises(NotFoundError):
        await a.get_active_secret(T, P, E, S)
    assert await a.get_verification_secrets(T, P, E, S) == []


@pytest.mark.asyncio
async def test_revoke_empty_slot_is_zero_and_idempotent():
    """Revoking a slot with no versions is a clean no-op; a second revoke too."""
    a = _fresh()
    first = await a.revoke(T, P, E, S, actor="admin")
    assert first["revoked_versions"] == 0
    await a.create_pending(T, P, E, S, "whsec_a", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    r1 = await a.revoke(T, P, E, S, actor="admin")
    assert r1["revoked_versions"] == 1
    r2 = await a.revoke(T, P, E, S, actor="admin")  # already terminal
    assert r2["revoked_versions"] == 0


# ── A2: delete an ACTIVE slot directly (no prior revoke) ──────────────────────
@pytest.mark.asyncio
async def test_delete_active_slot_tombstones_and_erases_ciphertext():
    """delete() on a still-active slot tombstones it and erases the ciphertext."""
    a = _fresh()
    await a.create_pending(T, P, E, S, "whsec_del", created_by="admin")
    await a.activate(T, P, E, S, credential_version=1, actor="admin")
    out = await a.delete(T, P, E, S, actor="admin")
    assert out["tombstoned_versions"] == 1
    rows = await CredentialVersionRepo().versions_for_slot(T, P, E, S)
    assert rows and all(
        r["state"] == CredentialState.TOMBSTONED and r["encrypted_value"] == ""
        for r in rows
    )
    with pytest.raises(NotFoundError):
        await a.get_active_secret(T, P, E, S)


# ── A2: cross-slot / cross-environment mismatch on activate & test ────────────
@pytest.mark.asyncio
async def test_activate_wrong_environment_is_not_found():
    """A version created in sandbox cannot be activated under `live`.

    Environment is part of the version's identity (and its KMS encryption
    context), so the live-environment lookup finds no matching version.
    """
    a = _fresh()
    await a.create_pending(T, P, "sandbox", S, "whsec_sbx", created_by="admin")
    with pytest.raises(NotFoundError):
        await a.activate(T, P, "live", S, credential_version=1, actor="admin")


@pytest.mark.asyncio
async def test_activate_wrong_slot_is_not_found():
    """A version created for one slot cannot be activated against a sibling slot."""
    a = _fresh()
    await a.create_pending(T, P, E, S, "whsec_only", created_by="admin")
    # onramp_api_key is a real declared slot, but it has no version 1.
    with pytest.raises(NotFoundError):
        await a.activate(T, P, E, APIKEY, credential_version=1, actor="admin")


@pytest.mark.asyncio
async def test_test_slot_wrong_environment_is_not_found():
    """Testing a slot in an environment with no version resolves to NotFound."""
    a = _fresh()
    await a.create_pending(T, P, "sandbox", S, "whsec_sbx", created_by="admin")
    with pytest.raises(NotFoundError):
        await a.test_slot(T, P, "live", S, actor="admin")


@pytest.mark.asyncio
async def test_activate_and_delete_unknown_slot_raise_slot_error():
    """An undeclared slot name is rejected up front with SlotError, everywhere."""
    a = _fresh()
    with pytest.raises(SlotError):
        await a.activate(T, P, E, "not_a_slot", credential_version=1, actor="admin")
    with pytest.raises(SlotError):
        await a.delete(T, P, E, "not_a_slot", actor="admin")
    with pytest.raises(SlotError):
        await a.test_slot(T, P, E, "not_a_slot", actor="admin")


# ── A1: a failed test of a fresh pending must NOT conjure an active secret ─────
@pytest.mark.asyncio
async def test_failed_test_of_lone_pending_never_activates():
    """A pending version that fails validation is marked test_failed — and there
    is still NO active secret (a failed test cannot create one from nothing).

    Distinct from ``test_failed_pending_leaves_active_intact`` (which has a
    pre-existing active version): here the slot has ONLY the failing pending
    version, so the invariant under test is "no active appears", not "the
    existing active survives".
    """
    a = _fresh()
    bad = await a.create_pending(T, P, E, S, "whsec_bad", created_by="admin")
    repo = CredentialVersionRepo()
    rows = await repo.versions_for_slot(T, P, E, S)
    row = [r for r in rows if r["credential_version"] == bad["credential_version"]][0]
    await repo.update(row["id"], {"encrypted_value": "not-base64!!"})  # force decrypt fail

    tf = await a.test_slot(T, P, E, S, actor="admin", credential_version=1)
    assert tf["last_test_result"] == "decrypt_failed"
    assert tf["state"] == CredentialState.TEST_FAILED
    with pytest.raises(NotFoundError):
        await a.get_active_secret(T, P, E, S)  # nothing was activated


@pytest.mark.asyncio
async def test_create_pending_unknown_environment_rejected_and_no_leak():
    """An unknown environment is rejected at create; the value never leaks."""
    a = _fresh()
    secret = "whsec_should_not_persist"
    with pytest.raises(SlotError) as exc:
        await a.create_pending(T, P, "not-an-env", S, secret, created_by="admin")
    assert secret not in str(exc.value)
