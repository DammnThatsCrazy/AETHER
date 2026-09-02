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

import json
from typing import Optional

from shared.common.common import utc_now

from services.security.repositories import _ScopedRepo

from .models import VerificationChallenge, VerificationEvidence


# Backing tables (JSONB `data` column, tenant-scoped).
CHALLENGES_TABLE = "identity_verification_challenges"
EVIDENCE_TABLE = "identity_verification_evidence"

# Challenge states that are still "live" (may still be validated/consumed).
_ACTIVE_CHALLENGE_STATES = {"issued", "validated"}


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
        """Atomically bump ``attempt_count`` and lock at ``max_attempts``.

        Concurrency contract: a burst of concurrent OTP verifications must never
        lose an increment (a lost update would under-count attempts and weaken
        the lock, letting a burst exceed ``max_attempts``). The Postgres path
        does the read-modify-write in ONE ``UPDATE ... RETURNING`` statement; the
        in-memory path performs a compare-and-set directly on the shared store
        with NO ``await`` between reading and writing, so under ``asyncio`` a
        second coroutine cannot interleave and read a stale count.
        """
        pool = await self._ensure_pool()
        if pool is not None:
            row = await pool.fetchrow(
                f"""
                UPDATE {self.table_name}
                SET data = jsonb_set(
                        jsonb_set(
                            data,
                            '{{attempt_count}}',
                            to_jsonb(COALESCE((data->>'attempt_count')::int, 0) + 1)
                        ),
                        '{{state}}',
                        CASE
                            WHEN COALESCE((data->>'attempt_count')::int, 0) + 1
                                 >= COALESCE((data->>'max_attempts')::int, 5)
                            THEN '"locked"'::jsonb
                            ELSE data->'state'
                        END
                    ),
                    updated_at = NOW()
                WHERE id = $1 AND tenant_id = $2
                RETURNING data
                """,
                challenge_id,
                tenant_id,
            )
            return json.loads(row["data"]) if row is not None else None

        # In-memory compare-and-set: no await between read and write.
        record = self._store.get(challenge_id)
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        attempts = int(record.get("attempt_count", 0)) + 1
        record["attempt_count"] = attempts
        if attempts >= int(record.get("max_attempts", 5)):
            record["state"] = "locked"
        record["updated_at"] = utc_now().isoformat()
        return record

    async def consume_atomic(
        self, tenant_id: str, challenge_id: str
    ) -> Optional[dict]:
        """Guarded one-time consume of a validated challenge.

        Concurrency contract: exactly one of any number of concurrent callers
        may transition a ``validated`` challenge to ``consumed``; every other
        caller (and any call on an already consumed / expired / locked / issued
        row) gets ``None``. This prevents a double-consume that would mint two
        evidence rows for one challenge.

        The Postgres path relies on a single conditional ``UPDATE``: the
        ``WHERE ... data->>'state' = 'validated'`` predicate is evaluated
        atomically, so only the first statement to run flips the state and gets
        a ``RETURNING`` row; a concurrent statement matches zero rows and
        returns ``None``. The in-memory path performs a compare-and-set directly
        on the shared store with NO ``await`` between the state check and the
        write, so two gathered coroutines cannot both observe ``validated``.
        """
        now_iso = utc_now().isoformat()
        pool = await self._ensure_pool()
        if pool is not None:
            row = await pool.fetchrow(
                f"""
                UPDATE {self.table_name}
                SET data = jsonb_set(
                        jsonb_set(data, '{{state}}', '"consumed"'),
                        '{{consumed_at}}',
                        to_jsonb($3::text)
                    ),
                    updated_at = NOW()
                WHERE id = $1
                  AND tenant_id = $2
                  AND data->>'state' = 'validated'
                RETURNING data
                """,
                challenge_id,
                tenant_id,
                now_iso,
            )
            # No row returned => the row was not 'validated' (already consumed by
            # a concurrent caller, or never validated): treat as already-consumed.
            return json.loads(row["data"]) if row is not None else None

        # In-memory compare-and-set: no await between read and write.
        record = self._store.get(challenge_id)
        if (
            record is None
            or record.get("tenant_id") != tenant_id
            or record.get("state") != "validated"
        ):
            return None
        record["state"] = "consumed"
        record["consumed_at"] = now_iso
        record["updated_at"] = now_iso
        return record


class VerificationEvidenceRepository(_ScopedRepo):
    """Tenant-scoped persistence for verification evidence rows."""

    def __init__(self) -> None:
        super().__init__(EVIDENCE_TABLE)

    async def create(self, evidence: VerificationEvidence) -> dict:
        return await self.insert(evidence.id, evidence.to_record())

    async def get_for_tenant(
        self, tenant_id: str, evidence_id: str
    ) -> Optional[dict]:
        record = await self.find_by_id(evidence_id)
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return record

    async def get_active_for_identifier(
        self, tenant_id: str, identifier_type: str, identifier_hash: str
    ) -> list[dict]:
        rows = await self.list_for_tenant(
            tenant_id,
            extra={
                "identifier_type": identifier_type,
                "identifier_hash": identifier_hash,
            },
        )
        return [r for r in rows if r.get("status") == "active"]

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
