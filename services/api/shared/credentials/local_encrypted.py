"""Fernet-encrypted, durable credential backend backed by ``tenant_credentials``.

Serializes the :data:`StructuredCredential` to JSON (secrets revealed only for
the encrypt seam), Fernet-encrypts it, and persists the ciphertext + masked,
secret-free metadata through :class:`CredentialStore`. Versioned on rotate.

Encryption rules (reused from ``shared/providers/key_vault.py``, not imported):
- ``BYOK_ENCRYPTION_KEY`` (Fernet) is the active key.
- ``BYOK_ENCRYPTION_KEY_PREVIOUS`` decrypts during a rotation window.
- base64 fallback is permitted ONLY when ``AETHER_ENV`` is ``local``.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from typing import Any, Optional

from shared.credentials.interface import (
    STATUS_ACTIVE,
    STATUS_REVOKED,
    CredentialBackend,
    CredentialBackendError,
    CredentialBackendHealth,
    CredentialMetadata,
    make_metadata,
)
from shared.credentials.store import CredentialStore
from shared.credentials.types import (
    StructuredCredential,
    as_structured,
    from_plaintext_json,
    masked_identifier,
    masked_metadata,
    to_plaintext_json,
)
from shared.logger.logger import get_logger

logger = get_logger("aether.credentials.local_encrypted")

try:
    from cryptography.fernet import Fernet, InvalidToken

    FERNET_AVAILABLE = True
except ImportError:  # pragma: no cover - cryptography is a hard prod dependency
    Fernet = None  # type: ignore[misc, assignment]
    InvalidToken = Exception  # type: ignore[misc, assignment]
    FERNET_AVAILABLE = False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LocalEncryptedCredentialBackend(CredentialBackend):
    """Durable, Fernet-encrypted credential backend."""

    def __init__(
        self,
        store: Optional[CredentialStore] = None,
        encryption_key: str = "",
        encryption_key_previous: str = "",
    ) -> None:
        self._store = store if store is not None else CredentialStore()
        self._encryption_key = encryption_key or os.getenv("BYOK_ENCRYPTION_KEY", "")
        self._fernet: Optional[Any] = None
        self._fernet_previous: Optional[Any] = None

        if self._encryption_key and FERNET_AVAILABLE:
            try:
                self._fernet = Fernet(self._encryption_key.encode())
            except Exception as exc:
                if not _is_local_env():
                    raise CredentialBackendError(
                        f"Invalid BYOK_ENCRYPTION_KEY: {exc}"
                    ) from exc
                logger.warning("Invalid encryption key, falling back to base64 (LOCAL only)")
        elif not _is_local_env():
            if not FERNET_AVAILABLE:
                raise CredentialBackendError(
                    "cryptography package required for non-local environments"
                )
            raise CredentialBackendError(
                "BYOK_ENCRYPTION_KEY not set — required in non-local environments"
            )
        else:
            logger.warning("credential backend using base64 encoding (LOCAL mode only)")

        prev_key = encryption_key_previous or os.getenv("BYOK_ENCRYPTION_KEY_PREVIOUS", "")
        if prev_key and FERNET_AVAILABLE:
            try:
                self._fernet_previous = Fernet(prev_key.encode())
            except Exception as exc:
                logger.warning(f"Invalid BYOK_ENCRYPTION_KEY_PREVIOUS, ignoring: {exc}")

    # ── encryption seam ────────────────────────────────────────────────────
    def _encrypt(self, plaintext: str) -> str:
        if self._fernet:
            return self._fernet.encrypt(plaintext.encode()).decode()
        return base64.urlsafe_b64encode(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        if self._fernet:
            try:
                return self._fernet.decrypt(ciphertext.encode()).decode()
            except InvalidToken:
                if self._fernet_previous:
                    try:
                        return self._fernet_previous.decrypt(ciphertext.encode()).decode()
                    except InvalidToken:
                        pass
                raise CredentialBackendError(
                    "Failed to decrypt credential — set BYOK_ENCRYPTION_KEY_PREVIOUS "
                    "to the previous key or re-encrypt"
                )
        return base64.urlsafe_b64decode(ciphertext.encode()).decode()

    # ── interface ──────────────────────────────────────────────────────────
    async def create(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CredentialMetadata:
        cred = as_structured(credential)
        ciphertext = self._encrypt(to_plaintext_json(cred))
        extra = dict(metadata or {})
        display = {**extra, **masked_metadata(cred)}
        now = _utc_now()
        await self._store.upsert(
            tenant_id,
            ref,
            credential_type=cred.type,
            ciphertext=ciphertext,
            masked_metadata={**display, "_extra": extra},
            version=1,
            status=STATUS_ACTIVE,
            expires_at=cred.expires_at,
            created_at=now,
            updated_at=now,
            rotated_at=None,
            revoked_at=None,
        )
        logger.info(
            "credential stored tenant=%s ref=%s type=%s id=%s",
            tenant_id,
            ref,
            cred.type,
            masked_identifier(cred),
        )
        return (await self.metadata(tenant_id, ref))  # type: ignore[return-value]

    async def get(self, tenant_id: str, ref: str) -> Optional[StructuredCredential]:
        row = await self._store.get(tenant_id, ref)
        if row is None or row["status"] == STATUS_REVOKED:
            return None
        return from_plaintext_json(self._decrypt(row["ciphertext"]))

    async def rotate(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
    ) -> CredentialMetadata:
        existing = await self._store.get(tenant_id, ref)
        if existing is None:
            return await self.create(tenant_id, ref, credential)
        cred = as_structured(credential)
        ciphertext = self._encrypt(to_plaintext_json(cred))
        extra = dict(existing.get("masked_metadata", {}).get("_extra", {}))
        display = {**extra, **masked_metadata(cred)}
        now = _utc_now()
        await self._store.upsert(
            tenant_id,
            ref,
            credential_type=cred.type,
            ciphertext=ciphertext,
            masked_metadata={**display, "_extra": extra},
            version=int(existing["version"]) + 1,
            status=STATUS_ACTIVE,
            expires_at=cred.expires_at,
            created_at=existing["created_at"],
            updated_at=now,
            rotated_at=now,
            revoked_at=None,
        )
        logger.info(
            "credential rotated tenant=%s ref=%s type=%s id=%s",
            tenant_id,
            ref,
            cred.type,
            masked_identifier(cred),
        )
        return (await self.metadata(tenant_id, ref))  # type: ignore[return-value]

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        ok = await self._store.set_status(
            tenant_id, ref, STATUS_REVOKED, revoked_at=_utc_now()
        )
        if ok:
            logger.info("credential revoked tenant=%s ref=%s", tenant_id, ref)
        return ok

    async def delete(self, tenant_id: str, ref: str) -> bool:
        ok = await self._store.delete(tenant_id, ref)
        if ok:
            logger.info("credential deleted tenant=%s ref=%s", tenant_id, ref)
        return ok

    async def metadata(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]:
        row = await self._store.get(tenant_id, ref)
        return self._metadata_from_row(row)

    async def list(self, tenant_id: str) -> list[CredentialMetadata]:
        rows = await self._store.list_for_tenant(tenant_id)
        out: list[CredentialMetadata] = []
        for row in rows:
            md = self._metadata_from_row(row)
            if md is not None:
                out.append(md)
        return out

    async def health_check(self) -> CredentialBackendHealth:
        try:
            durable = await self._store.is_durable()
        except Exception as exc:  # pragma: no cover - defensive
            return CredentialBackendHealth(
                backend="local_encrypted", durable=False, healthy=False, detail=str(exc)
            )
        return CredentialBackendHealth(
            backend="local_encrypted",
            durable=durable,
            healthy=True,
            detail="postgres-backed" if durable else "local process-store fallback",
        )

    @staticmethod
    def reset(tenant_id: Optional[str] = None) -> None:
        """Test-only: clear the process-local fallback store."""
        CredentialStore.reset(tenant_id)

    def _metadata_from_row(self, row: Optional[dict[str, Any]]) -> Optional[CredentialMetadata]:
        if row is None:
            return None
        display = dict(row.get("masked_metadata", {}))
        extra = dict(display.pop("_extra", {}))
        merged = {**extra, **display}
        return make_metadata(
            tenant_id=row["tenant_id"],
            ref=row["credential_ref"],
            credential_type=row["credential_type"],
            version=int(row["version"]),
            lifecycle_status=row["status"],
            masked_identifier=str(merged.get("masked_identifier", "****")),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            rotated_at=row.get("rotated_at"),
            revoked_at=row.get("revoked_at"),
            expires_at=row.get("expires_at"),
            extra=merged,
        )


__all__ = ["LocalEncryptedCredentialBackend"]
