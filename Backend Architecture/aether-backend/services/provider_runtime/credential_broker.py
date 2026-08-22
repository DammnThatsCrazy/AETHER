"""Credential broker — the runtime's single seam onto the credential platform.

Wraps the existing :class:`~shared.credentials.service.CredentialService`
singleton so the runtime only ever manipulates **refs**, never plaintext. A ref
is an opaque, tenant-namespaced string (``provider:{tenant_id}:{identity_key}``)
that names a stored :class:`~shared.credentials.types.StructuredCredential`.

Secret reads are explicit and auditable: ``resolve`` returns the structured
credential (masked ``SecretStr`` fields) for trusted resolvers; ``reveal``
returns the same structured credential and signals the caller intends to unwrap
a secret via ``SecretStr.get_secret_value()``. Plaintext never appears in refs,
connection ``config``, or ``ProviderConnection`` records.
"""

from __future__ import annotations

from typing import Optional

from shared.credentials.types import StructuredCredential

# Process-wide facade. Tests inject a lightweight backend via CredentialService
# directly rather than mutating this singleton.
from shared.credentials.service import credential_service as _default_service


class CredentialBroker:
    """Wraps the existing ``credential_service``. NO plaintext in refs/config."""

    def __init__(self, service=None) -> None:
        # Defaults to the process-wide credential_service singleton.
        self._service = service if service is not None else _default_service

    def provider_ref(self, tenant_id: str, identity_key: str) -> str:
        """``provider:{tenant_id}:{identity_key}`` — a ref, never a secret."""
        return f"provider:{tenant_id}:{identity_key}"

    async def store(
        self,
        tenant_id: str,
        ref: str,
        credential: StructuredCredential,
    ) -> None:
        """Persist a structured credential under ``ref`` (no plaintext stored)."""
        await self._service.create(tenant_id, ref, credential)

    async def resolve(
        self, tenant_id: str, ref: str
    ) -> Optional[StructuredCredential]:
        """Return the stored structured credential (trusted resolver surface).

        Mirrors ``credential_service.get`` — secrets remain wrapped in
        ``SecretStr`` and are never stringified by this method.
        """
        return await self._service.get(tenant_id, ref)

    async def reveal(
        self, tenant_id: str, ref: str
    ) -> Optional[StructuredCredential]:
        """Return the stored structured credential for an explicit secret read.

        Same storage read as :meth:`resolve`; semantically signals that the
        caller intends to unwrap a secret field via ``SecretStr``. Absent or
        revoked credentials resolve to ``None``.
        """
        return await self._service.get(tenant_id, ref)

    async def revoke(self, tenant_id: str, ref: str) -> None:
        """Revoke a stored credential by ref (hard-deletes on the backends)."""
        await self._service.revoke(tenant_id, ref)


# Process-wide broker singleton — every runtime component shares one.
credential_broker = CredentialBroker()

__all__ = ["CredentialBroker", "credential_broker"]
