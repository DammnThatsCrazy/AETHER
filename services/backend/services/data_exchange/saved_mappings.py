"""Data Exchange Plane — saved import-mapping persistence (M3).

Net-new, tenant-scoped persistence for reusable ``ImportMappingContract``
mappings (``docs/plans/data-exchange-api.md`` M3 ``/import-mappings`` rows).
A saved mapping is the full Data Exchange envelope mapping (the import engine's
canonical ``FieldMapping`` list inside ``fields`` plus the identity / temporal /
currency / geographic / consent policies and the unknown-field rule) bound to a
human-readable ``name`` the tenant re-applies on later imports.  Bytes never
touch Postgres here; the JSONB policy columns are metadata only.

Direct-SQL repository over the ``data_exchange_saved_mappings`` table created
by the ``YYYYMMDD_data_exchange.py`` alembic migration (the coordinator lands
``SCHEMA_SQL`` verbatim into that migration).  Like ``repositories/
data_artifacts.py`` (M1) this repo owns its own SQL because the typed JSONB
columns are inexpressible through the JSONB BaseRepository API, and it keeps the
same module-local in-memory fallback so route/job/singleton and test-constructed
repositories observe one consistent view under ``AETHER_ENV=local``.
"""

from __future__ import annotations

import json as _json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from repositories.repos import get_pool
from services.data_exchange.authz import require_data_exchange
from services.data_exchange.contracts import ImportMappingContract
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError
from shared.temporal.instant import coerce_utc_lenient

# Must stay string-identical to the saved-mappings fragment of
# alembic/versions/YYYYMMDD_data_exchange.py (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS data_exchange_saved_mappings (
    mapping_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    import_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    identity_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    temporal_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    currency_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    geographic_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    consent_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    unknown_field_policy TEXT NOT NULL DEFAULT 'error',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_data_exchange_saved_mappings_tenant_name
    ON data_exchange_saved_mappings (tenant_id, name);
CREATE INDEX IF NOT EXISTS ix_data_exchange_saved_mappings_tenant_import
    ON data_exchange_saved_mappings (tenant_id, import_id);
"""

# Module-local in-memory backing store, shared by every
# SavedImportMappingRepository instance (mirrors repositories/data_artifacts.py).
_LOCAL_STORE: dict[str, dict] = {}


def reset_saved_mapping_in_memory_store() -> None:
    """Test helper: empty the module-local in-memory saved-mapping store."""
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


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return _json.loads(value)
        except ValueError:
            return {}
    return value


def _validate_unknown_field_policy(value: str) -> None:
    if value not in ("error", "ignore"):
        raise BadRequestError(
            f"invalid unknown_field_policy {value!r} — expected 'error' or 'ignore'"
        )


def _rowcount(result: Any) -> int:
    """Asyncpg ``pool.execute`` returns a command-status *string* (``"DELETE 1"``)
    with no ``.rowcount`` attribute — parse the trailing count like every other
    repo (e.g. ``repositories/continuation_repo.py``)."""
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


def _validate_mapping_contract(contract: ImportMappingContract) -> None:
    """Structural validation for a persisted envelope mapping."""
    if not contract.import_id:
        raise BadRequestError("import_id is required")
    if int(contract.version or 0) < 1:
        raise BadRequestError("version must be >= 1")
    if not isinstance(contract.fields, list):
        raise BadRequestError("fields must be a list")
    _validate_unknown_field_policy(contract.unknown_field_policy)


class SavedImportMappingRepository:
    """Tenant-scoped saved ImportMappingContract store (Postgres / in-memory)."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @property
    def _store(self) -> dict[str, dict]:
        return _LOCAL_STORE

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    # ── writes ────────────────────────────────────────────────────────────

    async def create(
        self,
        tenant_id: str,
        *,
        name: str,
        contract: ImportMappingContract,
        created_by: Optional[str] = None,
    ) -> dict:
        """Persist one saved envelope mapping (mints ``mapping_id``)."""
        if not tenant_id:
            raise BadRequestError("tenant_id is required")
        name = (name or "").strip()
        if not name:
            raise BadRequestError("name is required")
        _validate_mapping_contract(contract)

        mapping_id = f"demap_{uuid.uuid4().hex}"
        now = _now()
        row: dict[str, Any] = {
            "mapping_id": mapping_id,
            "tenant_id": tenant_id,
            "name": name,
            "import_id": contract.import_id,
            "version": int(contract.version or 1),
            "fields": contract.fields or [],
            "identity_policy": contract.identity_policy or {},
            "temporal_policy": contract.temporal_policy or {},
            "currency_policy": contract.currency_policy or {},
            "geographic_policy": contract.geographic_policy or {},
            "consent_policy": contract.consent_policy or {},
            "unknown_field_policy": contract.unknown_field_policy,
            "created_by": created_by,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            self._store[mapping_id] = dict(row)
        else:
            await pool.execute(
                """
                INSERT INTO data_exchange_saved_mappings
                    (mapping_id, tenant_id, name, import_id, version, fields,
                     identity_policy, temporal_policy, currency_policy,
                     geographic_policy, consent_policy, unknown_field_policy,
                     created_by, created_at)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9::jsonb,
                        $10::jsonb,$11::jsonb,$12,$13,$14)
                """,
                mapping_id,
                tenant_id,
                name,
                contract.import_id,
                int(contract.version or 1),
                _json.dumps(contract.fields or [], default=str),
                _json.dumps(contract.identity_policy or {}, default=str),
                _json.dumps(contract.temporal_policy or {}, default=str),
                _json.dumps(contract.currency_policy or {}, default=str),
                _json.dumps(contract.geographic_policy or {}, default=str),
                _json.dumps(contract.consent_policy or {}, default=str),
                contract.unknown_field_policy,
                created_by,
                now,
            )
        return dict(row)

    # ── reads ─────────────────────────────────────────────────────────────

    def _meta_from(self, row: dict) -> dict:
        meta = {
            "mapping_id": row.get("mapping_id"),
            "tenant_id": row.get("tenant_id"),
            "name": row.get("name"),
            "import_id": row.get("import_id"),
            "version": row.get("version"),
            "fields": _parse_json(row.get("fields")) or [],
            "identity_policy": _parse_json(row.get("identity_policy")) or {},
            "temporal_policy": _parse_json(row.get("temporal_policy")) or {},
            "currency_policy": _parse_json(row.get("currency_policy")) or {},
            "geographic_policy": _parse_json(row.get("geographic_policy")) or {},
            "consent_policy": _parse_json(row.get("consent_policy")) or {},
            "unknown_field_policy": row.get("unknown_field_policy") or "error",
            "created_by": row.get("created_by"),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")) or _iso(row.get("created_at")),
        }
        return meta

    async def get(self, tenant_id: str, mapping_id: str) -> dict:
        """Return one saved mapping; refuses cross-tenant reads."""
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(mapping_id)
            if row is None or row.get("tenant_id") != tenant_id:
                raise NotFoundError("saved import mapping")
            return self._meta_from(row)
        record = await pool.fetchrow(
            "SELECT mapping_id, tenant_id, name, import_id, version, fields, "
            "identity_policy, temporal_policy, currency_policy, geographic_policy, "
            "consent_policy, unknown_field_policy, created_by, created_at, updated_at "
            "FROM data_exchange_saved_mappings "
            "WHERE tenant_id = $1 AND mapping_id = $2",
            tenant_id,
            mapping_id,
        )
        if record is None:
            raise NotFoundError("saved import mapping")
        return self._meta_from(dict(record))

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        import_id: Optional[str] = None,
    ) -> list[dict]:
        """Newest-first saved mappings for a tenant (optionally by import)."""
        limit = max(0, int(limit))
        offset = max(0, int(offset))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id
                and (import_id is None or r.get("import_id") == import_id)
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [self._meta_from(r) for r in rows[offset : offset + limit]]
        if import_id is not None:
            records = await pool.fetch(
                "SELECT mapping_id, tenant_id, name, import_id, version, fields, "
                "identity_policy, temporal_policy, currency_policy, geographic_policy, "
                "consent_policy, unknown_field_policy, created_by, created_at, updated_at "
                "FROM data_exchange_saved_mappings "
                "WHERE tenant_id = $1 AND import_id = $2 "
                "ORDER BY created_at DESC LIMIT $3 OFFSET $4",
                tenant_id,
                import_id,
                limit,
                offset,
            )
        else:
            records = await pool.fetch(
                "SELECT mapping_id, tenant_id, name, import_id, version, fields, "
                "identity_policy, temporal_policy, currency_policy, geographic_policy, "
                "consent_policy, unknown_field_policy, created_by, created_at, updated_at "
                "FROM data_exchange_saved_mappings "
                "WHERE tenant_id = $1 "
                "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                tenant_id,
                limit,
                offset,
            )
        return [self._meta_from(dict(r)) for r in records]

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def delete(self, tenant_id: str, mapping_id: str) -> bool:
        """Delete a saved mapping (tenant-scoped; False when absent)."""
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(mapping_id)
            if row is None or row.get("tenant_id") != tenant_id:
                return False
            del self._store[mapping_id]
            return True
        result = await pool.execute(
            "DELETE FROM data_exchange_saved_mappings "
            "WHERE tenant_id = $1 AND mapping_id = $2",
            tenant_id,
            mapping_id,
        )
        return _rowcount(result) > 0


_repo: Optional[SavedImportMappingRepository] = None


def get_data_exchange_saved_mappings_repository() -> SavedImportMappingRepository:
    """Module singleton mirroring ``get_data_artifact_repository()``."""
    global _repo
    if _repo is None:
        _repo = SavedImportMappingRepository()
    return _repo


# ── HTTP surface (prefix /v1/data-exchange/import-mappings) ─────────────────

router = APIRouter(
    prefix="/v1/data-exchange/import-mappings",
    tags=["Data Exchange Imports"],
)


class SavedMappingCreateBody(ImportMappingContract):
    """POST body: a full ``ImportMappingContract`` plus a display ``name``."""

    name: str = Field(..., min_length=1)


def _tenant(request: Request, permission: str = "data_exchange.read"):
    tenant = request.state.tenant
    require_data_exchange(tenant, permission)
    return tenant


@router.get("")
async def list_saved_mappings(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    import_id: Optional[str] = Query(default=None),
):
    tenant = _tenant(request, "data_exchange.read")
    repo = get_data_exchange_saved_mappings_repository()
    # Both branches honor the caller's page — the import_id filter must not
    # silently cap the feed at the repo default of 50.
    mappings = await repo.list_for_tenant(
        tenant.tenant_id, limit=limit, offset=offset, import_id=import_id
    )
    return {"mappings": mappings, "count": len(mappings)}


@router.post("")
async def create_saved_mapping(body: SavedMappingCreateBody, request: Request):
    tenant = _tenant(request, "data_exchange.import.map")
    if body.tenant_id != tenant.tenant_id:
        raise ForbiddenError(
            f"tenant_id {body.tenant_id!r} does not match the authenticated tenant"
        )
    repo = get_data_exchange_saved_mappings_repository()
    row = await repo.create(
        tenant.tenant_id,
        name=body.name,
        contract=body,
        created_by=getattr(tenant, "user_id", None),
    )
    return {
        "mapping_id": row["mapping_id"],
        "import_id": row["import_id"],
        "version": row["version"],
    }


@router.get("/{mapping_id}")
async def get_saved_mapping(mapping_id: str, request: Request):
    tenant = _tenant(request, "data_exchange.read")
    repo = get_data_exchange_saved_mappings_repository()
    return await repo.get(tenant.tenant_id, mapping_id)


@router.delete("/{mapping_id}")
async def delete_saved_mapping(mapping_id: str, request: Request):
    tenant = _tenant(request, "data_exchange.import.map")
    repo = get_data_exchange_saved_mappings_repository()
    deleted = await repo.delete(tenant.tenant_id, mapping_id)
    if not deleted:
        raise NotFoundError("saved import mapping")
    return {"deleted": True, "mapping_id": mapping_id}
