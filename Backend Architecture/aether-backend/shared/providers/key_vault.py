"""
Aether Shared -- BYOK Key Vault

Encrypted storage for tenant-provided API keys.
Uses Fernet symmetric encryption (AES-128-CBC via cryptography library).

In-memory store for local dev; production should persist to DynamoDB/Redis.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.providers.key_vault")

# Optional Fernet import — falls back to base64 only in LOCAL mode
try:
    from cryptography.fernet import Fernet, InvalidToken
    FERNET_AVAILABLE = True
except ImportError:
    Fernet = None  # type: ignore[misc, assignment]
    InvalidToken = Exception  # type: ignore[misc, assignment]
    FERNET_AVAILABLE = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


@dataclass
class StoredKey:
    """A single encrypted BYOK key record."""

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
    """
    Manages BYOK API keys with encryption at rest.

    Encryption:
    - Production: Fernet symmetric encryption (AES-128-CBC).
      Set BYOK_ENCRYPTION_KEY env var to a Fernet key
      (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    - Local dev: Falls back to base64 if cryptography not installed or key not set.
    """

    def __init__(self, encryption_key: str = "", encryption_key_previous: str = "") -> None:
        self._encryption_key = encryption_key or os.getenv("BYOK_ENCRYPTION_KEY", "")
        self._fernet: Optional[Any] = None
        self._fernet_previous: Optional[Any] = None

        if self._encryption_key and FERNET_AVAILABLE:
            try:
                self._fernet = Fernet(self._encryption_key.encode())
                logger.info("BYOK vault initialized with Fernet encryption")
            except Exception as e:
                if not _is_local_env():
                    raise RuntimeError(
                        f"Invalid BYOK_ENCRYPTION_KEY: {e}. "
                        "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                    )
                logger.warning(f"Invalid encryption key, falling back to base64: {e}")
        elif not _is_local_env():
            if not FERNET_AVAILABLE:
                raise RuntimeError(
                    "cryptography package required for production. "
                    "Install with: pip install cryptography>=42.0"
                )
            raise RuntimeError(
                "BYOK_ENCRYPTION_KEY not set. Required in non-local environments. "
                "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        else:
            logger.warning("BYOK vault using base64 encoding (LOCAL mode only)")

        prev_key = encryption_key_previous or os.getenv("BYOK_ENCRYPTION_KEY_PREVIOUS", "")
        if prev_key and FERNET_AVAILABLE:
            try:
                self._fernet_previous = Fernet(prev_key.encode())
                logger.info("BYOK vault: previous encryption key loaded for rotation window")
            except Exception as e:
                logger.warning(f"Invalid BYOK_ENCRYPTION_KEY_PREVIOUS, ignoring: {e}")

        # In-memory store — production should swap to DynamoDB/Redis
        self._store: dict[str, StoredKey] = {}

    @staticmethod
    def _vault_key(tenant_id: str, provider_name: str) -> str:
        return f"{tenant_id}:{provider_name}"

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext API key."""
        if self._fernet:
            return self._fernet.encrypt(plaintext.encode()).decode()
        # Local-only fallback: base64 (NOT secure)
        return base64.urlsafe_b64encode(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted API key, falling back to previous key during rotation."""
        if self._fernet:
            try:
                return self._fernet.decrypt(ciphertext.encode()).decode()
            except InvalidToken:
                if self._fernet_previous:
                    try:
                        return self._fernet_previous.decrypt(ciphertext.encode()).decode()
                    except InvalidToken:
                        pass
                raise ValueError(
                    "Failed to decrypt BYOK key — run scripts/byok_reencrypt.py "
                    "or set BYOK_ENCRYPTION_KEY_PREVIOUS to the previous key"
                )
        # Local-only fallback
        return base64.urlsafe_b64decode(ciphertext.encode()).decode()

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
        vk = self._vault_key(tenant_id, provider_name)
        now = _utc_now()

        record = StoredKey(
            tenant_id=tenant_id,
            provider_name=provider_name,
            category=category,
            encrypted_key=self._encrypt(api_key),
            endpoint=endpoint,
            extra=extra or {},
            created_at=now,
            updated_at=now,
        )
        self._store[vk] = record
        logger.info(f"BYOK key stored: tenant={tenant_id} provider={provider_name}")
        return record

    async def get_key(self, tenant_id: str, provider_name: str) -> Optional[str]:
        """Retrieve and decrypt a BYOK key. Returns None if not found."""
        vk = self._vault_key(tenant_id, provider_name)
        record = self._store.get(vk)
        if record is None or not record.enabled:
            return None
        return self._decrypt(record.encrypted_key)

    async def get_endpoint(self, tenant_id: str, provider_name: str) -> Optional[str]:
        """Get the custom endpoint for a BYOK key."""
        vk = self._vault_key(tenant_id, provider_name)
        record = self._store.get(vk)
        return record.endpoint if record else None

    async def list_keys(self, tenant_id: str) -> list[dict]:
        """List all BYOK keys for a tenant (keys masked, never exposed)."""
        results = []
        for record in self._store.values():
            if record.tenant_id == tenant_id:
                results.append({
                    "provider_name": record.provider_name,
                    "category": record.category,
                    "endpoint": record.endpoint,
                    "enabled": record.enabled,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "has_key": True,
                })
        return results

    async def delete_key(self, tenant_id: str, provider_name: str) -> bool:
        """Delete a BYOK key."""
        vk = self._vault_key(tenant_id, provider_name)
        if vk in self._store:
            del self._store[vk]
            logger.info(f"BYOK key deleted: tenant={tenant_id} provider={provider_name}")
            return True
        return False

    async def toggle_key(self, tenant_id: str, provider_name: str, enabled: bool) -> bool:
        """Enable or disable a BYOK key without deleting it."""
        vk = self._vault_key(tenant_id, provider_name)
        record = self._store.get(vk)
        if record:
            record.enabled = enabled
            record.updated_at = _utc_now()
            return True
        return False

    async def rotate_key(
        self,
        tenant_id: str,
        provider_name: str,
        new_api_key: str,
        endpoint: Optional[str] = None,
    ) -> Optional[StoredKey]:
        """Rotate a BYOK key — re-encrypts under the new key value.

        The new key replaces the existing encrypted_key. The original key
        is NOT recoverable after rotation. Increments updated_at.
        Note: BYOK rotation does NOT change any lake/graph/training rights.
        Those require a separate DataRightsGrant update.
        """
        vk = self._vault_key(tenant_id, provider_name)
        record = self._store.get(vk)
        if not record:
            return None

        record.encrypted_key = self._encrypt(new_api_key)
        record.updated_at = _utc_now()
        if endpoint is not None:
            record.endpoint = endpoint

        logger.info(f"BYOK key rotated: tenant={tenant_id} provider={provider_name}")
        return record

    async def revoke_key(self, tenant_id: str, provider_name: str) -> bool:
        """Revoke (disable) a BYOK key without deleting the record.

        The key is retained for audit purposes but will not be returned by get_key().
        Use delete_key() to fully purge.
        """
        vk = self._vault_key(tenant_id, provider_name)
        record = self._store.get(vk)
        if not record:
            return False

        record.enabled = False
        record.updated_at = _utc_now()
        logger.info(f"BYOK key revoked: tenant={tenant_id} provider={provider_name}")
        return True

    async def verify_key(self, tenant_id: str, provider_name: str) -> dict:
        """Verify the BYOK key is stored and active without exposing the key.

        Returns safe metadata only — never the actual key value.
        Liveness testing (calling the provider) is a separate operation.
        """
        vk = self._vault_key(tenant_id, provider_name)
        record = self._store.get(vk)

        if not record:
            return {"exists": False, "active": False, "provider_name": provider_name}

        return {
            "exists": True,
            "active": record.enabled,
            "provider_name": record.provider_name,
            "category": record.category,
            "has_endpoint_override": bool(record.endpoint),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def masked_identifier(self, tenant_id: str, provider_name: str) -> str:
        """Return a masked representation of the key for display (never the raw key).

        Format: "****<last4>" where last4 comes from a stable hash of the encrypted key.
        This avoids exposing any key bytes while still being stable across calls.
        """
        vk = self._vault_key(tenant_id, provider_name)
        record = self._store.get(vk)
        if not record:
            return "****"

        import hashlib as _hashlib
        suffix = _hashlib.sha256(record.encrypted_key.encode()).hexdigest()[-4:]
        return f"****{suffix}"
