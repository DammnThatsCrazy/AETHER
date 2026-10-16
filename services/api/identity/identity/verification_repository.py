"""Tenant-scoped persistence for identity assurance / verification records.

Two append-style stores back the ownership-verification flow:

* :class:`VerificationChallengeRepository` — single-use OTP/magic-link
  challenges (issued → validated → consumed), with attempt-count locking.
* :class:`VerificationEvidenceRepository` — durable proof that an identifier's
  ownership was verified, consumed by the resolver to raise assurance.

Both subclass the shared tenant-scoped ``_ScopedRepo`` (JSONB-backed in
production, in-memory for local dev). Every read is tenant-checked: a row whose
``tenant_id`` differs from the caller's is never returned. This module is
intentionally additive and mirrors ``decision_evidence.py``'s repository shape.
"""

from __future__ import annotations

import asyncio
import json
import hashlib
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary
from typing import AsyncIterator, Optional

from shared.common.common import utc_now

from governance.security.repositories import _ScopedRepo

from .models import VerificationChallenge, VerificationEvidence


# Backing tables (JSONB `data` column, tenant-scoped).
CHALLENGES_TABLE = "identity_verification_challenges"
EVIDENCE_TABLE = "identity_verification_evidence"

# Challenge states that are still "live" (may still be validated/consumed).
_ACTIVE_CHALLENGE_STATES = {"issued", "validated"}
_CONSUME_LOCKS: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    WeakKeyDictionary()
)
_IDENTIFIER_LOCKS: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
] = WeakKeyDictionary()
_IDENTIFIER_LOCK_SEMAPHORES: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[int, tuple[object, asyncio.Semaphore]]
] = WeakKeyDictionary()


def _consume_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _CONSUME_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _CONSUME_LOCKS[loop] = lock
    return lock


def _identifier_lock(name: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _IDENTIFIER_LOCKS.get(loop)
    if locks is None:
        locks = {}
        _IDENTIFIER_LOCKS[loop] = locks
    lock = locks.get(name)
    if lock is None:
        lock = locks[name] = asyncio.Lock()
    return lock


def _identifier_lock_semaphore(pool: object) -> asyncio.Semaphore:
    """Reserve one pool connection for repository queries while locks are held."""
    loop = asyncio.get_running_loop()
    semaphores = _IDENTIFIER_LOCK_SEMAPHORES.get(loop)
    if semaphores is None:
        semaphores = {}
        _IDENTIFIER_LOCK_SEMAPHORES[loop] = semaphores
    pool_key = id(pool)
    cached = semaphores.get(pool_key)
    if cached is not None and cached[0] is pool:
        return cached[1]
    get_max_size = getattr(pool, "get_max_size", None)
    max_size = get_max_size() if callable(get_max_size) else 1
    if max_size < 2:
        raise RuntimeError(
            "identity verification requires a database pool with at least two connections"
        )
    semaphore = asyncio.Semaphore(max_size - 1)
    semaphores[pool_key] = (pool, semaphore)
    return semaphore


def _identifier_lock_name(
    tenant_id: str, identifier_type: str, identifier_hash: str
) -> str:
    normalized_type = identifier_type.strip().lower()
    if normalized_type in {"email", "email_hash"}:
        normalized_type = "email"
    return f"identity-verification:{tenant_id}:{normalized_type}:{identifier_hash}"


class VerificationChallengeRepository(_ScopedRepo):
    """Tenant-scoped persistence for verification challenges."""

    def __init__(self) -> None:
        super().__init__(CHALLENGES_TABLE)

    async def create(self, challenge: VerificationChallenge) -> dict:
        return await self.insert(challenge.id, challenge.to_record())

    async def get_for_tenant(
        self, tenant_id: str, challenge_id: str
    ) -> Optional[dict]:
        record = await self.find_by_id(challenge_id)
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return record

    async def list_active_for_identifier(
        self, tenant_id: str, identifier_hash: str
    ) -> list[dict]:
        rows = await self.list_for_tenant(
            tenant_id, extra={"identifier_hash": identifier_hash}
        )
        return [r for r in rows if r.get("state") in _ACTIVE_CHALLENGE_STATES]

    async def apply_update(
        self, tenant_id: str, challenge_id: str, fields: dict
    ) -> Optional[dict]:
        record = await self.get_for_tenant(tenant_id, challenge_id)
        if record is None:
            return None
        return await self.update(challenge_id, fields)

    async def increment_attempt(
        self, tenant_id: str, challenge_id: str
    ) -> Optional[dict]:
        record = await self.get_for_tenant(tenant_id, challenge_id)
        if record is None:
            return None
        attempts = int(record.get("attempt_count", 0)) + 1
        fields: dict = {"attempt_count": attempts}
        if attempts >= int(record.get("max_attempts", 5)):
            fields["state"] = "locked"
        return await self.update(challenge_id, fields)

    async def record_failed_attempt(
        self, tenant_id: str, challenge_id: str
    ) -> Optional[dict]:
        """Atomically count a failed wallet proof and lock at the limit."""
        pool = await self._ensure_pool()
        if pool is not None:
            await self._ensure_table()
            row = await pool.fetchrow(
                f"""UPDATE {self.table_name}
                    SET data = data || jsonb_build_object(
                        'attempt_count',
                        COALESCE(NULLIF(data->>'attempt_count', '')::integer, 0) + 1,
                        'state', CASE
                            WHEN COALESCE(NULLIF(data->>'attempt_count', '')::integer, 0) + 1
                                 >= COALESCE(NULLIF(data->>'max_attempts', '')::integer, 5)
                            THEN 'locked'
                            ELSE 'issued'
                        END
                    ), updated_at = NOW()
                    WHERE id = $1 AND tenant_id = $2
                      AND data->>'state' = 'issued'
                      AND COALESCE(NULLIF(data->>'attempt_count', '')::integer, 0)
                          < COALESCE(NULLIF(data->>'max_attempts', '')::integer, 5)
                    RETURNING data""",
                challenge_id,
                tenant_id,
            )
            if row is None:
                return None
            data = row["data"]
            return json.loads(data) if isinstance(data, str) else dict(data)

        async with _consume_lock():
            record = await self.get_for_tenant(tenant_id, challenge_id)
            if record is None or record.get("state") != "issued":
                return None
            attempts = int(record.get("attempt_count", 0))
            max_attempts = int(record.get("max_attempts", 5))
            if attempts >= max_attempts:
                return None
            attempts += 1
            state = "locked" if attempts >= max_attempts else "issued"
            return await self.update(
                challenge_id, {"attempt_count": attempts, "state": state}
            )

    async def consume_wallet_atomic(
        self, tenant_id: str, challenge_id: str
    ) -> Optional[dict]:
        """Count a valid attempt and consume an issued wallet challenge once.

        Signature verification happens before this guarded transition. A valid
        signature on the configured final attempt is therefore accepted, while
        concurrent requests cannot resurrect a consumed challenge.
        """
        now = utc_now().isoformat()
        pool = await self._ensure_pool()
        if pool is not None:
            await self._ensure_table()
            row = await pool.fetchrow(
                f"""UPDATE {self.table_name}
                    SET data = data || jsonb_build_object(
                        'state', 'consumed',
                        'attempt_count',
                        COALESCE(NULLIF(data->>'attempt_count', '')::integer, 0) + 1,
                        'consumed_at', $1::text
                    ), updated_at = NOW()
                    WHERE id = $2 AND tenant_id = $3
                      AND data->>'state' = 'issued'
                      AND COALESCE(NULLIF(data->>'attempt_count', '')::integer, 0)
                          < COALESCE(NULLIF(data->>'max_attempts', '')::integer, 5)
                    RETURNING data""",
                now,
                challenge_id,
                tenant_id,
            )
            if row is None:
                return None
            data = row["data"]
            return json.loads(data) if isinstance(data, str) else dict(data)

        async with _consume_lock():
            record = await self.get_for_tenant(tenant_id, challenge_id)
            if record is None or record.get("state") != "issued":
                return None
            attempts = int(record.get("attempt_count", 0))
            if attempts >= int(record.get("max_attempts", 5)):
                return None
            return await self.update(
                challenge_id,
                {
                    "state": "consumed",
                    "attempt_count": attempts + 1,
                    "consumed_at": now,
                },
            )

    async def consume_atomic(
        self, tenant_id: str, challenge_id: str
    ) -> Optional[dict]:
        """Guarded one-time consume of a validated challenge.

        PostgreSQL performs the state check and transition in one conditional
        UPDATE. Local storage serializes competing consumers on the event loop.
        A row in any other state (already consumed / expired / locked / issued)
        yields ``None``.
        """
        now = utc_now().isoformat()
        pool = await self._ensure_pool()
        if pool is not None:
            await self._ensure_table()
            row = await pool.fetchrow(
                f"""UPDATE {self.table_name}
                    SET data = data || $1::jsonb, updated_at = NOW()
                    WHERE id = $2 AND tenant_id = $3
                      AND data->>'state' = 'validated'
                    RETURNING data""",
                json.dumps({"state": "consumed", "consumed_at": now}),
                challenge_id,
                tenant_id,
            )
            if row is None:
                return None
            data = row["data"]
            return json.loads(data) if isinstance(data, str) else dict(data)

        async with _consume_lock():
            record = await self.get_for_tenant(tenant_id, challenge_id)
            if record is None or record.get("state") != "validated":
                return None
            return await self.update(
                challenge_id,
                {"state": "consumed", "consumed_at": now},
            )


class VerificationEvidenceRepository(_ScopedRepo):
    """Tenant-scoped persistence for verification evidence rows."""

    def __init__(self) -> None:
        super().__init__(EVIDENCE_TABLE)

    @asynccontextmanager
    async def identifier_guard(
        self, tenant_id: str, identifier_type: str, identifier_hash: str
    ) -> AsyncIterator[None]:
        """Serialize proof issuance, replay, revocation, and cleanup per identifier.

        Local mode uses an event-loop scoped lock. PostgreSQL mode holds a
        session advisory lock on a dedicated pooled connection so concurrent
        service processes use the same lock boundary.
        """
        name = _identifier_lock_name(tenant_id, identifier_type, identifier_hash)
        pool = await self._ensure_pool()
        if pool is None:
            async with _identifier_lock(name):
                yield
            return

        async with _identifier_lock_semaphore(pool):
            conn = await pool.acquire()
            lock_key = int.from_bytes(
                hashlib.sha256(name.encode("utf-8")).digest()[:8],
                "big",
                signed=True,
            )
            acquired = False
            lock_attempted = False
            try:
                # If cancellation lands while asyncpg is waiting for the
                # result, the server may already own the session lock. Close
                # that connection unless a successful unlock is confirmed.
                lock_attempted = True
                await conn.execute("SELECT pg_advisory_lock($1)", lock_key)
                acquired = True
                yield
            finally:
                if not acquired and lock_attempted:
                    conn.terminate()
                if acquired:
                    try:
                        await conn.execute("SELECT pg_advisory_unlock($1)", lock_key)
                    except BaseException:
                        # A connection that may still own a session lock must
                        # not return to the pool and block later operations.
                        conn.terminate()
                        raise
                await pool.release(conn)

    async def create(self, evidence: VerificationEvidence) -> dict:
        return await self.insert(evidence.id, evidence.to_record())

    async def get_for_tenant(
        self, tenant_id: str, evidence_id: str
    ) -> Optional[dict]:
        record = await self.find_by_id(evidence_id)
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return record

    async def expire_if_active(
        self, tenant_id: str, evidence_id: str
    ) -> Optional[dict]:
        """Atomically mark a tenant-owned active evidence row as expired."""
        now = utc_now().isoformat()
        pool = await self._ensure_pool()
        if pool is None:
            record = await self.get_for_tenant(tenant_id, evidence_id)
            if record is None or record.get("status") != "active":
                return record
            return await self.update(
                evidence_id, {"status": "expired", "expired_at": now}
            )

        await self._ensure_table()
        row = await pool.fetchrow(
            f"""UPDATE {self.table_name}
                SET data = data || jsonb_build_object(
                        'status', 'expired', 'expired_at', $1::text
                    ),
                    updated_at = NOW()
                WHERE id = $2 AND tenant_id = $3
                  AND data->>'status' = 'active'
                RETURNING data""",
            now,
            evidence_id,
            tenant_id,
        )
        if row is None:
            return await self.get_for_tenant(tenant_id, evidence_id)
        data = row["data"]
        return json.loads(data) if isinstance(data, str) else dict(data)

    async def get_active_for_identifier(
        self,
        tenant_id: str,
        identifier_type: str,
        identifier_hash: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self.list_for_tenant(
            tenant_id,
            limit=limit,
            offset=offset,
            extra={
                "identifier_type": identifier_type,
                "identifier_hash": identifier_hash,
                "status": "active",
            },
        )
        return rows

    async def get_for_entity(
        self, tenant_id: str, canonical_entity_id: str
    ) -> list[dict]:
        return await self.list_for_tenant(
            tenant_id, extra={"canonical_entity_id": canonical_entity_id}
        )

    async def revoke(
        self, tenant_id: str, evidence_id: str, reason: str = ""
    ) -> Optional[dict]:
        record = await self.get_for_tenant(tenant_id, evidence_id)
        if record is None:
            return None
        metadata = dict(record.get("metadata") or {})
        metadata["revoke_reason"] = reason
        return await self.update(
            evidence_id,
            {
                "status": "revoked",
                "revoked_at": utc_now().isoformat(),
                "metadata": metadata,
            },
        )

    async def bind_entity(
        self, tenant_id: str, evidence_id: str, canonical_entity_id: str
    ) -> Optional[dict]:
        record = await self.get_for_tenant(tenant_id, evidence_id)
        if record is None:
            return None
        return await self.update(
            evidence_id, {"canonical_entity_id": canonical_entity_id}
        )
