"""
Aether Repository — Export Artifacts

Durable, tenant-scoped storage for generated export artifacts (the bytes, a
sha256 checksum, and the export manifest). Direct-SQL repository over the
``export_artifacts`` table created by
``alembic/versions/20260713_platform_control_plane.py`` — BYTEA content is
inexpressible through the JSONB BaseRepository API, so this repo owns its own
SQL with an in-memory fallback that mirrors the same semantics in local mode.

Storage ruling (see docs/JOBS-PLATFORM.md when it lands): Postgres BYTEA is
the only shared durable medium in the stack today (no object store exists;
ECS tasks have no shared filesystem). The byte I/O is kept behind small
private methods so an S3-backed implementation can replace it without
touching callers.

Expiration is physical: ``expire_sweep`` NULLs the content of expired rows
and stamps ``deleted_at`` while keeping the row (id, sha256, manifest) as an
audit tombstone — an expired artifact is provably gone but still accounted
for.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import BadRequestError, NotFoundError

# Hard cap per artifact. Larger exports must stream/paginate at the exporter
# level; a 32 MB BYTEA row is the ceiling for what we let a single artifact
# occupy in Postgres.
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024

# Must stay string-identical to EXPORT_ARTIFACTS_DDL in
# alembic/versions/20260713_platform_control_plane.py (parity-tested).
EXPORT_ARTIFACTS_DDL = """
CREATE TABLE IF NOT EXISTS export_artifacts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT,
    export_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    content BYTEA,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


class ArtifactRepository:
    """Tenant-scoped export artifact store (Postgres BYTEA / in-memory local)."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False
        # Local fallback: id -> row dict (content held as bytes).
        self._store: dict[str, dict] = {}

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(EXPORT_ARTIFACTS_DDL)
            self._table_ensured = True
        return self._pool

    # ── writes ────────────────────────────────────────────────────────────

    async def put(
        self,
        tenant_id: str,
        *,
        export_type: str,
        filename: str,
        content: bytes,
        content_type: str,
        manifest: dict,
        job_id: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> dict:
        if not tenant_id:
            raise BadRequestError("tenant_id is required")
        if len(content) > MAX_ARTIFACT_BYTES:
            raise BadRequestError(
                f"artifact exceeds {MAX_ARTIFACT_BYTES} byte cap "
                f"({len(content)} bytes) — stream or narrow the export window"
            )
        artifact_id = f"art_{uuid.uuid4().hex}"
        sha256 = hashlib.sha256(content).hexdigest()
        row = {
            "id": artifact_id,
            "tenant_id": tenant_id,
            "job_id": job_id,
            "export_type": export_type,
            "filename": filename,
            "content_type": content_type,
            "sha256": sha256,
            "size_bytes": len(content),
            "manifest": manifest,
            "expires_at": expires_at,
            "deleted_at": None,
            "created_at": _now().isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            self._store[artifact_id] = {**row, "content": content}
        else:
            import json as _json

            await pool.execute(
                """
                INSERT INTO export_artifacts
                    (id, tenant_id, job_id, export_type, filename, content,
                     content_type, sha256, size_bytes, manifest, expires_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11)
                """,
                artifact_id,
                tenant_id,
                job_id,
                export_type,
                filename,
                content,
                content_type,
                sha256,
                len(content),
                _json.dumps(manifest, default=str),
                _parse_ts(expires_at),
            )
        return {k: v for k, v in row.items()}

    async def soft_delete(self, tenant_id: str, artifact_id: str) -> dict:
        meta = await self.get_meta(tenant_id, artifact_id)
        now = _now()
        pool = await self._ensure()
        if pool is None:
            row = self._store[artifact_id]
            row["deleted_at"] = now.isoformat()
            row["content"] = None
        else:
            await pool.execute(
                "UPDATE export_artifacts SET deleted_at = $3, content = NULL, "
                "updated_at = now() WHERE tenant_id = $1 AND id = $2",
                tenant_id,
                artifact_id,
            )
        meta["deleted_at"] = now.isoformat()
        return meta

    async def expire_sweep(self) -> dict:
        """Physically delete content of expired artifacts; keep tombstones."""
        now = _now()
        pool = await self._ensure()
        if pool is None:
            swept = 0
            for row in self._store.values():
                exp = _parse_ts(row.get("expires_at"))
                if exp and exp <= now and row.get("deleted_at") is None:
                    row["content"] = None
                    row["deleted_at"] = now.isoformat()
                    swept += 1
            return {"swept": swept}
        result = await pool.execute(
            "UPDATE export_artifacts SET content = NULL, deleted_at = now(), "
            "updated_at = now() WHERE expires_at IS NOT NULL "
            "AND expires_at <= now() AND deleted_at IS NULL"
        )
        # asyncpg returns e.g. "UPDATE 3"
        try:
            swept = int(str(result).split()[-1])
        except (ValueError, IndexError):
            swept = 0
        return {"swept": swept}

    # ── reads ────────────────────────────────────────────────────────────

    def _meta_from(self, row: dict) -> dict:
        meta = {k: v for k, v in dict(row).items() if k != "content"}
        for key in ("expires_at", "deleted_at", "created_at", "updated_at"):
            if isinstance(meta.get(key), datetime):
                meta[key] = meta[key].isoformat()
        if isinstance(meta.get("manifest"), str):
            import json as _json

            try:
                meta["manifest"] = _json.loads(meta["manifest"])
            except ValueError:
                pass
        return meta

    async def get_meta(self, tenant_id: str, artifact_id: str) -> dict:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(artifact_id)
            if row is None or row.get("tenant_id") != tenant_id:
                raise NotFoundError("export artifact")
            return self._meta_from(row)
        record = await pool.fetchrow(
            "SELECT id, tenant_id, job_id, export_type, filename, content_type, "
            "sha256, size_bytes, manifest, expires_at, deleted_at, created_at "
            "FROM export_artifacts WHERE tenant_id = $1 AND id = $2",
            tenant_id,
            artifact_id,
        )
        if record is None:
            raise NotFoundError("export artifact")
        return self._meta_from(dict(record))

    async def get_content(self, tenant_id: str, artifact_id: str) -> tuple[dict, bytes]:
        """Return (meta, bytes); refuses expired or deleted artifacts."""
        meta = await self.get_meta(tenant_id, artifact_id)
        if meta.get("deleted_at"):
            raise NotFoundError("export artifact (deleted)")
        exp = _parse_ts(meta.get("expires_at"))
        if exp and exp <= _now():
            raise NotFoundError("export artifact (expired)")
        pool = await self._ensure()
        if pool is None:
            content = self._store[artifact_id].get("content")
        else:
            record = await pool.fetchrow(
                "SELECT content FROM export_artifacts WHERE tenant_id = $1 AND id = $2",
                tenant_id,
                artifact_id,
            )
            content = record["content"] if record else None
        if content is None:
            raise NotFoundError("export artifact content")
        return meta, bytes(content)

    async def verify(self, tenant_id: str, artifact_id: str) -> bool:
        """Recompute the checksum of stored bytes against the recorded sha256."""
        meta, content = await self.get_content(tenant_id, artifact_id)
        return hashlib.sha256(content).hexdigest() == meta["sha256"]

    async def list_for_tenant(
        self, tenant_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        pool = await self._ensure()
        if pool is None:
            rows = [
                self._meta_from(r)
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return rows[offset : offset + limit]
        records = await pool.fetch(
            "SELECT id, tenant_id, job_id, export_type, filename, content_type, "
            "sha256, size_bytes, manifest, expires_at, deleted_at, created_at "
            "FROM export_artifacts WHERE tenant_id = $1 "
            "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            tenant_id,
            limit,
            offset,
        )
        return [self._meta_from(dict(r)) for r in records]


_repo: Optional[ArtifactRepository] = None


def get_artifact_repository() -> ArtifactRepository:
    global _repo
    if _repo is None:
        _repo = ArtifactRepository()
    return _repo
