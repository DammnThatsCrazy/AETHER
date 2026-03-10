"""
Aether Shared -- BYOK Key Vault

Encrypted storage for tenant-provided API keys.
Uses Fernet symmetric encryption (AES-128-CBC).
Stub uses in-memory dict; production swaps to DynamoDB + KMS.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.providers.key_vault")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    Stub uses in-memory dict + base64 encoding.
    Production: DynamoDB table + AWS KMS (Fernet wrapper).
    """

    def __init__(self, encryption_key: str = "") -> None:
        self._encryption_key = encryption_key
        # "{tenant_id}:{provider_name}" -> StoredKey
        self._store: dict[str, StoredKey] = {}

    @staticmethod
    def _vault_key(tenant_id: str, provider_name: str) -> str:
        return f"{tenant_id}:{provider_name}"

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext API key.  Stub: base64.  Production: Fernet."""
        if self._encryption_key:
            # Production: Fernet(self._encryption_key).encrypt(plaintext.encode()).decode()
            pass
        return base64.urlsafe_b64encode(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted API key."""
        if self._encryption_key:
            # Production: Fernet(self._encryption_key).decrypt(ciphertext.encode()).decode()
            pass
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
        """Retrieve and decrypt a BYOK key.  Returns None if not found."""
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
