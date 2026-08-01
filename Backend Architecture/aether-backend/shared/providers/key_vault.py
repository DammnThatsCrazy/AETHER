"""
Aether Shared -- BYOK Key Vault

Encrypted storage for tenant-provided API keys.

Storage is delegated to the provider-neutral credential platform
(:mod:`shared.credentials`). Keys are persisted under the ref
``byok:{category}:{provider_name}`` via the configured
:class:`~shared.credentials.interface.CredentialBackend` (Fernet-encrypted rows
in production, in-memory under tests). This module keeps the historical
``BYOKKeyVault`` surface intact so existing callers (provider registry, provider
routes, payment-rails, card-linked feed) need no changes.

DEPRECATED for payment-rail secret resolution: superseded by the durable,
multi-slot :class:`~services.providers.credentials.authority.CredentialAuthority`.
Payment-rail adapters resolve their webhook signing secret from the authority
when ``AETHER_PAYMENT_CREDENTIAL_AUTHORITY_ENABLED`` is set; this vault is slated
for removal once that flag defaults on and all payment-rail callers have cut over
(polling-slot resolution + vault removal are the sequenced follow-up). No runtime
behavior change here — it remains the default read path until cutover.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.credentials.interface import CredentialBackend, CredentialMetadata
from shared.credentials.service import byok_ref
from shared.credentials.types import ApiKeyCredential
from shared.certification.readiness import CredentialReadiness
from shared.logger.logger import get_logger
from shared.temporal.instant import ensure_aware_utc

logger = get_logger("aether.providers.key_vault")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return ensure_aware_utc(value).isoformat()


@dataclass
class StoredKey:
    """A single BYOK key record (metadata view — never carries plaintext)."""

    tenant_id: str
    provider_name: str
    category: str
    encrypted_key: str
    endpoint: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    enabled: bool = True


class BYOKKeyVault:
    """Manages BYOK API keys with encryption at rest via the credential backend.

    The ``encryption_key`` / ``encryption_key_previous`` parameters are retained
    for backward compatibility. Encryption is now owned by the configured
    credential backend (``AETHER_CREDENTIAL_BACKEND``); these values are honoured
    by the backend through the standard ``BYOK_ENCRYPTION_KEY`` env contract.
    """

    def __init__(
        self,
        encryption_key: str = "",
        encryption_key_previous: str = "",
        backend: Optional[CredentialBackend] = None,
    ) -> None:
        self._encryption_key = encryption_key
        self._encryption_key_previous = encryption_key_previous
        self._backend_override = backend
        # Best-effort synchronous cache of masked identifiers, keyed by
        # (tenant_id, provider_name). Populated on store/rotate so the
        # synchronous ``masked_identifier`` accessor can answer without awaiting.
        self._mask_cache: dict[tuple[str, str], str] = {}

    def _backend(self) -> CredentialBackend:
        if self._backend_override is not None:
            return self._backend_override
        from shared.credentials.factory import get_credential_backend

        return get_credential_backend()

    @staticmethod
    def _provider_from_ref(ref: str) -> str:
        return ref.rsplit(":", 1)[-1]

    async def _find(self, tenant_id: str, provider_name: str) -> Optional[CredentialMetadata]:
        """Resolve stored metadata for a (tenant, provider) pair.

        The category is part of the ref but not supplied to lookup-style methods,
        so we scan the tenant's BYOK credentials and match on the stored
        ``provider_name`` (which may itself contain ``:`` — e.g. scoped partner
        provider names), falling back to the ref suffix for legacy rows.
        """
        for md in await self._backend().list(tenant_id):
            if not md.ref.startswith("byok:"):
                continue
            stored = self._byok_aux(md).get("provider_name")
            if stored is not None:
                if stored == provider_name:
                    return md
            elif self._provider_from_ref(md.ref) == provider_name:
                return md
        return None

    @staticmethod
    def _byok_aux(md: CredentialMetadata) -> dict[str, Any]:
        aux = md.metadata.get("byok")
        return dict(aux) if isinstance(aux, dict) else {}

    def _to_stored_key(self, tenant_id: str, md: CredentialMetadata) -> StoredKey:
        aux = self._byok_aux(md)
        provider_name = aux.get("provider_name") or self._provider_from_ref(md.ref)
        enabled = md.status != CredentialReadiness.DISABLED
        return StoredKey(
            tenant_id=tenant_id,
            provider_name=provider_name,
            category=aux.get("category", ""),
            encrypted_key="",  # ciphertext never surfaces through this view
            endpoint=aux.get("endpoint") or None,
            extra=dict(aux.get("extra", {})),
            created_at=_iso(md.created_at),
            updated_at=_iso(md.updated_at),
            enabled=enabled,
        )

    async def store_key(
        self,
        tenant_id: str,
        provider_name: str,
        category: str,
        api_key: str,
        endpoint: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> StoredKey:
        """Encrypt and store a BYOK API key for a tenant."""
        ref = byok_ref(category, provider_name)
        cred = ApiKeyCredential(api_key=api_key)
        aux = {
            "provider_name": provider_name,
            "category": category,
            "endpoint": endpoint or "",
            "extra": dict(extra or {}),
        }
        await self._backend().create(tenant_id, ref, cred, metadata={"byok": aux})
        self._mask_cache[(tenant_id, provider_name)] = self._compute_mask(api_key)
        logger.info(f"BYOK key stored: tenant={tenant_id} provider={provider_name}")
        md = await self._backend().metadata(tenant_id, ref)
        return self._to_stored_key(tenant_id, md) if md else StoredKey(
            tenant_id=tenant_id, provider_name=provider_name, category=category,
            encrypted_key="", endpoint=endpoint, extra=dict(extra or {}),
            created_at=_utc_now(), updated_at=_utc_now(),
        )

    async def get_key(self, tenant_id: str, provider_name: str) -> Optional[str]:
        """Retrieve and decrypt a BYOK key. Returns None if not found/disabled."""
        md = await self._find(tenant_id, provider_name)
        if md is None:
            return None
        cred = await self._backend().get(tenant_id, md.ref)
        if cred is None:
            return None
        if isinstance(cred, ApiKeyCredential):
            return cred.api_key.get_secret_value()
        from shared.credentials.service import _primary_secret

        return _primary_secret(cred)

    async def get_endpoint(self, tenant_id: str, provider_name: str) -> Optional[str]:
        """Get the custom endpoint for a BYOK key."""
        md = await self._find(tenant_id, provider_name)
        if md is None:
            return None
        return self._byok_aux(md).get("endpoint") or None

    async def list_keys(self, tenant_id: str) -> list[dict]:
        """List all BYOK keys for a tenant (keys masked, never exposed)."""
        results: list[dict] = []
        for md in await self._backend().list(tenant_id):
            if not md.ref.startswith("byok:"):
                continue
            aux = self._byok_aux(md)
            results.append({
                "provider_name": aux.get("provider_name") or self._provider_from_ref(md.ref),
                "category": aux.get("category", ""),
                "endpoint": aux.get("endpoint") or None,
                "enabled": md.status != CredentialReadiness.DISABLED,
                "created_at": _iso(md.created_at),
                "updated_at": _iso(md.updated_at),
                "has_key": True,
            })
        return results

    async def delete_key(self, tenant_id: str, provider_name: str) -> bool:
        """Delete a BYOK key."""
        md = await self._find(tenant_id, provider_name)
        if md is None:
            return False
        ok = await self._backend().delete(tenant_id, md.ref)
        if ok:
            self._mask_cache.pop((tenant_id, provider_name), None)
            logger.info(f"BYOK key deleted: tenant={tenant_id} provider={provider_name}")
        return ok

    async def toggle_key(self, tenant_id: str, provider_name: str, enabled: bool) -> bool:
        """Enable or disable a BYOK key without deleting it.

        Disable maps to backend revoke. Re-enable is best-effort: it succeeds
        when a record exists, but the durable un-revoke path requires re-storing
        the key via ``store_key`` (no production caller re-enables today).
        """
        md = await self._find(tenant_id, provider_name)
        if md is None:
            return False
        if not enabled:
            return await self._backend().revoke(tenant_id, md.ref)
        return True

    async def rotate_key(
        self,
        tenant_id: str,
        provider_name: str,
        new_api_key: str,
        endpoint: Optional[str] = None,
    ) -> Optional[StoredKey]:
        """Rotate a BYOK key — re-encrypts under the new key value.

        The new key replaces the existing one (the original is not recoverable).
        Note: BYOK rotation does NOT change any lake/graph/training rights.
        """
        md = await self._find(tenant_id, provider_name)
        if md is None:
            return None
        aux = self._byok_aux(md)
        if endpoint is not None:
            aux["endpoint"] = endpoint
        aux.setdefault("provider_name", provider_name)
        ref = md.ref
        cred = ApiKeyCredential(api_key=new_api_key)
        # Re-encrypt under the new value and refresh endpoint metadata.
        await self._backend().create(tenant_id, ref, cred, metadata={"byok": aux})
        self._mask_cache[(tenant_id, provider_name)] = self._compute_mask(new_api_key)
        logger.info(f"BYOK key rotated: tenant={tenant_id} provider={provider_name}")
        refreshed = await self._backend().metadata(tenant_id, ref)
        return self._to_stored_key(tenant_id, refreshed) if refreshed else None

    async def revoke_key(self, tenant_id: str, provider_name: str) -> bool:
        """Revoke (disable) a BYOK key without deleting the record.

        Retained for audit; ``get_key`` returns None afterwards. Use
        ``delete_key`` to fully purge.
        """
        md = await self._find(tenant_id, provider_name)
        if md is None:
            return False
        ok = await self._backend().revoke(tenant_id, md.ref)
        if ok:
            logger.info(f"BYOK key revoked: tenant={tenant_id} provider={provider_name}")
        return ok

    async def verify_key(self, tenant_id: str, provider_name: str) -> dict:
        """Verify the BYOK key is stored and active without exposing the key."""
        md = await self._find(tenant_id, provider_name)
        if md is None:
            return {"exists": False, "active": False, "provider_name": provider_name}
        aux = self._byok_aux(md)
        return {
            "exists": True,
            "active": md.status != CredentialReadiness.DISABLED,
            "provider_name": provider_name,
            "category": aux.get("category", ""),
            "has_endpoint_override": bool(aux.get("endpoint")),
            "created_at": _iso(md.created_at),
            "updated_at": _iso(md.updated_at),
        }

    @staticmethod
    def _compute_mask(secret: str) -> str:
        suffix = hashlib.sha256(secret.encode()).hexdigest()[-4:]
        return f"****{suffix}"

    def masked_identifier(self, tenant_id: str, provider_name: str) -> str:
        """Masked representation for display (never the raw key). Best-effort.

        Synchronous: returns the value cached at store/rotate time, or ``"****"``
        when unknown to this instance.
        """
        return self._mask_cache.get((tenant_id, provider_name), "****")


__all__ = ["BYOKKeyVault", "StoredKey"]
