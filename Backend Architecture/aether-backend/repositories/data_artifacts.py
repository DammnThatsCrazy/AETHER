"""
Aether Repository — Data Exchange Artifacts (``data_artifacts`` metadata)

Durable, tenant-scoped **metadata** store for Data Exchange Plane artifacts
(M1 of the Data Exchange program; see ``docs/plans/DATA_EXCHANGE_PHASES.md``).
Each row models the full ``DataArtifactContract`` envelope plus ``canonical_id``
(the canonical engine's import/export id the artifact maps onto).  Bytes never
touch Postgres on this path — the ``data_artifacts`` table is metadata only;
payload bytes live in the shared ObjectStore at ``object_key``.

Direct-SQL repository over the ``data_artifacts`` table created by the
``YYYYMMDD_data_exchange.py`` alembic migration.  Like ``artifacts.py`` and
``import_files.py`` this repo owns its own SQL (the envelope's typed columns
are inexpressible through the JSONB BaseRepository API) with an in-memory
fallback that mirrors the same semantics in local mode.

Status doctrine: a status is explicit — never inferred from the existence of
bytes.  Three byte-ownership classes (mirrored in
``services/data_exchange/retention.py``):

- **Durable-byte states** (``available`` / ``committed`` /
  ``partially_committed``) own real bytes at their ``object_key`` and a
  verified checksum (contracts.py).  They are never byte-less and never
  resurrected; the ONLY way into them is ``mark_available`` (with verified
  size/sha) or direct creation.  ``update_status`` may move them only to
  ``expired``/``deleted``/``revoked``.
- **Tombstones** (``failed`` / ``expired`` / ``deleted`` / ``revoked``) are
  absorbing audit stubs with no outgoing transitions; they survive payload
  expiry.
- **Transient** statuses (``created`` … ``generating``) are in-flight; they may
  move to any tombstone or other transient state, but never directly to a
  durable-byte state.

``update_status`` validates against the Data Exchange status vocabulary
(``services/data_exchange/contracts.py``) and enforces this legal-transition
policy, raising ``ConflictError`` on illegal moves (resurrection, durable→
``failed``, any →durable-byte-by-flip).
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from services.data_exchange.contracts import (
    DATA_ARTIFACT_STATUSES,
    DATA_EXCHANGE_CLASSIFICATIONS,
    DATA_EXCHANGE_DIRECTIONS,
)
from services.data_exchange.retention import (
    DURABLE_BYTE_STATUSES,
    TOMBSTONE_STATUSES,
)
from shared.common.common import BadRequestError, ConflictError, NotFoundError
from shared.temporal.instant import coerce_utc_lenient

# Must stay string-identical to DATA_ARTIFACTS_DDL in
# alembic/versions/YYYYMMDD_data_exchange.py (parity-tested).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS data_artifacts (
    artifact_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    job_id TEXT,
    canonical_id TEXT,
    source_or_destination JSONB NOT NULL DEFAULT '{}'::jsonb,
    object_key TEXT NOT NULL,
    filename TEXT NOT NULL,
    format TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL,
    schema_version TEXT,
    classification TEXT NOT NULL,
    encryption JSONB NOT NULL DEFAULT '{}'::jsonb,
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL,
    created_by TEXT,
    correlation_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, artifact_id)
);
CREATE INDEX IF NOT EXISTS ix_data_artifacts_tenant_direction
    ON data_artifacts (tenant_id, direction);
CREATE INDEX IF NOT EXISTS ix_data_artifacts_tenant_status
    ON data_artifacts (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_data_artifacts_tenant_canonical
    ON data_artifacts (tenant_id, canonical_id);
"""

# Module-local in-memory backing store, shared by every DataArtifactRepository
# instance so route/job/singleton and test-constructed repositories observe one
# consistent view under AETHER_ENV=local (mirrors repos._IN_MEMORY_STORES but
# deliberately module-scoped — this repo does not edit repositories/repos.py).
#
# Keyed by the SAME composite identity as the Postgres PK
# (``(tenant_id, artifact_id)``): artifact_id alone is never globally unique —
# egress artifacts reuse a client-supplied export_id as artifact_id, so two
# tenants may legally hold the same artifact_id (finding #14).
_LOCAL_STORE: dict[str, dict] = {}


def _local_key(tenant_id: str, artifact_id: str) -> str:
    """In-memory store key mirroring the ``(tenant_id, artifact_id)`` PK."""
    return f"{tenant_id}\x00{artifact_id}"


def reset_data_artifact_in_memory_store() -> None:
    """Test helper: empty the module-local in-memory artifact store."""
    _LOCAL_STORE.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, datetime):
        return coerce_utc_lenient(raw) or raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(raw: Any) -> Optional[str]:
    dt = _parse_ts(raw)
    return dt.isoformat() if dt is not None else None


def _parse_json(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            parsed = _json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return dict(value) if isinstance(value, dict) else {}


def _validate_status(status: str) -> None:
    if status not in DATA_ARTIFACT_STATUSES:
        raise BadRequestError(
            f"invalid data artifact status {status!r} — expected one of "
            f"{', '.join(DATA_ARTIFACT_STATUSES)}"
        )


def _illegal_transition_reason(current: str, target: str) -> Optional[str]:
    """Human reason ``current`` → ``target`` is illegal, else ``None``.

    Byte-ownership doctrine (see module docstring).  Ordering matters: a target
    that is a durable-byte state is ALWAYS illegal via ``update_status`` (real
    bytes + verified checksum must be recorded by ``mark_available`` first);
    a ``failed`` source may only move to ``deleted`` (checked BEFORE the generic
    absorbing-tombstone branch — ``failed`` is a member of ``TOMBSTONE_STATUSES``
    yet is not fully absorbing, since cleanup may refine it to the ``deleted``
    audit stub); the other tombstone sources have no outgoing transitions at
    all; a durable-byte source may only tombstone to ``expired``/``deleted``/
    ``revoked`` (never ``failed`` — a failed artifact never had durable bytes to
    lose).
    """
    if target in DURABLE_BYTE_STATUSES:
        return (
            f"{current!r} -> {target!r} would reach a durable-byte state without "
            "verified bytes — promotion to available/committed/partially_committed "
            "must go through mark_available"
        )
    if current == "failed":
        if target != "deleted":
            return f"a failed artifact may only move to 'deleted', not to {target!r}"
        return None
    if current in TOMBSTONE_STATUSES:
        return f"{current!r} is an absorbing tombstone with no outgoing transitions"
    if current in DURABLE_BYTE_STATUSES:
        if target not in {"expired", "deleted", "revoked"}:
            return (
                f"{current!r} is a durable-byte state and may only move to "
                f"'expired'/'deleted'/'revoked', not to {target!r}"
            )
        return None
    return None


class DataArtifactRepository:
    """Tenant-scoped Data Exchange artifact metadata store (Postgres /
    in-memory local).  Metadata only — payload bytes live in ObjectStore."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @property
    def _store(self) -> dict[str, dict]:
        # Resolved lazily (like repositories/import_files.py) so reads and
        # writes always observe the *current* module state even across test
        # sys.modules churn, and never bind to a stale dict at import time.
        return _LOCAL_STORE

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    # ── writes ────────────────────────────────────────────────────────────

    async def create_artifact(
        self,
        artifact_id: str,
        tenant_id: str,
        *,
        direction: str,
        artifact_type: str,
        object_key: str,
        filename: str,
        format: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        classification: str,
        status: str,
        canonical_id: Optional[str] = None,
        job_id: Optional[str] = None,
        source_or_destination: Optional[dict] = None,
        schema_version: Optional[str] = None,
        encryption: Optional[dict] = None,
        manifest: Optional[dict] = None,
        created_by: Optional[str] = None,
        correlation_id: Optional[str] = None,
        expires_at: Optional[Any] = None,
        created_at: Optional[Any] = None,
    ) -> dict:
        """Insert one data-artifact metadata row (envelope + canonical_id)."""
        if not artifact_id or not tenant_id:
            raise BadRequestError("artifact_id and tenant_id are required")
        if direction not in DATA_EXCHANGE_DIRECTIONS:
            raise BadRequestError(
                f"invalid data artifact direction {direction!r} — expected one of "
                f"{', '.join(DATA_EXCHANGE_DIRECTIONS)}"
            )
        if classification not in DATA_EXCHANGE_CLASSIFICATIONS:
            raise BadRequestError(
                f"invalid data artifact classification {classification!r} — "
                f"expected one of {', '.join(DATA_EXCHANGE_CLASSIFICATIONS)}"
            )
        _validate_status(status)
        if not object_key or not filename or not format or not sha256:
            raise BadRequestError(
                "object_key, filename, format and sha256 are required"
            )
        if size_bytes < 0:
            raise BadRequestError("size_bytes must be >= 0")

        created = _parse_ts(created_at) or _now()
        row: dict[str, Any] = {
            "artifact_id": artifact_id,
            "tenant_id": tenant_id,
            "direction": direction,
            "artifact_type": artifact_type,
            "job_id": job_id,
            "canonical_id": canonical_id,
            "source_or_destination": dict(source_or_destination or {}),
            "object_key": object_key,
            "filename": filename,
            "format": format,
            "content_type": content_type,
            "size_bytes": int(size_bytes),
            "sha256": sha256,
            "schema_version": schema_version,
            "classification": classification,
            "encryption": dict(encryption or {}),
            "manifest": dict(manifest or {}),
            "status": status,
            "created_by": created_by,
            "correlation_id": correlation_id,
            "created_at": created.isoformat(),
            "expires_at": _iso(expires_at),
            "deleted_at": None,
            "updated_at": created.isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            self._store[_local_key(tenant_id, artifact_id)] = dict(row)
        else:
            await pool.execute(
                """
                INSERT INTO data_artifacts
                    (artifact_id, tenant_id, direction, artifact_type, job_id,
                     canonical_id, source_or_destination, object_key, filename,
                     format, content_type, size_bytes, sha256, schema_version,
                     classification, encryption, manifest, status, created_by,
                     correlation_id, created_at, expires_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12,$13,$14,
                        $15,$16::jsonb,$17::jsonb,$18,$19,$20,$21,$22)
                """,
                artifact_id,
                tenant_id,
                direction,
                artifact_type,
                job_id,
                canonical_id,
                _json.dumps(row["source_or_destination"], default=str),
                object_key,
                filename,
                format,
                content_type,
                int(size_bytes),
                sha256,
                schema_version,
                classification,
                _json.dumps(row["encryption"], default=str),
                _json.dumps(row["manifest"], default=str),
                status,
                created_by,
                correlation_id,
                created,
                _parse_ts(expires_at),
            )
        return dict(row)

    async def mark_deleted(self, tenant_id: str, artifact_id: str) -> dict:
        """Tombstone an artifact (status ``deleted`` + ``deleted_at`` now)."""
        row = await self.update_status(tenant_id, artifact_id, "deleted")
        now = _now()
        pool = await self._ensure()
        if pool is None:
            key = _local_key(tenant_id, artifact_id)
            self._store[key]["deleted_at"] = now.isoformat()
            self._store[key]["updated_at"] = now.isoformat()
        else:
            await pool.execute(
                "UPDATE data_artifacts SET deleted_at = $3, updated_at = now() "
                "WHERE tenant_id = $1 AND artifact_id = $2",
                tenant_id,
                artifact_id,
            )
        return dict(await self.get(tenant_id, artifact_id))

    async def mark_expired(self, tenant_id: str, artifact_id: str) -> dict:
        """Mark an artifact expired (status ``expired``)."""
        return await self.update_status(tenant_id, artifact_id, "expired")

    async def mark_available(
        self,
        tenant_id: str,
        artifact_id: str,
        *,
        size_bytes: int,
        sha256: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Flip a transient row to terminal ``available`` with verified bytes.

        The ONLY transition that reaches ``available`` (M4/M5 materialization):
        a row created as ``generating`` carries the empty-payload sentinel sha
        until the real bytes are durable in the ObjectStore; ``mark_available``
        atomically records the *verified* size/sha256, merges ``metadata`` into
        ``source_or_destination`` (the bridge sets ``materialized: true``) and
        moves the row to ``available``.

        Idempotent: an already-``available`` row is returned untouched.  A
        tombstone (``failed`` / ``deleted`` / ``expired`` / ``revoked``) can
        never be resurrected to ``available``, and a durable-byte sibling
        (``committed`` / ``partially_committed``) is never silently re-flipped —
        both raise ``ConflictError``.
        """
        if size_bytes < 0:
            raise BadRequestError("size_bytes must be >= 0")
        if not sha256:
            raise BadRequestError("sha256 is required to mark an artifact available")
        current = await self.get(tenant_id, artifact_id)
        current_status = current.get("status") or "created"
        if current_status == "available":
            return current
        if current_status in TOMBSTONE_STATUSES or current_status in DURABLE_BYTE_STATUSES:
            raise ConflictError(
                f"data artifact {artifact_id!r} is {current_status!r} and cannot "
                "be resurrected/moved to 'available' (only mark_available may "
                "reach a durable-byte state)"
            )
        merged = _parse_json(current.get("source_or_destination"))
        merged.update({"materialized": True})
        if metadata:
            merged.update(dict(metadata))
        now = _now()
        pool = await self._ensure()
        if pool is None:
            row = self._store[_local_key(tenant_id, artifact_id)]
            row["status"] = "available"
            row["size_bytes"] = int(size_bytes)
            row["sha256"] = sha256
            row["source_or_destination"] = merged
            row["updated_at"] = now.isoformat()
            return self._meta_from(row)
        await pool.execute(
            "UPDATE data_artifacts "
            "SET status = 'available', size_bytes = $3, sha256 = $4, "
            "source_or_destination = $5::jsonb, updated_at = now() "
            "WHERE tenant_id = $1 AND artifact_id = $2",
            tenant_id,
            artifact_id,
            int(size_bytes),
            sha256,
            _json.dumps(merged, default=str),
        )
        return await self.get(tenant_id, artifact_id)

    # ── reads ─────────────────────────────────────────────────────────────

    def _meta_from(self, row: dict) -> dict:
        meta = {
            "artifact_id": row.get("artifact_id"),
            "tenant_id": row.get("tenant_id"),
            "direction": row.get("direction"),
            "artifact_type": row.get("artifact_type"),
            "job_id": row.get("job_id"),
            "canonical_id": row.get("canonical_id"),
            "source_or_destination": _parse_json(row.get("source_or_destination")),
            "object_key": row.get("object_key"),
            "filename": row.get("filename"),
            "format": row.get("format"),
            "content_type": row.get("content_type"),
            "size_bytes": row.get("size_bytes"),
            "sha256": row.get("sha256"),
            "schema_version": row.get("schema_version"),
            "classification": row.get("classification"),
            "encryption": _parse_json(row.get("encryption")),
            "manifest": _parse_json(row.get("manifest")),
            "status": row.get("status"),
            "created_by": row.get("created_by"),
            "correlation_id": row.get("correlation_id"),
            "created_at": _iso(row.get("created_at")),
            "expires_at": _iso(row.get("expires_at")),
            "deleted_at": _iso(row.get("deleted_at")),
            "updated_at": _iso(row.get("updated_at")),
        }
        # ``updated_at`` may be absent on rows produced by very old writes.
        meta["updated_at"] = meta.get("updated_at") or meta.get("created_at")
        return meta

    async def get(self, tenant_id: str, artifact_id: str) -> dict:
        """Return the artifact row scoped to tenant; refuses cross-tenant reads."""
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(_local_key(tenant_id, artifact_id))
            if row is None:
                raise NotFoundError("data exchange artifact")
            return self._meta_from(row)
        record = await pool.fetchrow(
            "SELECT artifact_id, tenant_id, direction, artifact_type, job_id, "
            "canonical_id, source_or_destination, object_key, filename, format, "
            "content_type, size_bytes, sha256, schema_version, classification, "
            "encryption, manifest, status, created_by, correlation_id, created_at, "
            "expires_at, deleted_at, updated_at FROM data_artifacts "
            "WHERE tenant_id = $1 AND artifact_id = $2",
            tenant_id,
            artifact_id,
        )
        if record is None:
            raise NotFoundError("data exchange artifact")
        return self._meta_from(dict(record))

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        direction: Optional[str] = None,
        artifact_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """Newest-first rows for a tenant with optional filters."""
        if direction is not None and direction not in DATA_EXCHANGE_DIRECTIONS:
            raise BadRequestError(
                f"invalid data artifact direction {direction!r} — expected one of "
                f"{', '.join(DATA_EXCHANGE_DIRECTIONS)}"
            )
        if status is not None:
            _validate_status(status)
        limit = max(0, int(limit))
        offset = max(0, int(offset))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id
                and (direction is None or r.get("direction") == direction)
                and (artifact_type is None or r.get("artifact_type") == artifact_type)
                and (status is None or r.get("status") == status)
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [self._meta_from(r) for r in rows[offset : offset + limit]]

        clauses = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        if direction is not None:
            params.append(direction)
            clauses.append(f"direction = ${len(params)}")
        if artifact_type is not None:
            params.append(artifact_type)
            clauses.append(f"artifact_type = ${len(params)}")
        if status is not None:
            params.append(status)
            clauses.append(f"status = ${len(params)}")
        params.extend([limit, offset])
        records = await pool.fetch(
            "SELECT artifact_id, tenant_id, direction, artifact_type, job_id, "
            "canonical_id, source_or_destination, object_key, filename, format, "
            "content_type, size_bytes, sha256, schema_version, classification, "
            "encryption, manifest, status, created_by, correlation_id, created_at, "
            "expires_at, deleted_at, updated_at FROM data_artifacts "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC "
            f"LIMIT ${len(params) - 1} OFFSET ${len(params)}",
            *params,
        )
        return [self._meta_from(dict(r)) for r in records]

    async def get_by_canonical_id(
        self, tenant_id: str, canonical_id: str
    ) -> Optional[dict]:
        """Newest artifact row mapping to a canonical engine id (tenant-scoped)."""
        if not canonical_id:
            return None
        rows = await self.list_by_canonical_id(tenant_id, canonical_id, limit=1)
        return rows[0] if rows else None

    async def list_by_canonical_id(
        self,
        tenant_id: str,
        canonical_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """All artifact rows sharing one canonical engine id (tenant-scoped)."""
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("canonical_id") == canonical_id
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [self._meta_from(r) for r in rows[offset : offset + limit]]
        records = await pool.fetch(
            "SELECT artifact_id, tenant_id, direction, artifact_type, job_id, "
            "canonical_id, source_or_destination, object_key, filename, format, "
            "content_type, size_bytes, sha256, schema_version, classification, "
            "encryption, manifest, status, created_by, correlation_id, created_at, "
            "expires_at, deleted_at, updated_at FROM data_artifacts "
            "WHERE tenant_id = $1 AND canonical_id = $2 "
            "ORDER BY created_at DESC LIMIT $3 OFFSET $4",
            tenant_id,
            canonical_id,
            limit,
            offset,
        )
        return [self._meta_from(dict(r)) for r in records]

    async def usage_rows(self, tenant_id: str) -> list[dict]:
        """All of a tenant's artifact rows PROJECTED to usage-relevant columns
        with no arbitrary cap (finding #13).

        The M3 ``/usage`` read adapter aggregates over EVERY artifact row, so
        feeding it ``list_for_tenant(limit=100000)`` silently under-counted a
        tenant past 100k rows and dragged all 24 envelope columns along.  This
        returns only what the aggregation reads
        (``direction``/``artifact_type``/``size_bytes``/``created_at``/
        ``source_or_destination``) and pages the Postgres scan to exhaustion
        (the in-memory fallback is already unbounded).
        """
        pool = await self._ensure()
        if pool is None:
            return [
                self._usage_projection(r)
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id
            ]
        page = 10000
        offset = 0
        out: list[dict] = []
        while True:
            records = await pool.fetch(
                "SELECT direction, artifact_type, size_bytes, created_at, "
                "source_or_destination FROM data_artifacts "
                "WHERE tenant_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                tenant_id,
                page,
                offset,
            )
            rows = [self._usage_projection(dict(r)) for r in records]
            out.extend(rows)
            if len(rows) < page:
                break
            offset += page
        return out

    @staticmethod
    def _usage_projection(row: dict) -> dict:
        """Trim one raw row to the five fields ``/usage`` aggregation reads."""
        return {
            "direction": row.get("direction"),
            "artifact_type": row.get("artifact_type"),
            "size_bytes": row.get("size_bytes"),
            "created_at": _iso(row.get("created_at")),
            "source_or_destination": _parse_json(row.get("source_or_destination")),
        }

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def update_status(
        self, tenant_id: str, artifact_id: str, status: str
    ) -> dict:
        """Move an artifact to ``status`` under the byte-ownership doctrine.

        Refuses unknown statuses (``BadRequestError``), cross-tenant targets
        (``NotFoundError``), and every transition the doctrine forbids
        (``ConflictError``): resurrection out of a tombstone, durable-byte
        states moving anywhere but ``expired``/``deleted``/``revoked``, a
        ``failed`` row moving anywhere but ``deleted``, and ANY move into a
        durable-byte state (``available``/``committed``/``partially_committed``)
        — those require ``mark_available`` with verified bytes.  Same-status
        moves are an idempotent no-op (``mark_deleted``/``mark_expired`` may
        re-fire on already-tombstoned rows).
        """
        _validate_status(status)
        current = await self.get(tenant_id, artifact_id)
        current_status = current.get("status") or "created"
        if current_status == status:
            return current
        reason = _illegal_transition_reason(current_status, status)
        if reason is not None:
            raise ConflictError(f"data artifact {artifact_id!r}: {reason}")
        now = _now()
        pool = await self._ensure()
        if pool is None:
            row = self._store[_local_key(tenant_id, artifact_id)]
            row["status"] = status
            row["updated_at"] = now.isoformat()
            return self._meta_from(row)
        await pool.execute(
            "UPDATE data_artifacts SET status = $3, updated_at = now() "
            "WHERE tenant_id = $1 AND artifact_id = $2",
            tenant_id,
            artifact_id,
        )
        return await self.get(tenant_id, artifact_id)


_repo: Optional[DataArtifactRepository] = None


def get_data_artifact_repository() -> DataArtifactRepository:
    """Module singleton mirroring ``get_artifact_repository()``."""
    global _repo
    if _repo is None:
        _repo = DataArtifactRepository()
    return _repo
