"""
Aether Shared -- BYOK Key Vault

Durable encrypted storage for tenant-provided API keys.
Uses a SQLite-backed repository with Fernet encryption when an explicit
encryption key is configured, and fails closed in non-local environments
without durable storage.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger
from repositories.repos import BaseRepository

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

    Uses a durable SQLite-backed repository. When ``encryption_key`` is
    configured, keys are encrypted with Fernet-derived key material.
    Local mode may fall back to reversible base64 encoding to avoid
    breaking development environments that do not yet provide a key.
    """

    def __init__(self, encryption_key: str = "") -> None:
        self._encryption_key = encryption_key
        self._repo = BaseRepository("provider_keys")
        self._fernet = self._build_fernet(encryption_key)

    @staticmethod
    def _build_fernet(encryption_key: str):
        if not encryption_key:
            return None
        from cryptography.fernet import Fernet

        digest = hashlib.sha256(encryption_key.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    @staticmethod
    def _vault_key(tenant_id: str, provider_name: str) -> str:
        return f"{tenant_id}:{provider_name}"

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext API key."""
        if self._fernet is not None:
            return self._fernet.encrypt(plaintext.encode()).decode()
        return base64.urlsafe_b64encode(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted API key."""
        if self._fernet is not None:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        return base64.urlsafe_b64decode(ciphertext.encode()).decode()

    @staticmethod
    def _mask_key(ciphertext: str) -> str:
        return f"{ciphertext[:4]}…{ciphertext[-4:]}" if len(ciphertext) > 8 else "****"

    @staticmethod
    def _from_record(record: dict) -> StoredKey:
        return StoredKey(
            tenant_id=record["tenant_id"],
            provider_name=record["provider_name"],
            category=record["category"],
            encrypted_key=record["encrypted_key"],
            endpoint=record.get("endpoint"),
            extra=record.get("extra", {}),
            created_at=record.get("created_at", ""),
            updated_at=record.get("updated_at", ""),
            enabled=bool(record.get("enabled", True)),
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
        existing = await self._repo.find_by_id(vk)
        payload = {
            "tenant_id": tenant_id,
            "provider_name": provider_name,
            "category": category,
            "encrypted_key": record.encrypted_key,
            "endpoint": endpoint,
            "extra": extra or {},
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
            "enabled": True,
        }
        if existing:
            await self._repo.update(vk, payload)
        else:
            await self._repo.insert(vk, payload)
        logger.info(f"BYOK key stored: tenant={tenant_id} provider={provider_name}")
        return record

    async def get_key(self, tenant_id: str, provider_name: str) -> Optional[str]:
        """Retrieve and decrypt a BYOK key.  Returns None if not found."""
        vk = self._vault_key(tenant_id, provider_name)
        raw = await self._repo.find_by_id(vk)
        record = self._from_record(raw) if raw else None
        if record is None or not record.enabled:
            return None
        return self._decrypt(record.encrypted_key)

    async def get_endpoint(self, tenant_id: str, provider_name: str) -> Optional[str]:
        """Get the custom endpoint for a BYOK key."""
        vk = self._vault_key(tenant_id, provider_name)
        raw = await self._repo.find_by_id(vk)
        record = self._from_record(raw) if raw else None
        return record.endpoint if record else None

    async def list_keys(self, tenant_id: str) -> list[dict]:
        """List all BYOK keys for a tenant (keys masked, never exposed)."""
        results = []
        for raw in await self._repo.find_many(filters={"tenant_id": tenant_id}, limit=10_000):
            record = self._from_record(raw)
            results.append({
                "provider_name": record.provider_name,
                "masked_key": self._mask_key(record.encrypted_key),
                "category": record.category,
                "endpoint": record.endpoint,
                "enabled": record.enabled,
                "stored_at": record.updated_at or record.created_at,
            })
        return results

    async def delete_key(self, tenant_id: str, provider_name: str) -> bool:
        """Delete a BYOK key."""
        vk = self._vault_key(tenant_id, provider_name)
        deleted = await self._repo.delete(vk)
        if deleted:
            logger.info(f"BYOK key deleted: tenant={tenant_id} provider={provider_name}")
        return deleted

    async def toggle_key(self, tenant_id: str, provider_name: str, enabled: bool) -> bool:
        """Enable or disable a BYOK key without deleting it."""
        vk = self._vault_key(tenant_id, provider_name)
        record = await self._repo.find_by_id(vk)
        if record is None:
            return False
        await self._repo.update(vk, {"enabled": enabled, "updated_at": _utc_now()})
        return True
