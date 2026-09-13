"""``credential_service`` — the application-facing credential facade.

Thin, backend-agnostic surface over the configured :class:`CredentialBackend`.
Callers (connector secrets, BYOK vault, future resolvers) use this instead of a
concrete backend so the storage authority stays swappable.

Only :meth:`reveal` / :meth:`get` return plaintext, and both are explicit,
auditable calls. Every other method returns masked metadata.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.credentials.interface import (
    CredentialBackend,
    CredentialBackendHealth,
    CredentialMetadata,
)
from shared.credentials.types import (
    ApiKeyCredential,
    MultiCredential,
    OAuthTokenCredential,
    StructuredCredential,
)
from shared.logger.logger import get_logger

logger = get_logger("aether.credentials.service")


def connector_ref(tenant_id: str, connector_type: str) -> str:
    """Canonical credential ref for a tenant connector secret."""
    return f"connector:{tenant_id}:{connector_type}"


def byok_ref(category: str, provider_name: str) -> str:
    """Canonical credential ref for a BYOK provider key."""
    return f"byok:{category}:{provider_name}"


def _primary_secret(cred: StructuredCredential) -> Optional[str]:
    """Reveal the single most-relevant secret string for a credential.

    Used by legacy string-oriented resolvers (connector secrets, BYOK
    ``get_key``) that expect one opaque string.
    """
    if isinstance(cred, ApiKeyCredential):
        return cred.api_key.get_secret_value()
    if isinstance(cred, OAuthTokenCredential):
        return cred.access_token.get_secret_value()
    if isinstance(cred, MultiCredential):
        inner = cred.credentials.get("primary") or next(iter(cred.credentials.values()), None)
        return _primary_secret(inner) if inner is not None else None
    # Fall back to the first SecretStr field on the model.
    from pydantic import SecretStr

    for value in dict(cred).values():
        if isinstance(value, SecretStr):
            return value.get_secret_value()
    return None


class CredentialService:
    """Facade over the configured credential backend."""

    def __init__(self, backend: Optional[CredentialBackend] = None) -> None:
        self._backend_override = backend

    def _backend(self) -> CredentialBackend:
        if self._backend_override is not None:
            return self._backend_override
        from shared.credentials.factory import get_credential_backend

        return get_credential_backend()

    async def create(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Store a credential and return its ref."""
        await self._backend().create(tenant_id, ref, credential, metadata=metadata)
        logger.info("credential.create tenant=%s ref=%s", tenant_id, ref)
        return ref

    async def get(self, tenant_id: str, ref: str) -> Optional[StructuredCredential]:
        """Return the decrypted structured credential (trusted resolvers only)."""
        return await self._backend().get(tenant_id, ref)

    async def reveal(self, tenant_id: str, ref: str) -> Optional[str]:
        """Return the primary secret string, or ``None`` if absent/revoked."""
        cred = await self._backend().get(tenant_id, ref)
        if cred is None:
            return None
        return _primary_secret(cred)

    async def rotate(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
    ) -> CredentialMetadata:
        logger.info("credential.rotate tenant=%s ref=%s", tenant_id, ref)
        return await self._backend().rotate(tenant_id, ref, credential)

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        logger.info("credential.revoke tenant=%s ref=%s", tenant_id, ref)
        return await self._backend().revoke(tenant_id, ref)

    async def delete(self, tenant_id: str, ref: str) -> bool:
        logger.info("credential.delete tenant=%s ref=%s", tenant_id, ref)
        return await self._backend().delete(tenant_id, ref)

    async def metadata(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]:
        return await self._backend().metadata(tenant_id, ref)

    async def list(self, tenant_id: str) -> list[CredentialMetadata]:
        return await self._backend().list(tenant_id)

    async def health_check(self) -> CredentialBackendHealth:
        return await self._backend().health_check()

    @staticmethod
    def masked_metadata(cred: StructuredCredential) -> dict[str, Any]:
        from shared.credentials.types import masked_metadata as _mm

        return _mm(cred)

    @staticmethod
    def masked_identifier(cred: StructuredCredential) -> str:
        from shared.credentials.types import masked_identifier as _mi

        return _mi(cred)


credential_service = CredentialService()


__all__ = ["CredentialService", "credential_service", "byok_ref", "connector_ref"]
