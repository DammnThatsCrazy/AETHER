"""Persistence for the Kyber device-trust plane.

Every repository here is a thin, typed view over one table created by the
``kyber_workforce_identity`` migration. The shapes themselves live in
:mod:`services.kyber.access.contracts` — this module never redefines them, it
only stores and hydrates them.

Two additional stores back the single-use challenge ceremonies (WebAuthn and
device proof). They are deliberately server-side: a challenge that the browser
could choose, replay or extend would defeat both ceremonies, so the server
issues an opaque id, holds the challenge bytes, and *deletes* the row the first
time it is consumed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, TypeVar

from pydantic import BaseModel

from repositories.repos import BaseRepository
from shared.temporal.instant import try_parse_instant
from shared.common.common import utc_now

from ..access.contracts import (
    DeviceApprovalEvent,
    DeviceProofKey,
    TrustedDevice,
    WebAuthnCredential,
    now_iso,
)

M = TypeVar("M", bound=BaseModel)

#: Table names owned by this package.
TABLE_TRUSTED_DEVICES = "kyber_trusted_devices"
TABLE_WEBAUTHN_CREDENTIALS = "kyber_webauthn_credentials"
TABLE_DEVICE_PROOF_KEYS = "kyber_device_proof_keys"
TABLE_DEVICE_APPROVAL_EVENTS = "kyber_device_approval_events"
TABLE_WEBAUTHN_CHALLENGES = "kyber_webauthn_challenges"
TABLE_DEVICE_PROOF_CHALLENGES = "kyber_device_proof_challenges"

#: Ceiling on rows returned by an unbounded listing helper.
_LIST_LIMIT = 200


def parse_ts(value: Any) -> Optional[datetime]:
    """Parse a stored ISO timestamp into an aware UTC datetime, or ``None``.

    Every expiry comparison in this package runs on a deny path, so parsing
    must never raise: an unreadable timestamp has to read as "no usable
    expiry" and let the caller fail closed, not surface as a 500 that a client
    could provoke deliberately.
    """
    if not isinstance(value, str) or not value:
        return None
    # The canonical parser, not a local one. It rejects timezone-naive input
    # rather than assuming UTC, which is the behaviour we want here: a device
    # or credential expiry whose zone is unknown must read as unusable, not as
    # a moment we guessed.
    instant, _reason = try_parse_instant(value)
    return instant


def is_expired(value: Any, *, missing_is_expired: bool = True) -> bool:
    """True when an ISO timestamp is absent, unreadable or already past."""
    parsed = parse_ts(value)
    if parsed is None:
        return missing_is_expired
    return parsed <= utc_now()


def hydrate(model_cls: type[M], row: Optional[dict[str, Any]]) -> Optional[M]:
    """Rebuild a contract model from a stored row.

    ``BaseRepository.insert`` decorates every row with ``id``/``created_at``/
    ``updated_at`` bookkeeping columns. Filtering to declared model fields keeps
    hydration total: a bookkeeping column added later can never turn into a
    validation error on a read path that authorization depends on.
    """
    if row is None:
        return None
    return model_cls(**{k: v for k, v in row.items() if k in model_cls.model_fields})


def hydrate_all(model_cls: type[M], rows: list[dict[str, Any]]) -> list[M]:
    out: list[M] = []
    for row in rows:
        model = hydrate(model_cls, row)
        if model is not None:
            out.append(model)
    return out


class _ModelRepository(BaseRepository):
    """Insert-or-update helper shared by the four device tables."""

    async def _save(self, record_id: str, model: BaseModel) -> None:
        payload = model.model_dump()
        if await self.find_by_id(record_id) is None:
            await self.insert(record_id, payload)
        else:
            await self.update(record_id, payload)


class TrustedDeviceRepository(_ModelRepository):
    """Devices an operator has enrolled, in every approval state."""

    def __init__(self) -> None:
        super().__init__(TABLE_TRUSTED_DEVICES)

    async def save(self, device: TrustedDevice) -> TrustedDevice:
        await self._save(device.device_id, device)
        return device

    async def get(self, device_id: str) -> Optional[TrustedDevice]:
        return hydrate(TrustedDevice, await self.find_by_id(device_id))

    async def find_by_operator(
        self, operator_id: str, *, limit: int = _LIST_LIMIT
    ) -> list[TrustedDevice]:
        rows = await self.find_many({"operator_id": operator_id}, limit=limit)
        return hydrate_all(TrustedDevice, rows)

    async def find_by_grant_hash(self, grant_hash: str) -> Optional[TrustedDevice]:
        """Resolve the device holding a live grant.

        A unique partial index guarantees at most one non-revoked device per
        grant hash. Revoked devices keep their hash so a presented cookie still
        resolves and is denied with ``device_revoked`` rather than silently
        looking like an unknown device.
        """
        if not grant_hash:
            return None
        rows = await self.find_many({"grant_hash": grant_hash}, limit=2)
        live = [r for r in rows if not r.get("revoked_at")]
        return hydrate(TrustedDevice, (live or rows or [None])[0])

    async def find_by_state(
        self, operator_id: str, approval_state: str, *, limit: int = _LIST_LIMIT
    ) -> list[TrustedDevice]:
        rows = await self.find_many(
            {"operator_id": operator_id, "approval_state": approval_state}, limit=limit
        )
        return hydrate_all(TrustedDevice, rows)

    async def delete_by_operator(self, operator_id: str) -> int:
        """Physically erase every device row for one operator (DSR erasure, M8-E1).

        Offboarding *revokes* a device — the row stays so the audit trail and a
        revoke-then-re-enroll ceremony still resolve, and every transition keeps
        its ``DeviceApprovalEvent``. A data-subject erasure is the opposite act:
        it must physically erase the operator's device personal data. This is the
        DSR hook the consent erasure job calls; the append-only
        ``kyber_device_approval_events`` ledger is deliberately NOT covered
        (storage policy ``preserve`` / legal hold).
        """
        return await self.delete_by_entity("operator_id", operator_id)


class WebAuthnCredentialRepository(_ModelRepository):
    """Platform authenticator credentials. Public key and counter only."""

    def __init__(self) -> None:
        super().__init__(TABLE_WEBAUTHN_CREDENTIALS)

    async def save(self, credential: WebAuthnCredential) -> WebAuthnCredential:
        await self._save(credential.credential_pk, credential)
        return credential

    async def get(self, credential_pk: str) -> Optional[WebAuthnCredential]:
        return hydrate(WebAuthnCredential, await self.find_by_id(credential_pk))

    async def find_by_credential_id(self, credential_id: str) -> Optional[WebAuthnCredential]:
        """Look up by the authenticator-issued id, ignoring revoked rows.

        Revocation is what frees the unique index, so an operator may re-enroll
        the same authenticator after wiping a machine.
        """
        if not credential_id:
            return None
        rows = await self.find_many({"credential_id": credential_id}, limit=5)
        live = [r for r in rows if not r.get("revoked_at")]
        return hydrate(WebAuthnCredential, live[0] if live else None)

    async def find_by_device(self, device_id: str) -> list[WebAuthnCredential]:
        rows = await self.find_many({"device_id": device_id}, limit=_LIST_LIMIT)
        return hydrate_all(WebAuthnCredential, rows)

    async def find_by_operator(
        self, operator_id: str, *, include_revoked: bool = False
    ) -> list[WebAuthnCredential]:
        rows = await self.find_many({"operator_id": operator_id}, limit=_LIST_LIMIT)
        if not include_revoked:
            rows = [r for r in rows if not r.get("revoked_at")]
        return hydrate_all(WebAuthnCredential, rows)

    async def delete_by_operator(self, operator_id: str) -> int:
        """Physically erase every WebAuthn credential row for one operator (M8-E1).

        Revocation marks a credential revoked and retains it for forensics; a
        data-subject erasure physically deletes the stored public key + counter
        data. The same DSR boundary as :meth:`TrustedDeviceRepository.delete_by_operator`.
        """
        return await self.delete_by_entity("operator_id", operator_id)


class DeviceProofKeyRepository(_ModelRepository):
    """Browser-profile-bound ECDSA P-256 public keys."""

    def __init__(self) -> None:
        super().__init__(TABLE_DEVICE_PROOF_KEYS)

    async def save(self, key: DeviceProofKey) -> DeviceProofKey:
        await self._save(key.proof_key_id, key)
        return key

    async def get(self, proof_key_id: str) -> Optional[DeviceProofKey]:
        return hydrate(DeviceProofKey, await self.find_by_id(proof_key_id))

    async def find_by_device(
        self, device_id: str, *, include_revoked: bool = False
    ) -> list[DeviceProofKey]:
        rows = await self.find_many({"device_id": device_id}, limit=_LIST_LIMIT)
        if not include_revoked:
            rows = [r for r in rows if not r.get("revoked_at")]
        return hydrate_all(DeviceProofKey, rows)

    async def find_active_by_device(self, device_id: str) -> Optional[DeviceProofKey]:
        """The one key a proof must verify against.

        When more than one live key exists (re-enrollment inside the same
        browser profile), the newest wins; older keys stay readable for
        forensics but never authorize on their own.
        """
        keys = await self.find_by_device(device_id)
        if not keys:
            return None
        return sorted(keys, key=lambda k: k.created_at, reverse=True)[0]

    async def find_by_operator(self, operator_id: str) -> list[DeviceProofKey]:
        rows = await self.find_many({"operator_id": operator_id}, limit=_LIST_LIMIT)
        return hydrate_all(DeviceProofKey, rows)

    async def delete_by_operator(self, operator_id: str) -> int:
        """Physically erase every device proof key for one operator (M8-E1).

        Same contract as the sibling device repos: a data-subject erasure deletes
        the stored public-key material (the private half never leaves the enrolled
        profile and is not exportable). The proof-key rows are what authorize
        device-bound sessions, so erasure is what actually ends device proof.
        """
        return await self.delete_by_entity("operator_id", operator_id)


class DeviceApprovalEventRepository(_ModelRepository):
    """Append-only record of every device-state transition."""

    def __init__(self) -> None:
        super().__init__(TABLE_DEVICE_APPROVAL_EVENTS)

    async def append(self, event: DeviceApprovalEvent) -> DeviceApprovalEvent:
        await self.insert(event.event_id, event.model_dump())
        return event

    async def find_by_device(
        self, device_id: str, *, limit: int = _LIST_LIMIT
    ) -> list[DeviceApprovalEvent]:
        rows = await self.find_many({"device_id": device_id}, limit=limit)
        return hydrate_all(DeviceApprovalEvent, rows)

    async def find_by_operator(
        self, operator_id: str, *, limit: int = _LIST_LIMIT
    ) -> list[DeviceApprovalEvent]:
        rows = await self.find_many({"operator_id": operator_id}, limit=limit)
        return hydrate_all(DeviceApprovalEvent, rows)


class ChallengeRepository(BaseRepository):
    """Single-use, TTL-bound challenge store.

    ``consume`` deletes before it validates. That ordering is the whole point:
    a replayed challenge id finds nothing on the second attempt regardless of
    whether the first attempt succeeded, so a captured ceremony cannot be
    re-run even within the TTL.
    """

    async def issue(
        self,
        *,
        challenge_id: str,
        challenge: str,
        subject_id: str,
        purpose: str,
        ttl_seconds: int,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        expires_at = (utc_now() + timedelta(seconds=ttl_seconds)).isoformat()
        await self.insert(
            challenge_id,
            {
                "challenge_id": challenge_id,
                "challenge": challenge,
                "subject_id": subject_id,
                "purpose": purpose,
                "issued_at": now_iso(),
                "expires_at": expires_at,
                "metadata": metadata or {},
            },
        )
        return challenge_id

    async def consume(
        self, challenge_id: str, *, subject_id: str, purpose: str
    ) -> Optional[dict[str, Any]]:
        """Return the challenge row exactly once, or ``None``."""
        if not challenge_id:
            return None
        row = await self.find_by_id(challenge_id)
        await self.delete(challenge_id)
        if row is None:
            return None
        if row.get("purpose") != purpose or row.get("subject_id") != subject_id:
            return None
        if is_expired(row.get("expires_at")):
            return None
        return row

    async def purge_expired(self, *, limit: int = 500) -> int:
        """Best-effort sweep. Expiry is enforced on read; this only reclaims rows."""
        removed = 0
        for row in await self.find_many({}, limit=limit):
            if not is_expired(row.get("expires_at")):
                continue
            if await self.delete(str(row.get("id") or row.get("challenge_id"))):
                removed += 1
        return removed


class WebAuthnChallengeRepository(ChallengeRepository):
    def __init__(self) -> None:
        super().__init__(TABLE_WEBAUTHN_CHALLENGES)


class DeviceProofChallengeRepository(ChallengeRepository):
    def __init__(self) -> None:
        super().__init__(TABLE_DEVICE_PROOF_CHALLENGES)


__all__ = [
    "ChallengeRepository",
    "DeviceApprovalEventRepository",
    "DeviceProofChallengeRepository",
    "DeviceProofKeyRepository",
    "TABLE_DEVICE_APPROVAL_EVENTS",
    "TABLE_DEVICE_PROOF_CHALLENGES",
    "TABLE_DEVICE_PROOF_KEYS",
    "TABLE_TRUSTED_DEVICES",
    "TABLE_WEBAUTHN_CHALLENGES",
    "TABLE_WEBAUTHN_CREDENTIALS",
    "TrustedDeviceRepository",
    "WebAuthnChallengeRepository",
    "WebAuthnCredentialRepository",
    "hydrate",
    "hydrate_all",
    "is_expired",
    "parse_ts",
]
