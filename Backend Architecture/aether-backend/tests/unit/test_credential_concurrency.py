"""Concurrent/racing rotation on one credential slot (A3) + overlap sweep.

Two rotations racing on the same active version must not both win: optimistic
concurrency admits exactly one and rejects the other with a ConflictError, so a
slot never ends up with two active versions.

The in-memory backend never suspends the event loop (its awaits complete
synchronously), so a naive ``asyncio.gather`` is NOT a race — it is two serial
rotations. ``test_concurrent_rotation_true_race`` therefore drives the authority
through a *suspending* repo that (a) yields at a real coroutine boundary and
(b) simulates the Postgres partial-unique index (SQLSTATE 23505) that the
authority maps to a 409 ConflictError. That is the durable-rotation contract:
exactly one winner, loser gets 409, and the single-active invariant holds.

The sweep tests close gap (2): the rotation-overlap expiry sweep is no longer
lazy-only — ``sweep_once`` tombstones an expired previous version and emits the
revoked/expired demotion hook.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.providers.credentials.authority import CredentialAuthority  # noqa: E402
from services.providers.credentials.repository import CredentialVersionRepo  # noqa: E402
from services.providers.credentials.schema import CredentialState  # noqa: E402
from services.providers.credentials.sweeper import sweep_once  # noqa: E402
from shared.common.common import ConflictError, utc_now  # noqa: E402

pytestmark = pytest.mark.asyncio

_ENV = "sandbox"
_SLOT = "webhook_signing_secret"


class _UniqueViolation(Exception):
    """asyncpg-shaped unique violation (SQLSTATE 23505)."""

    sqlstate = "23505"


class _RaceBarrier:
    """Two-party rendezvous: neither party proceeds until both have arrived.

    Inert until ``arm()`` is called, so setup/teardown repo reads (which are
    not racing) pass straight through and only the two racing rotations block.
    """

    def __init__(self, parties: int = 2) -> None:
        self._parties = parties
        self._count = 0
        self._event = asyncio.Event()
        self._armed = False

    def arm(self) -> None:
        self._armed = True

    async def wait(self) -> None:
        if not self._armed:
            return
        self._count += 1
        if self._count >= self._parties:
            self._event.set()
        else:
            await self._event.wait()


class _SuspendingRaceRepo:
    """Real-repo wrapper that forces a true race and enforces the index.

    Every call yields at a real coroutine boundary (``await asyncio.sleep(0)``)
    so the two rotators genuinely interleave instead of running serially.
    ``next_version_number`` serialises version assignment so the racing creators
    can never collide on the same version number. ``update`` simulates the
    Postgres partial-unique index (at most one ACTIVE per slot) by raising an
    asyncpg-shaped ``UniqueViolationError`` when a second version would become
    ACTIVE — the exact 23505 the authority maps to a 409.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.barrier = _RaceBarrier(2)
        self._version_lock = asyncio.Lock()
        self._max_assigned = 0

    async def next_version_number(self, tenant_id, provider, environment, slot_name) -> int:
        await asyncio.sleep(0)
        async with self._version_lock:
            base = await self._inner.next_version_number(
                tenant_id, provider, environment, slot_name
            )
            version = max(base, self._max_assigned + 1)
            self._max_assigned = version
            return version

    async def insert(self, record_id, data):
        await asyncio.sleep(0)
        return await self._inner.insert(record_id, data)

    async def versions_for_slot(self, tenant_id, provider, environment, slot_name):
        await asyncio.sleep(0)
        return await self._inner.versions_for_slot(
            tenant_id, provider, environment, slot_name
        )

    async def previous_version(self, tenant_id, provider, environment, slot_name):
        await asyncio.sleep(0)
        return await self._inner.previous_version(
            tenant_id, provider, environment, slot_name
        )

    async def active_version(self, tenant_id, provider, environment, slot_name):
        await asyncio.sleep(0)
        row = await self._inner.active_version(
            tenant_id, provider, environment, slot_name
        )
        # Rendezvous: both rotators must observe the SAME active version before
        # either may demote/activate, so the collision is guaranteed, not luck.
        await self.barrier.wait()
        await asyncio.sleep(0)
        return row

    async def update(self, record_id, patch):
        await asyncio.sleep(0)
        if patch.get("state") == CredentialState.ACTIVE:
            existing = await self._inner.find_by_id(record_id)
            slot = (
                existing.get("tenant_id"),
                existing.get("provider"),
                existing.get("environment"),
                existing.get("slot_name"),
            )
            active = await self._inner.active_version(*slot)
            if active is not None and active.get("id") != record_id:
                raise _UniqueViolation(f"duplicate active for slot {slot}")
        return await self._inner.update(record_id, patch)


async def test_concurrent_rotation_one_wins_in_memory():
    """Serial (in-memory) rotations still admit exactly one winner."""
    reset_in_memory_stores()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    authority = CredentialAuthority()
    await authority.create_pending(tenant, "coinbase", _ENV, _SLOT, "v1", created_by="a")
    await authority.activate(tenant, "coinbase", _ENV, _SLOT, credential_version=1, actor="a")

    async def _rotate(value: str):
        try:
            await authority.rotate(
                tenant, "coinbase", _ENV, _SLOT, value,
                actor="a", expected_active_version=1, idempotency_key=value,
            )
            return "ok"
        except ConflictError:
            return "conflict"

    results = await asyncio.gather(_rotate("alpha"), _rotate("beta"))
    assert sorted(results) == ["conflict", "ok"]  # exactly one wins

    rows = await authority._repo.versions_for_slot(tenant, "coinbase", _ENV, _SLOT)
    active = [r for r in rows if r.get("state") == CredentialState.ACTIVE]
    assert len(active) == 1


async def test_concurrent_rotation_true_race_loser_gets_409():
    """A real coroutine boundary + simulated unique index: exactly one winner,
    the loser surfaces as a 409 ConflictError (never a raw UniqueViolationError)."""
    reset_in_memory_stores()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    authority = CredentialAuthority(repo=_SuspendingRaceRepo(CredentialVersionRepo()))
    await authority.create_pending(tenant, "coinbase", _ENV, _SLOT, "v1", created_by="a")
    await authority.activate(tenant, "coinbase", _ENV, _SLOT, credential_version=1, actor="a")
    # Arm the rendezvous so the two racing rotations interleave deterministically.
    authority._repo.barrier.arm()

    results: list[str] = []

    async def _rotate(value: str):
        try:
            await authority.rotate(
                tenant, "coinbase", _ENV, _SLOT, value,
                actor="a", expected_active_version=1,
            )
            results.append("ok")
        except ConflictError as exc:
            results.append("conflict")
            assert exc.code.value == 409  # a clean conflict, not a 500

    await asyncio.gather(_rotate("alpha"), _rotate("beta"))
    assert sorted(results) == ["conflict", "ok"]  # exactly one wins

    rows = await authority._repo._inner.versions_for_slot(tenant, "coinbase", _ENV, _SLOT)
    active = [r for r in rows if r.get("state") == CredentialState.ACTIVE]
    assert len(active) == 1  # single-active invariant survived the race


async def test_sweep_tombstones_expired_overlap_previous():
    """The overlap sweep tombstones a previous version whose window lapsed."""
    reset_in_memory_stores()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    authority = CredentialAuthority()
    await authority.create_pending(tenant, "coinbase", _ENV, _SLOT, "v1", created_by="a")
    await authority.activate(tenant, "coinbase", _ENV, _SLOT, credential_version=1, actor="a")
    await authority.rotate(tenant, "coinbase", _ENV, _SLOT, "v2", actor="a", expected_active_version=1)
    assert set(await authority.get_verification_secrets(tenant, "coinbase", _ENV, _SLOT)) == {"v2", "v1"}

    # Force-expire the overlap window on the previous version.
    rows = await authority._repo.versions_for_slot(tenant, "coinbase", _ENV, _SLOT)
    prev = [r for r in rows if r.get("state") == CredentialState.PREVIOUS][0]
    await authority._repo.update(
        prev["id"],
        {"rotation_overlap_expires_at": (utc_now() - timedelta(hours=1)).isoformat()},
    )

    report = await sweep_once(repo=authority._repo, authority=authority)
    assert report["tombstoned_overlap"] == 1

    rows = await authority._repo.versions_for_slot(tenant, "coinbase", _ENV, _SLOT)
    assert not [r for r in rows if r.get("state") == CredentialState.PREVIOUS]
    tombstones = [r for r in rows if r.get("state") == CredentialState.TOMBSTONED]
    assert tombstones and all(r.get("encrypted_value") == "" for r in tombstones)
    # The active version is untouched and still resolvable.
    assert await authority.get_active_secret(tenant, "coinbase", _ENV, _SLOT) == "v2"


async def test_sweep_emits_revoked_demotion_hook():
    """Revoked credentials fire the lifecycle-demotion hook (metric fallback
    when the readiness seam is unseeded — never a crash)."""
    reset_in_memory_stores()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    authority = CredentialAuthority()
    await authority.create_pending(tenant, "coinbase", _ENV, _SLOT, "v1", created_by="a")
    await authority.activate(tenant, "coinbase", _ENV, _SLOT, credential_version=1, actor="a")
    await authority.revoke(tenant, "coinbase", _ENV, _SLOT, actor="a")

    report = await sweep_once(repo=authority._repo, authority=authority)
    # Either the readiness seam demoted (seeded) or the metric-only fallback
    # fired — but the lifecycle change was always observed.
    assert report["demoted_readiness"] >= 0
    assert report["demotion_metrics_only"] >= 1
