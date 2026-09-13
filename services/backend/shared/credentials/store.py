"""Raw-SQL persistence for the ``tenant_credentials`` table.

This is a deliberate exception to the JSONB ``BaseRepository`` pattern: tenant
credentials are a dedicated non-JSONB row store (ciphertext + masked metadata +
versioning + lifecycle columns), created by the
``20260812_credential_platform`` migration.

The connection pool is reused from ``repositories.repos.get_pool`` — the same
asyncpg pool the rest of the backend uses. When no pool is available (local/dev
with ``AETHER_ENV=local`` and no ``DATABASE_URL``), the store falls back to a
process-local dict that persists across ``CredentialStore`` instances, so the
durable-roundtrip contract (write with one instance, read with a fresh one)
holds without a live database. The production path still targets
``tenant_credentials``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.credentials.store")

_TABLE = "tenant_credentials"

# Process-local durable fallback keyed by (tenant_id, credential_ref). Shared
# across instances so a "simulated restart" (new CredentialStore) still reads
# prior writes when there is no Postgres pool.
_LOCAL_ROWS: dict[tuple[str, str], dict[str, Any]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CredentialStore:
    """Row-level access to ``tenant_credentials`` (raw SQL, non-JSONB)."""

    def __init__(self, rows: Optional[dict[tuple[str, str], dict[str, Any]]] = None) -> None:
        # ``rows`` is an injection seam for tests; default is the shared dict.
        self._rows = rows if rows is not None else _LOCAL_ROWS
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @staticmethod
    def reset(tenant_id: Optional[str] = None) -> None:
        """Test-only: clear the process-local fallback rows."""
        if tenant_id is None:
            _LOCAL_ROWS.clear()
            return
        for key in [k for k in _LOCAL_ROWS if k[0] == tenant_id]:
            del _LOCAL_ROWS[key]

    async def _ensure_pool(self) -> Optional[Any]:
        if self._pool is None:
            from repositories.repos import get_pool

            self._pool = await get_pool()
        return self._pool

    async def _ensure_table(self, pool: Any) -> None:
        # The migration owns the canonical schema; this is a safety net for
        # environments that boot before migrations run.
        if self._table_ensured:
            return
        await pool.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                credential_ref TEXT NOT NULL,
                credential_type TEXT NOT NULL,
                ciphertext TEXT NOT NULL,
                masked_metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                version INT NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                rotated_at TIMESTAMPTZ,
                revoked_at TIMESTAMPTZ
            )
            """
        )
        await pool.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{_TABLE}_ref "
            f"ON {_TABLE} (tenant_id, credential_ref)"
        )
        self._table_ensured = True

    @staticmethod
    def _row_id(tenant_id: str, credential_ref: str) -> str:
        return f"{tenant_id}:{credential_ref}"

    async def upsert(
        self,
        tenant_id: str,
        credential_ref: str,
        *,
        credential_type: str,
        ciphertext: str,
        masked_metadata: dict[str, Any],
        version: int,
        status: str,
        expires_at: Optional[datetime],
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        rotated_at: Optional[datetime] = None,
        revoked_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        row = {
            "id": self._row_id(tenant_id, credential_ref),
            "tenant_id": tenant_id,
            "credential_ref": credential_ref,
            "credential_type": credential_type,
            "ciphertext": ciphertext,
            "masked_metadata": dict(masked_metadata),
            "version": version,
            "status": status,
            "expires_at": expires_at,
            "created_at": created_at or now,
            "updated_at": updated_at or now,
            "rotated_at": rotated_at,
            "revoked_at": revoked_at,
        }
        pool = await self._ensure_pool()
        if pool is None:
            self._rows[(tenant_id, credential_ref)] = row
            return row
        await self._ensure_table(pool)
        await pool.execute(
            f"""
            INSERT INTO {_TABLE} (
                id, tenant_id, credential_ref, credential_type, ciphertext,
                masked_metadata, version, status, expires_at,
                created_at, updated_at, rotated_at, revoked_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $12, $13
            )
            ON CONFLICT (id) DO UPDATE SET
                credential_type = EXCLUDED.credential_type,
                ciphertext = EXCLUDED.ciphertext,
                masked_metadata = EXCLUDED.masked_metadata,
                version = EXCLUDED.version,
                status = EXCLUDED.status,
                expires_at = EXCLUDED.expires_at,
                updated_at = EXCLUDED.updated_at,
                rotated_at = EXCLUDED.rotated_at,
                revoked_at = EXCLUDED.revoked_at
            """,
            row["id"],
            tenant_id,
            credential_ref,
            credential_type,
            ciphertext,
            json.dumps(row["masked_metadata"], default=str),
            version,
            status,
            expires_at,
            row["created_at"],
            row["updated_at"],
            rotated_at,
            revoked_at,
        )
        return row

    async def get(self, tenant_id: str, credential_ref: str) -> Optional[dict[str, Any]]:
        pool = await self._ensure_pool()
        if pool is None:
            row = self._rows.get((tenant_id, credential_ref))
            return dict(row) if row is not None else None
        await self._ensure_table(pool)
        record = await pool.fetchrow(
            f"SELECT * FROM {_TABLE} WHERE tenant_id = $1 AND credential_ref = $2",
            tenant_id,
            credential_ref,
        )
        return self._from_db_row(record)

    async def set_status(
        self,
        tenant_id: str,
        credential_ref: str,
        status: str,
        *,
        revoked_at: Optional[datetime] = None,
    ) -> bool:
        pool = await self._ensure_pool()
        now = _utc_now()
        if pool is None:
            row = self._rows.get((tenant_id, credential_ref))
            if row is None:
                return False
            row["status"] = status
            row["updated_at"] = now
            if revoked_at is not None:
                row["revoked_at"] = revoked_at
            return True
        await self._ensure_table(pool)
        result = await pool.execute(
            f"""
            UPDATE {_TABLE}
            SET status = $3, updated_at = $4, revoked_at = COALESCE($5, revoked_at)
            WHERE tenant_id = $1 AND credential_ref = $2
            """,
            tenant_id,
            credential_ref,
            status,
            now,
            revoked_at,
        )
        return result.endswith("1")

    async def bump_version(self, tenant_id: str, credential_ref: str) -> Optional[int]:
        pool = await self._ensure_pool()
        now = _utc_now()
        if pool is None:
            row = self._rows.get((tenant_id, credential_ref))
            if row is None:
                return None
            row["version"] += 1
            row["rotated_at"] = now
            row["updated_at"] = now
            return int(row["version"])
        await self._ensure_table(pool)
        record = await pool.fetchrow(
            f"""
            UPDATE {_TABLE}
            SET version = version + 1, rotated_at = $3, updated_at = $3
            WHERE tenant_id = $1 AND credential_ref = $2
            RETURNING version
            """,
            tenant_id,
            credential_ref,
            now,
        )
        return int(record["version"]) if record is not None else None

    async def delete(self, tenant_id: str, credential_ref: str) -> bool:
        pool = await self._ensure_pool()
        if pool is None:
            return self._rows.pop((tenant_id, credential_ref), None) is not None
        await self._ensure_table(pool)
        result = await pool.execute(
            f"DELETE FROM {_TABLE} WHERE tenant_id = $1 AND credential_ref = $2",
            tenant_id,
            credential_ref,
        )
        return result.endswith("1")

    async def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        if pool is None:
            return [dict(r) for (t, _), r in self._rows.items() if t == tenant_id]
        await self._ensure_table(pool)
        records = await pool.fetch(
            f"SELECT * FROM {_TABLE} WHERE tenant_id = $1 ORDER BY created_at",
            tenant_id,
        )
        return [self._from_db_row(r) for r in records if r is not None]  # type: ignore[misc]

    @staticmethod
    def _from_db_row(record: Any) -> Optional[dict[str, Any]]:
        if record is None:
            return None
        row = dict(record)
        meta = row.get("masked_metadata")
        if isinstance(meta, str):
            row["masked_metadata"] = json.loads(meta) if meta else {}
        elif meta is None:
            row["masked_metadata"] = {}
        return row

    async def is_durable(self) -> bool:
        return await self._ensure_pool() is not None


__all__ = ["CredentialStore"]
