"""Reconciled Control Plane — §9.1/§9.2 source-authority + equivalence stores (Phase 3).

Direct-SQL repositories over the tables created by the
``20260906_rcp_source_authority.py`` alembic migration (the migration lands
``SCHEMA_SQL`` verbatim — string-identical, mirroring the Phase-2
``execution_records_repository`` and Phase-1 ``change_sets_repository``).

These stores hold the control plane's *own* reasoning configuration — never
canonical downstream facts (§9.3 boundary):

* ``SourceAuthorityRuleRepository`` — §9.1 SourceAuthorityRuleContract rows:
  domain/property-specific ``source_precedence`` (authority is never a blanket
  "provider X is always superior" statement).
* ``ObservationEquivalenceKeyRepository`` — §9.2
  ObservationEquivalenceKeyContract rows: semantic-equivalence keys that
  separate transport idempotency from semantic deduplication (§19).

Every repository keeps the module-local in-memory fallback (``get_pool()``
None under ``AETHER_ENV=local``), so unit tests exercise the same columnar path
the engine uses without a live Postgres. Tenancy (CP-11): a NULL ``tenant_id``
row is global (Olympus); scoped reads always match ``tenant_id = $X OR
tenant_id IS NULL`` and never leak a tenant's private row cross-tenant.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import (
    ObservationEquivalenceKeyView,
    SourceAuthorityRuleView,
)

# Must stay string-identical to the alembic migration
# ``20260906_rcp_source_authority.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_authority_rules (
    rule_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    property_path TEXT NOT NULL,
    source_precedence JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflict_strategy TEXT,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    policy_ref TEXT,
    tenant_id TEXT,
    environment_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_source_authority_rules_domain
    ON source_authority_rules (domain, property_path);

CREATE TABLE IF NOT EXISTS observation_equivalence_keys (
    key_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    candidate_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    key_components JSONB NOT NULL DEFAULT '[]'::jsonb,
    window TEXT,
    normalization_rules JSONB,
    semantic_dedupe_policy TEXT,
    tenant_id TEXT,
    environment_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_observation_equivalence_keys_domain
    ON observation_equivalence_keys (domain);
"""

# Module-local in-memory backing stores, shared by every repository instance.
# Keys are the row's primary key (mirrors services/data_exchange/saved_mappings.py).
_RULE_STORE: dict[str, dict] = {}
_KEY_STORE: dict[str, dict] = {}


def reset_source_authority_stores() -> None:
    """Test helper: empty every module-local source-authority store."""
    _RULE_STORE.clear()
    _KEY_STORE.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, datetime):
        return coerce_utc_lenient(raw) or raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _iso(raw: Any) -> Optional[str]:
    dt = _parse_ts(raw)
    return dt.isoformat() if dt is not None else None


def _parse_json(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return _json.loads(value)
        except ValueError:
            return {}
    return value


def _rowcount(result: Any) -> int:
    """Asyncpg ``pool.execute`` returns a command-status *string* — parse the
    trailing count like every other repo."""
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


# ── typed storage views (mirror the table columns) ───────────────────────────


class SourceAuthorityRuleRow(BaseModel):
    """A durable §9.1 source-authority rule row (all table columns)."""

    rule_id: str
    domain: str
    property_path: str
    source_precedence: list[str] = Field(default_factory=list)
    conflict_strategy: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    policy_ref: Optional[str] = None
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None
    created_at: datetime


class ObservationEquivalenceKeyRow(BaseModel):
    """A durable §9.2 observation-equivalence key row (all table columns)."""

    key_id: str
    domain: str
    candidate_types: list[str] = Field(default_factory=list)
    key_components: list[str] = Field(default_factory=list)
    window: Optional[str] = None
    normalization_rules: Optional[list[str]] = None
    semantic_dedupe_policy: Optional[str] = None
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None
    created_at: datetime


class _AuthorityRepo:
    """Shared pool/ensure plumbing for the source-authority repositories."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool


def _visible_tenancy(row: dict, tenant_id: Optional[str]) -> bool:
    """CP-11 visibility for reads: global rows (tenant_id NULL) are visible to
    every scoped read; a tenant's private row is visible only to that tenant.

    ``tenant_id=None`` is the Olympus/global read scope — it sees global rows
    only and can never observe a tenant's private row.
    """
    row_tenant = row.get("tenant_id")
    if tenant_id is None:
        return row_tenant is None
    return row_tenant is None or row_tenant == tenant_id


def _owned_tenancy(row: dict, tenant_id: Optional[str]) -> bool:
    """CP-11 ownership for destructive ops (delete): unlike reads, a scoped
    delete never matches a global row. The None (Olympus) scope deletes global
    rows only; a tenant scope deletes exactly its own private row."""
    row_tenant = row.get("tenant_id")
    if tenant_id is None:
        return row_tenant is None
    return row_tenant == tenant_id


# ── §9.1 source-authority rules ──────────────────────────────────────────────


class SourceAuthorityRuleRepository(_AuthorityRepo):
    """Durable §9.1 source-authority rules (domain/property-specific)."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _RULE_STORE

    async def create(self, view: SourceAuthorityRuleView) -> dict:
        if not view.source_precedence:
            raise ValueError(
                "source_precedence must be non-empty (§9.1: authority is "
                "domain/property specific — a rule with an empty precedence "
                "orders nothing)"
            )
        row = {
            **view.model_dump(mode="json"),
            "created_at": _now().isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            self._store[view.rule_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO source_authority_rules (rule_id, domain, "
            "property_path, source_precedence, conflict_strategy, valid_from, "
            "valid_to, policy_ref, tenant_id, environment_id) "
            "VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9,$10)",
            view.rule_id,
            view.domain,
            view.property_path,
            _json.dumps(view.source_precedence),
            view.conflict_strategy,
            view.valid_from,
            view.valid_to,
            view.policy_ref,
            view.tenant_id,
            view.environment_id,
        )
        record = await pool.fetchrow(
            "SELECT * FROM source_authority_rules WHERE rule_id=$1",
            view.rule_id,
        )
        return _rule_row(dict(record)) if record is not None else dict(row)

    async def get(self, *, rule_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
        """Scoped read: tenant-or-global when ``tenant_id`` is given; global
        rows only when it is None (an Olympus read can never see a tenant's
        private rule, and no tenant read can see another tenant's)."""
        pool = await self._ensure()
        if pool is None:
            stored = self._store.get(rule_id)
            if stored is None or not _visible_tenancy(stored, tenant_id):
                return None
            return dict(stored)
        if tenant_id is None:
            record = await pool.fetchrow(
                "SELECT * FROM source_authority_rules WHERE rule_id=$1 AND tenant_id IS NULL",
                rule_id,
            )
        else:
            record = await pool.fetchrow(
                "SELECT * FROM source_authority_rules "
                "WHERE rule_id=$1 AND (tenant_id=$2 OR tenant_id IS NULL)",
                rule_id,
                tenant_id,
            )
        return _rule_row(dict(record)) if record is not None else None

    async def list(
        self,
        *,
        domain: Optional[str] = None,
        tenant_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """List rules, CP-11 scoped: a tenant read returns its own rules plus
        global rules; the global (None) read returns global rules only.

        Ordering is deterministic and SQL-parity: ``created_at DESC`` then
        ``rule_id ASC`` (ties on an equal timestamp fall back to rule_id).
        """
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                dict(r)
                for r in self._store.values()
                if (domain is None or r.get("domain") == domain) and _visible_tenancy(r, tenant_id)
            ]
            rows.sort(key=lambda r: r.get("rule_id") or "")
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return rows[:limit]
        where: list[str] = []
        args: list[Any] = []
        if domain is not None:
            args.append(domain)
            where.append(f"domain = ${len(args)}")
        if tenant_id is None:
            where.append("tenant_id IS NULL")
        else:
            args.append(tenant_id)
            where.append(f"(tenant_id = ${len(args)} OR tenant_id IS NULL)")
        args.append(limit)
        records = await pool.fetch(
            "SELECT * FROM source_authority_rules "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC, rule_id ASC LIMIT " + str(len(args)),
            *args,
        )
        return [_rule_row(dict(r)) for r in records]

    async def delete(self, *, rule_id: str, tenant_id: Optional[str] = None) -> bool:
        """Hard-delete a stale rule, CP-11 scoped (governed ops need removal of
        stale rules). A tenant scope can only delete its own private row —
        never a global rule; the None (Olympus) scope deletes global rows only.
        Returns whether a row was actually deleted."""
        pool = await self._ensure()
        if pool is None:
            stored = self._store.get(rule_id)
            if stored is None or not _owned_tenancy(stored, tenant_id):
                return False
            del self._store[rule_id]
            return True
        if tenant_id is None:
            result = await pool.execute(
                "DELETE FROM source_authority_rules WHERE rule_id=$1 AND tenant_id IS NULL",
                rule_id,
            )
        else:
            result = await pool.execute(
                "DELETE FROM source_authority_rules WHERE rule_id=$1 AND tenant_id=$2",
                rule_id,
                tenant_id,
            )
        return _rowcount(result) > 0


def _rule_row(row: dict) -> dict:
    row = dict(row)
    row["source_precedence"] = _parse_json(row.get("source_precedence"))
    row["valid_from"] = _iso(row.get("valid_from"))
    row["valid_to"] = _iso(row.get("valid_to"))
    row["created_at"] = _iso(row.get("created_at"))
    return row


# ── §9.2 observation-equivalence keys ────────────────────────────────────────


class ObservationEquivalenceKeyRepository(_AuthorityRepo):
    """Durable §9.2 observation-equivalence keys (semantic, not transport)."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _KEY_STORE

    async def create(self, view: ObservationEquivalenceKeyView) -> dict:
        row = {
            **view.model_dump(mode="json"),
            "created_at": _now().isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            self._store[view.key_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO observation_equivalence_keys (key_id, domain, "
            "candidate_types, key_components, window, normalization_rules, "
            "semantic_dedupe_policy, tenant_id, environment_id) "
            "VALUES ($1,$2,$3::jsonb,$4::jsonb,$5,$6::jsonb,$7,$8,$9)",
            view.key_id,
            view.domain,
            _json.dumps(view.candidate_types),
            _json.dumps(view.key_components),
            view.window,
            _json.dumps(view.normalization_rules) if view.normalization_rules is not None else None,
            view.semantic_dedupe_policy,
            view.tenant_id,
            view.environment_id,
        )
        record = await pool.fetchrow(
            "SELECT * FROM observation_equivalence_keys WHERE key_id=$1",
            view.key_id,
        )
        return _key_row(dict(record)) if record is not None else dict(row)

    async def get(self, *, key_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
        """Scoped read with the same tenant-or-global / global-only semantics
        as :meth:`SourceAuthorityRuleRepository.get` (CP-11)."""
        pool = await self._ensure()
        if pool is None:
            stored = self._store.get(key_id)
            if stored is None or not _visible_tenancy(stored, tenant_id):
                return None
            return dict(stored)
        if tenant_id is None:
            record = await pool.fetchrow(
                "SELECT * FROM observation_equivalence_keys WHERE key_id=$1 AND tenant_id IS NULL",
                key_id,
            )
        else:
            record = await pool.fetchrow(
                "SELECT * FROM observation_equivalence_keys "
                "WHERE key_id=$1 AND (tenant_id=$2 OR tenant_id IS NULL)",
                key_id,
                tenant_id,
            )
        return _key_row(dict(record)) if record is not None else None

    async def list(
        self,
        *,
        domain: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        """List equivalence keys, CP-11 scoped (tenant-or-global reads).

        Ordering is deterministic and SQL-parity: ``created_at DESC`` then
        ``key_id ASC`` (ties on an equal timestamp fall back to key_id).
        """
        pool = await self._ensure()
        if pool is None:
            rows = [
                dict(r)
                for r in self._store.values()
                if (domain is None or r.get("domain") == domain) and _visible_tenancy(r, tenant_id)
            ]
            rows.sort(key=lambda r: r.get("key_id") or "")
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return rows
        where: list[str] = []
        args: list[Any] = []
        if domain is not None:
            args.append(domain)
            where.append(f"domain = ${len(args)}")
        if tenant_id is None:
            where.append("tenant_id IS NULL")
        else:
            args.append(tenant_id)
            where.append(f"(tenant_id = ${len(args)} OR tenant_id IS NULL)")
        records = await pool.fetch(
            "SELECT * FROM observation_equivalence_keys "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC, key_id ASC",
            *args,
        )
        return [_key_row(dict(r)) for r in records]

    async def delete(self, *, key_id: str, tenant_id: Optional[str] = None) -> bool:
        """Hard-delete a stale equivalence key, CP-11 scoped (same visibility
        rules as :meth:`SourceAuthorityRuleRepository.delete`)."""
        pool = await self._ensure()
        if pool is None:
            stored = self._store.get(key_id)
            if stored is None or not _owned_tenancy(stored, tenant_id):
                return False
            del self._store[key_id]
            return True
        if tenant_id is None:
            result = await pool.execute(
                "DELETE FROM observation_equivalence_keys WHERE key_id=$1 AND tenant_id IS NULL",
                key_id,
            )
        else:
            result = await pool.execute(
                "DELETE FROM observation_equivalence_keys WHERE key_id=$1 AND tenant_id=$2",
                key_id,
                tenant_id,
            )
        return _rowcount(result) > 0


def _key_row(row: dict) -> dict:
    row = dict(row)
    row["candidate_types"] = _parse_json(row.get("candidate_types"))
    row["key_components"] = _parse_json(row.get("key_components"))
    normalization = _parse_json(row.get("normalization_rules"))
    row["normalization_rules"] = normalization or None
    row["created_at"] = _iso(row.get("created_at"))
    return row


# ── module singletons ────────────────────────────────────────────────────────

_rule_repo: Optional[SourceAuthorityRuleRepository] = None
_key_repo: Optional[ObservationEquivalenceKeyRepository] = None


def get_source_authority_rule_repository() -> SourceAuthorityRuleRepository:
    global _rule_repo
    if _rule_repo is None:
        _rule_repo = SourceAuthorityRuleRepository()
    return _rule_repo


def get_observation_equivalence_key_repository() -> ObservationEquivalenceKeyRepository:
    global _key_repo
    if _key_repo is None:
        _key_repo = ObservationEquivalenceKeyRepository()
    return _key_repo
