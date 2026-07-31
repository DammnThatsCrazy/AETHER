"""In-memory credential backend — TEST authority only.

Process-local dict store. NOT durable and NOT for production use; the factory
only returns this when ``AETHER_CREDENTIAL_BACKEND=in_memory`` (the default
under the backend test suite).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.credentials.interface import (
    STATUS_ACTIVE,
    STATUS_REVOKED,
    CredentialBackend,
    CredentialBackendHealth,
    CredentialMetadata,
    make_metadata,
)
from shared.credentials.types import (
    StructuredCredential,
    as_structured,
    masked_identifier,
    masked_metadata,
)

# Shared across every instance so a freshly-constructed backend observes prior
# writes (mirrors how the real backends are process/DB-durable).
_STORE: dict[tuple[str, str], dict[str, Any]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryCredentialBackend(CredentialBackend):
    """Dict-backed credential store for tests."""

    def __init__(self, store: Optional[dict[tuple[str, str], dict[str, Any]]] = None) -> None:
        self._store = store if store is not None else _STORE

    @staticmethod
    def reset(tenant_id: Optional[str] = None) -> None:
        """Test-only: drop all records (or just one tenant's)."""
        if tenant_id is None:
            _STORE.clear()
            return
        for key in [k for k in _STORE if k[0] == tenant_id]:
            del _STORE[key]

    async def create(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CredentialMetadata:
        cred = as_structured(credential)
        now = _utc_now()
        self._store[(tenant_id, ref)] = {
            "credential": cred,
            "version": 1,
            "status": STATUS_ACTIVE,
            "created_at": now,
            "updated_at": now,
            "rotated_at": None,
            "revoked_at": None,
            "extra": dict(metadata or {}),
        }
        return self._metadata_for(tenant_id, ref)  # type: ignore[return-value]

    async def get(self, tenant_id: str, ref: str) -> Optional[StructuredCredential]:
        record = self._store.get((tenant_id, ref))
        if record is None or record["status"] == STATUS_REVOKED:
            return None
        return record["credential"]

    async def rotate(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
    ) -> CredentialMetadata:
        record = self._store.get((tenant_id, ref))
        if record is None:
            return await self.create(tenant_id, ref, credential)
        now = _utc_now()
        record["credential"] = as_structured(credential)
        record["version"] += 1
        record["status"] = STATUS_ACTIVE
        record["revoked_at"] = None
        record["updated_at"] = now
        record["rotated_at"] = now
        return self._metadata_for(tenant_id, ref)  # type: ignore[return-value]

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        record = self._store.get((tenant_id, ref))
        if record is None:
            return False
        record["status"] = STATUS_REVOKED
        record["revoked_at"] = _utc_now()
        record["updated_at"] = record["revoked_at"]
        return True

    async def delete(self, tenant_id: str, ref: str) -> bool:
        return self._store.pop((tenant_id, ref), None) is not None

    async def metadata(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]:
        return self._metadata_for(tenant_id, ref)

    async def list(self, tenant_id: str) -> list[CredentialMetadata]:
        out: list[CredentialMetadata] = []
        for (tid, ref) in list(self._store):
            if tid == tenant_id:
                md = self._metadata_for(tid, ref)
                if md is not None:
                    out.append(md)
        return out

    async def health_check(self) -> CredentialBackendHealth:
        return CredentialBackendHealth(
            backend="in_memory",
            durable=False,
            healthy=True,
            detail="process-local dict store (test authority only)",
        )

    def _metadata_for(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]:
        record = self._store.get((tenant_id, ref))
        if record is None:
            return None
        cred: StructuredCredential = record["credential"]
        extra = dict(record["extra"])
        extra.update(masked_metadata(cred))
        return make_metadata(
            tenant_id=tenant_id,
            ref=ref,
            credential_type=cred.type,
            version=record["version"],
            lifecycle_status=record["status"],
            masked_identifier=masked_identifier(cred),
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            rotated_at=record["rotated_at"],
            revoked_at=record["revoked_at"],
            expires_at=cred.expires_at,
            extra=extra,
        )


__all__ = ["InMemoryCredentialBackend"]
