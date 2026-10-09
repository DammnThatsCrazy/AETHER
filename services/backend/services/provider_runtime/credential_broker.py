"""Credential broker — the runtime's single seam onto the credential platform.

Wraps the existing :class:`~shared.credentials.service.CredentialService`
singleton so the runtime only ever manipulates **refs**, never plaintext.
Legacy refs are tenant/provider strings
(``provider:{tenant_id}:{identity_key}``). New provider connections append a
versioned digest of their connection ID so same-tenant connections cannot
overwrite each other's credentials. Refs name stored
:class:`~shared.credentials.types.StructuredCredential` values.

Secret reads are explicit and auditable: ``resolve`` returns the structured
credential (masked ``SecretStr`` fields) for trusted resolvers; ``reveal``
returns the same structured credential and signals the caller intends to unwrap
a secret via ``SecretStr.get_secret_value()``. Plaintext never appears in refs,
connection ``config``, or ``ProviderConnection`` records.
"""

from __future__ import annotations

import hashlib
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

    def provider_ref(
        self,
        tenant_id: str,
        identity_key: str,
        *,
        connection_id: Optional[str] = None,
    ) -> str:
        """Return a provider credential ref, scoped to a connection when supplied.

        The two-argument form preserves the legacy tenant/provider ref for
        callers and persisted connections that still use it. New connection
        credentials must pass ``connection_id``; its digest keeps the ref
        opaque while separating same-tenant connections to the same provider.
        """
        legacy_ref = f"provider:{tenant_id}:{identity_key}"
        if connection_id is None:
            return legacy_ref
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("connection_id must be non-empty for a scoped provider ref")
        connection_digest = hashlib.sha256(connection_id.encode("utf-8")).hexdigest()
        return f"{legacy_ref}:connection:v2:{connection_digest}"

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

    async def delete(self, tenant_id: str, ref: str) -> bool:
        """Hard-delete credential material from the configured backend.

        Unlike ``revoke``, which can retain an encrypted revoked record in
        external secret stores, this removes the provider secret object where
        the backend supports deletion.
        """
        return bool(await self._service.delete(tenant_id, ref))


# Process-wide broker singleton — every runtime component shares one.
credential_broker = CredentialBroker()

__all__ = ["CredentialBroker", "credential_broker"]
