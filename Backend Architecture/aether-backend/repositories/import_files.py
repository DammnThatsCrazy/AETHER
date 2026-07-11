"""
Aether Repository — Import Files

Durable, tenant-scoped storage for the raw bytes a tenant uploads to the Import
Engine (the content, a sha256 checksum, size, and MIME). Direct-SQL repository
over the ``import_files`` table created by
``alembic/versions/20260718_import_engine.py`` — BYTEA content is inexpressible
through the JSONB BaseRepository API, so this repo owns its own SQL with an
in-memory fallback that mirrors the same semantics in local mode.

Storage ruling (mirrors ``repositories/artifacts.py``): Postgres BYTEA is the
only shared durable medium in the stack today (no object store exists; ECS
tasks have no shared filesystem). The byte I/O is kept behind small private
methods so an S3-backed ``ImportStorageAdapter`` can replace it without
touching callers.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import BadRequestError, NotFoundError

# Hard ceiling for a single uploaded file held in a BYTEA row. Plan tiers may
# impose a lower cap at the route layer; this is the absolute maximum.
MAX_IMPORT_FILE_BYTES = 32 * 1024 * 1024

# Must stay string-identical to IMPORT_FILES_DDL in
# alembic/versions/20260718_import_engine.py (parity-tested).
IMPORT_FILES_DDL = """
CREATE TABLE IF NOT EXISTS import_files (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    import_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    content BYTEA,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_import_files_tenant_import
    ON import_files (tenant_id, import_id);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ImportFileRepository:
    """Tenant-scoped import-file byte store (Postgres BYTEA / in-memory local)."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False
        # Local fallback: id -> row dict (content held as bytes).
        self._store: dict[str, dict] = {}

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(IMPORT_FILES_DDL)
            self._table_ensured = True
        return self._pool

    # ── writes ────────────────────────────────────────────────────────────

    async def put(
        self,
        tenant_id: str,
        *,
        import_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict:
        if not tenant_id:
            raise BadRequestError("tenant_id is required")
        if not import_id:
            raise BadRequestError("import_id is required")
        if len(content) > MAX_IMPORT_FILE_BYTES:
            raise BadRequestError(
                f"file exceeds {MAX_IMPORT_FILE_BYTES} byte cap "
                f"({len(content)} bytes) — split the file or narrow the export"
            )
        file_id = f"impf_{uuid.uuid4().hex}"
        sha256 = hashlib.sha256(content).hexdigest()
        row = {
            "id": file_id,
            "tenant_id": tenant_id,
            "import_id": import_id,
            "filename": filename,
            "content_type": content_type,
            "sha256": sha256,
            "size_bytes": len(content),
            "status": "stored",
            "created_at": _now().isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            self._store[file_id] = {**row, "content": content}
        else:
            await pool.execute(
                """
                INSERT INTO import_files
                    (id, tenant_id, import_id, filename, content, content_type,
                     sha256, size_bytes, status)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'stored')
                """,
                file_id,
                tenant_id,
                import_id,
                filename,
                content,
                content_type,
                sha256,
                len(content),
            )
        return {k: v for k, v in row.items()}

    # ── reads ────────────────────────────────────────────────────────────

    def _meta_from(self, row: dict) -> dict:
        meta = {k: v for k, v in dict(row).items() if k != "content"}
        for key in ("created_at", "updated_at"):
            if isinstance(meta.get(key), datetime):
                meta[key] = meta[key].isoformat()
        return meta

    async def get_meta(self, tenant_id: str, file_id: str) -> dict:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(file_id)
            if row is None or row.get("tenant_id") != tenant_id:
                raise NotFoundError("import file")
            return self._meta_from(row)
        record = await pool.fetchrow(
            "SELECT id, tenant_id, import_id, filename, content_type, sha256, "
            "size_bytes, status, created_at FROM import_files "
            "WHERE tenant_id = $1 AND id = $2",
            tenant_id,
            file_id,
        )
        if record is None:
            raise NotFoundError("import file")
        return self._meta_from(dict(record))

    async def get_content(self, tenant_id: str, file_id: str) -> tuple[dict, bytes]:
        """Return (meta, bytes); raises NotFoundError when absent/cross-tenant."""
        meta = await self.get_meta(tenant_id, file_id)
        pool = await self._ensure()
        if pool is None:
            content = self._store[file_id].get("content")
        else:
            record = await pool.fetchrow(
                "SELECT content FROM import_files WHERE tenant_id = $1 AND id = $2",
                tenant_id,
                file_id,
            )
            content = record["content"] if record else None
        if content is None:
            raise NotFoundError("import file content")
        return meta, bytes(content)

    async def list_for_import(self, tenant_id: str, import_id: str) -> list[dict]:
        pool = await self._ensure()
        if pool is None:
            rows = [
                self._meta_from(r)
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id and r.get("import_id") == import_id
            ]
            rows.sort(key=lambda r: r.get("created_at") or "")
            return rows
        records = await pool.fetch(
            "SELECT id, tenant_id, import_id, filename, content_type, sha256, "
            "size_bytes, status, created_at FROM import_files "
            "WHERE tenant_id = $1 AND import_id = $2 ORDER BY created_at ASC",
            tenant_id,
            import_id,
        )
        return [self._meta_from(dict(r)) for r in records]

    async def verify(self, tenant_id: str, file_id: str) -> bool:
        """Recompute the checksum of stored bytes against the recorded sha256."""
        meta, content = await self.get_content(tenant_id, file_id)
        return hashlib.sha256(content).hexdigest() == meta["sha256"]


_repo: Optional[ImportFileRepository] = None


def get_import_file_repository() -> ImportFileRepository:
    global _repo
    if _repo is None:
        _repo = ImportFileRepository()
    return _repo
