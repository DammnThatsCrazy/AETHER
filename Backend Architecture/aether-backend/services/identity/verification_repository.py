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
        record = await self.get_for_tenant(tenant_id, challenge_id)
        if record is None:
            return None
        attempts = int(record.get("attempt_count", 0)) + 1
        fields: dict = {"attempt_count": attempts}
        if attempts >= int(record.get("max_attempts", 5)):
            fields["state"] = "locked"
        return await self.update(challenge_id, fields)

    async def consume_atomic(
        self, tenant_id: str, challenge_id: str
    ) -> Optional[dict]:
        """Guarded one-time consume of a validated challenge.

        Re-reads the row and, only if it is currently ``validated``, transitions
        it to ``consumed`` and stamps ``consumed_at``. A row in any other state
        (already consumed / expired / locked / issued) yields ``None``. This is
        best-effort atomic under the in-memory / JSONB backend — there is no
        row-level lock, so concurrent callers rely on the read-check-write here.
        """
        record = await self.get_for_tenant(tenant_id, challenge_id)
        if record is None or record.get("state") != "validated":
            return None
        return await self.update(
            challenge_id,
            {"state": "consumed", "consumed_at": utc_now().isoformat()},
        )


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
