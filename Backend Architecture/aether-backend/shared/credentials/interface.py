"""Credential backend interface + masked (secret-free) metadata models.

A :class:`CredentialBackend` is the pluggable storage authority for tenant
credentials. Concrete backends (in-memory, local-encrypted Postgres, AWS Secrets
Manager) implement this contract; the ``credential_service`` facade and legacy
consolidations (BYOK vault, connector secrets) talk only to this interface.

Only ``get`` returns plaintext (a decrypted :data:`StructuredCredential`, for
trusted resolvers). Every other read returns a :class:`CredentialMetadata`,
which by construction carries NO secret fields.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.certification.readiness import CredentialReadiness
from shared.credentials.types import StructuredCredential
from shared.temporal.instant import ensure_aware_utc

# Lifecycle status tokens stored in the durable ``status`` column. Distinct from
# the readiness projection surfaced on ``CredentialMetadata.status``.
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"


class CredentialBackendError(Exception):
    """Base error for credential backend failures."""


class CredentialBackendNotConfigured(CredentialBackendError):
    """Raised when a backend is selected but its dependencies/config are absent."""


class CredentialMetadata(BaseModel):
    """Masked, secret-free view of a stored credential.

    This model has NO secret fields. ``masked_identifier`` is a one-way,
    stable, non-reversible tag (``"****" + last4(sha256(...))``). ``metadata``
    carries non-secret display extras only (endpoints, categories, scopes).
    """

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    ref: str
    credential_type: str
    version: int
    status: CredentialReadiness
    masked_identifier: str
    created_at: datetime
    updated_at: datetime
    rotated_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CredentialBackendHealth(BaseModel):
    backend: str
    durable: bool
    healthy: bool
    detail: str = ""


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return ensure_aware_utc(value)


def _readiness_for(lifecycle_status: str, expires_at: Optional[datetime]) -> CredentialReadiness:
    """Project the durable lifecycle status onto a readiness token.

    active + unexpired -> PARTNER_LIVE (a supplied, usable credential)
    active + expired   -> DEGRADED
    revoked            -> DISABLED
    """
    if lifecycle_status == STATUS_REVOKED:
        return CredentialReadiness.DISABLED
    exp = _aware(expires_at)
    if exp is not None and datetime.now(timezone.utc) >= exp:
        return CredentialReadiness.DEGRADED
    return CredentialReadiness.PARTNER_LIVE


def make_metadata(
    *,
    tenant_id: str,
    ref: str,
    credential_type: str,
    version: int,
    lifecycle_status: str,
    masked_identifier: str,
    created_at: datetime,
    updated_at: datetime,
    rotated_at: Optional[datetime] = None,
    revoked_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
    extra: Optional[dict[str, Any]] = None,
) -> CredentialMetadata:
    """Build a :class:`CredentialMetadata` uniformly across backends.

    Centralizing this keeps in-memory and durable backends semantically
    identical (the conformance suite depends on that).
    """
    return CredentialMetadata(
        tenant_id=tenant_id,
        ref=ref,
        credential_type=credential_type,
        version=version,
        status=_readiness_for(lifecycle_status, expires_at),
        masked_identifier=masked_identifier,
        created_at=_aware(created_at),  # type: ignore[arg-type]
        updated_at=_aware(updated_at),  # type: ignore[arg-type]
        rotated_at=_aware(rotated_at),
        revoked_at=_aware(revoked_at),
        expires_at=_aware(expires_at),
        metadata=dict(extra or {}),
    )


class CredentialBackend(abc.ABC):
    """Pluggable storage authority for tenant credentials."""

    @abc.abstractmethod
    async def create(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CredentialMetadata:
        """Store (or replace) a credential at ``ref`` for ``tenant_id``."""

    @abc.abstractmethod
    async def get(self, tenant_id: str, ref: str) -> Optional[StructuredCredential]:
        """Return the decrypted credential, or ``None`` if absent/revoked.

        Plaintext path — for trusted resolvers only.
        """

    @abc.abstractmethod
    async def rotate(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
    ) -> CredentialMetadata:
        """Replace the stored secret and bump the version."""

    @abc.abstractmethod
    async def revoke(self, tenant_id: str, ref: str) -> bool:
        """Mark the credential revoked (retained for audit; ``get`` -> None)."""

    @abc.abstractmethod
    async def delete(self, tenant_id: str, ref: str) -> bool:
        """Hard-delete the credential."""

    @abc.abstractmethod
    async def metadata(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]:
        """Return masked metadata (no plaintext), or ``None`` if absent."""

    @abc.abstractmethod
    async def list(self, tenant_id: str) -> list[CredentialMetadata]:
        """Return masked metadata for every credential owned by ``tenant_id``."""

    @abc.abstractmethod
    async def health_check(self) -> CredentialBackendHealth:
        """Return backend liveness/durability info."""


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_REVOKED",
    "CredentialBackend",
    "CredentialBackendError",
    "CredentialBackendHealth",
    "CredentialBackendNotConfigured",
    "CredentialMetadata",
    "make_metadata",
]
