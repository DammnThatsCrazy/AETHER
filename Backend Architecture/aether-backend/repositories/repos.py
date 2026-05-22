"""
Aether Backend — Repository Pattern
Each service accesses data stores through repository classes that abstract
query logic from business logic.

Backend selection:
- AETHER_ENV=local → in-memory dicts (no database required)
- AETHER_ENV=staging/production → asyncpg PostgreSQL with connection pooling
  Set DATABASE_URL env var to the PostgreSQL connection string.
"""

from __future__ import annotations

import json
import os
from abc import ABC
from typing import Any, Optional, TypeVar

import asyncio
import re

from shared.common.common import NotFoundError, utc_now
from shared.cache.cache import CacheClient, CacheKey, TTL
from shared.graph.graph import GraphClient, Vertex, Edge, VertexType, EdgeType
from shared.logger.logger import get_logger

logger = get_logger("aether.repository")

T = TypeVar("T", bound=dict)

# Optional asyncpg import
try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    asyncpg = None  # type: ignore[assignment]
    ASYNCPG_AVAILABLE = False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "")


# Shared connection pool (singleton, guarded by lock to prevent race conditions)
_pool: Optional[Any] = None
_pool_lock = asyncio.Lock()

# Strict table name validation (alphanumeric + underscores only)
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


async def _init_connection(conn: Any) -> None:
    """Per-connection init: set PostgreSQL-side timeouts and application name."""
    await conn.execute("SET statement_timeout = '30s'")
    await conn.execute("SET idle_in_transaction_session_timeout = '60s'")
    await conn.execute("SET application_name = 'aether-backend'")


async def get_pool() -> Any:
    """Get or create the shared asyncpg connection pool (thread-safe)."""
    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        # Double-check after acquiring lock
        if _pool is not None:
            return _pool

        url = _database_url()
        if not url:
            if _is_local_env():
                return None
            raise RuntimeError(
                "DATABASE_URL not set. Required in non-local environments. "
                "Set AETHER_ENV=local for in-memory fallback."
            )
        if not ASYNCPG_AVAILABLE:
            if _is_local_env():
                logger.warning("asyncpg not installed — using in-memory repositories")
                return None
            raise RuntimeError("asyncpg required for production: pip install asyncpg>=0.29")

        from config.settings import settings as _settings
        db_cfg = _settings.timescaledb
        _pool = await asyncpg.create_pool(
            url,
            min_size=db_cfg.pool_min,
            max_size=db_cfg.pool_max,
            command_timeout=30,
            statement_cache_size=100,
            init=_init_connection,
        )
        logger.info(
            f"Database pool created (asyncpg, {url.split('@')[-1] if '@' in url else url}, "
            f"min={db_cfg.pool_min} max={db_cfg.pool_max})"
        )
        return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


# ═══════════════════════════════════════════════════════════════════════════
# BASE REPOSITORY — auto-selects PostgreSQL or in-memory
# ═══════════════════════════════════════════════════════════════════════════

# Shared in-memory backing stores keyed by table_name.
#
# Without this, each BaseRepository instance owns a private `_store`. Routes
# that hold module-level repo singletons (services/flows/routes.py,
# services/entities/routes.py, services/agent/user_agents.py, etc.) would
# write into their own copies, and Profile360Aggregator — which constructs
# its own repos — would never observe writes made through the canonical
# routes when AETHER_ENV=local (no Postgres). Sharing a dict per table makes
# the in-memory backend behave like a real database for cross-module reads.
_IN_MEMORY_STORES: dict[str, dict[str, dict]] = {}


def reset_in_memory_stores() -> None:
    """Test helper: drop every in-memory backing store.

    Production code uses Postgres; the in-memory backend is local/dev-only.
    Tests that need isolated state can call this from their fixtures.
    """
    _IN_MEMORY_STORES.clear()


def _matches_filters(row: dict, filters: dict) -> bool:
    """In-memory equivalent of the SQL find_many predicate.

    Most filter keys use straight equality (mirroring `data->>'key' = $n`).
    `tenant_id=None` (or `""`) is special-cased to match legacy unscoped
    rows where the column is NULL or empty — exactly mirroring the SQL
    branch's `(tenant_id IS NULL OR tenant_id = '')`. Without this, the
    Profile 360 aggregator's legacy pass would drop blank-tenant rows
    when running on the in-memory backend even though Postgres returns
    them, leaving the two backends inconsistent.
    """
    for key, value in filters.items():
        if key == "tenant_id" and value in (None, ""):
            actual = row.get("tenant_id")
            if actual not in (None, ""):
                return False
            continue
        if row.get(key) != value:
            return False
    return True


class BaseRepository(ABC):
    """
    Base for relational repositories.

    Production: asyncpg queries against PostgreSQL (auto-creates table).
    Local: in-memory dicts for development, shared across instances of the
    same table so route-level singletons and the Profile 360 aggregator
    observe one consistent view.
    """

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        # All instances of a given table share the same dict so writes by one
        # singleton are visible to another (see _IN_MEMORY_STORES docstring).
        self._store: dict[str, dict] = _IN_MEMORY_STORES.setdefault(table_name, {})
        self._pool: Optional[Any] = None
        self._table_ensured = False

    async def _ensure_pool(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        return self._pool

    async def _ensure_table(self) -> None:
        """Auto-create JSONB table if it doesn't exist."""
        if self._table_ensured:
            return
        pool = await self._ensure_pool()
        if pool is None:
            self._table_ensured = True
            return
        safe_name = self.table_name.replace("-", "_").replace(" ", "_")
        if not _TABLE_NAME_RE.match(safe_name):
            raise ValueError(f"Invalid table name: {safe_name!r} — must be alphanumeric/underscores only")
        await pool.execute(f"""
            CREATE TABLE IF NOT EXISTS {safe_name} (
                id TEXT PRIMARY KEY,
                data JSONB NOT NULL DEFAULT '{{}}',
                tenant_id TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await pool.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{safe_name}_tenant
            ON {safe_name} (tenant_id)
        """)
        self._table_ensured = True

    async def find_by_id(self, record_id: str) -> Optional[dict]:
        pool = await self._ensure_pool()
        if pool is None:
            return self._store.get(record_id)
        await self._ensure_table()
        row = await pool.fetchrow(
            f"SELECT data FROM {self.table_name} WHERE id = $1", record_id
        )
        if row is None:
            return None
        return json.loads(row["data"])

    async def find_by_id_or_fail(self, record_id: str) -> dict:
        record = await self.find_by_id(record_id)
        if record is None:
            raise NotFoundError(self.table_name)
        return record

    async def find_many(
        self,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[dict]:
        pool = await self._ensure_pool()
        if pool is None:
            # In-memory fallback
            results = list(self._store.values())
            if filters:
                results = [
                    r for r in results
                    if _matches_filters(r, filters)
                ]
            reverse = sort_order == "desc"
            results.sort(key=lambda r: r.get(sort_by, ""), reverse=reverse)
            return results[offset: offset + limit]

        await self._ensure_table()
        # Build JSONB filter conditions
        conditions = ["1=1"]
        params: list[Any] = []
        idx = 1
        if filters:
            for key, value in filters.items():
                # `tenant_id=None` / `""` is the canonical way to request
                # legacy unscoped rows — pre-multi-tenant data that was
                # inserted before the tenant column existed. Emit a literal
                # IS NULL OR = '' predicate so those rows remain reachable
                # for callers that need to merge them with current-tenant
                # results (e.g. Profile360Aggregator._scoped_find_many).
                if key == "tenant_id" and value in (None, ""):
                    conditions.append("(tenant_id IS NULL OR tenant_id = '')")
                    continue
                if key == "tenant_id":
                    conditions.append(f"tenant_id = ${idx}")
                else:
                    conditions.append(f"data->>'{key}' = ${idx}")
                params.append(str(value))
                idx += 1

        direction = "DESC" if sort_order == "desc" else "ASC"
        safe_sort = sort_by if sort_by in ("created_at", "updated_at") else "created_at"
        query = f"""
            SELECT data FROM {self.table_name}
            WHERE {' AND '.join(conditions)}
            ORDER BY {safe_sort} {direction}
            LIMIT ${idx} OFFSET ${idx + 1}
        """
        params.extend([limit, offset])
        rows = await pool.fetch(query, *params)
        return [json.loads(row["data"]) for row in rows]

    async def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        pool = await self._ensure_pool()
        if pool is None:
            if not filters:
                return len(self._store)
            return len([
                r for r in self._store.values()
                if _matches_filters(r, filters)
            ])

        await self._ensure_table()
        conditions = ["1=1"]
        params: list[Any] = []
        idx = 1
        if filters:
            for key, value in filters.items():
                # See find_many: tenant_id=None/'' matches legacy unscoped rows.
                if key == "tenant_id" and value in (None, ""):
                    conditions.append("(tenant_id IS NULL OR tenant_id = '')")
                    continue
                if key == "tenant_id":
                    conditions.append(f"tenant_id = ${idx}")
                else:
                    conditions.append(f"data->>'{key}' = ${idx}")
                params.append(str(value))
                idx += 1

        row = await pool.fetchrow(
            f"SELECT COUNT(*) as cnt FROM {self.table_name} WHERE {' AND '.join(conditions)}",
            *params,
        )
        return row["cnt"] if row else 0

    async def insert(self, record_id: str, data: dict) -> dict:
        now = utc_now().isoformat()
        data["id"] = record_id
        data["created_at"] = now
        data["updated_at"] = now

        pool = await self._ensure_pool()
        if pool is None:
            self._store[record_id] = data
            logger.info(f"INSERT {self.table_name} id={record_id} (in-memory)")
            return data

        await self._ensure_table()
        tenant_id = data.get("tenant_id", "")
        await pool.execute(
            f"""INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET data = $2::jsonb, updated_at = NOW()""",
            record_id, json.dumps(data, default=str), tenant_id,
        )
        logger.info(f"INSERT {self.table_name} id={record_id}")
        return data

    async def update(self, record_id: str, data: dict) -> dict:
        existing = await self.find_by_id_or_fail(record_id)
        existing.update(data)
        existing["updated_at"] = utc_now().isoformat()

        pool = await self._ensure_pool()
        if pool is None:
            self._store[record_id] = existing
            logger.info(f"UPDATE {self.table_name} id={record_id} (in-memory)")
            return existing

        await pool.execute(
            f"UPDATE {self.table_name} SET data = $1::jsonb, updated_at = NOW() WHERE id = $2",
            json.dumps(existing, default=str), record_id,
        )
        logger.info(f"UPDATE {self.table_name} id={record_id}")
        return existing

    async def delete(self, record_id: str) -> bool:
        pool = await self._ensure_pool()
        if pool is None:
            if record_id in self._store:
                del self._store[record_id]
                logger.info(f"DELETE {self.table_name} id={record_id} (in-memory)")
                return True
            return False

        result = await pool.execute(
            f"DELETE FROM {self.table_name} WHERE id = $1", record_id
        )
        deleted = result.endswith("1")
        if deleted:
            logger.info(f"DELETE {self.table_name} id={record_id}")
        return deleted

    async def delete_by_entity(self, entity_field: str, entity_id: str) -> int:
        """Delete all records where a JSONB field matches the given entity ID.

        Used by DSAR cascading deletion to remove all records for a user/entity
        across any table. Returns count of deleted records.

        Args:
            entity_field: JSONB field name (e.g., 'user_id', 'entity_id', 'owner_entity_id')
            entity_id: The entity value to match.

        Returns:
            Number of records deleted.
        """
        pool = await self._ensure_pool()
        if pool is None:
            # In-memory: filter and delete matching records
            to_delete = [
                k for k, v in self._store.items()
                if v.get(entity_field) == entity_id
            ]
            for k in to_delete:
                del self._store[k]
            if to_delete:
                logger.info(
                    f"DELETE {self.table_name} {entity_field}={entity_id} "
                    f"count={len(to_delete)} (in-memory)"
                )
            return len(to_delete)

        await self._ensure_table()
        result = await pool.execute(
            f"DELETE FROM {self.table_name} WHERE data->>'{entity_field}' = $1",
            entity_id,
        )
        # result is like "DELETE 5"
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            logger.info(
                f"DELETE {self.table_name} {entity_field}={entity_id} count={count}"
            )
        return count


# ═══════════════════════════════════════════════════════════════════════════
# IDENTITY REPOSITORY (Neptune graph + TimescaleDB)
# ═══════════════════════════════════════════════════════════════════════════

class IdentityRepository:
    """Manages user profiles in both the graph and relational store."""

    def __init__(self, graph: GraphClient, cache: CacheClient) -> None:
        self.graph = graph
        self.cache = cache
        self._profiles = _ProfileStore()

    async def get_profile(self, tenant_id: str, user_id: str) -> Optional[dict]:
        key = CacheKey.profile(tenant_id, user_id)
        cached = await self.cache.get_json(key)
        if cached:
            return cached

        profile = await self._profiles.find_by_id(user_id)
        if profile:
            await self.cache.set_json(key, profile, TTL.PROFILE)
        return profile

    async def upsert_profile(self, tenant_id: str, user_id: str, data: dict) -> dict:
        existing = await self._profiles.find_by_id(user_id)
        if existing:
            profile = await self._profiles.update(user_id, data)
        else:
            profile = await self._profiles.insert(
                user_id, {**data, "tenant_id": tenant_id}
            )

        vertex = Vertex(
            vertex_type=VertexType.USER,
            vertex_id=user_id,
            properties={"tenant_id": tenant_id, **data},
        )
        await self.graph.upsert_vertex(vertex)
        await self.cache.delete(CacheKey.profile(tenant_id, user_id))
        return profile

    async def merge_identities(
        self,
        tenant_id: str,
        primary_id: str,
        secondary_id: str,
    ) -> dict:
        """Merge two user profiles into one (identity resolution)."""
        primary = await self._profiles.find_by_id_or_fail(primary_id)
        secondary = await self._profiles.find_by_id_or_fail(secondary_id)

        for key, value in secondary.items():
            if key not in primary or primary[key] is None:
                primary[key] = value

        await self._profiles.update(primary_id, primary)
        await self._profiles.delete(secondary_id)

        edge = Edge(
            edge_type=EdgeType.RESOLVED_AS,
            from_vertex_id=secondary_id,
            to_vertex_id=primary_id,
            properties={"merged_at": utc_now().isoformat()},
        )
        await self.graph.add_edge(edge)

        await self.cache.delete(CacheKey.profile(tenant_id, primary_id))
        await self.cache.delete(CacheKey.profile(tenant_id, secondary_id))
        return primary

    async def get_graph_neighbors(self, user_id: str) -> list[dict]:
        neighbors = await self.graph.get_neighbors(user_id, direction="out")
        return [
            {"id": v.vertex_id, "type": v.vertex_type, "properties": v.properties}
            for v in neighbors
        ]


# ═══════════════════════════════════════════════════════════════════════════
# ANALYTICS REPOSITORY (TimescaleDB + Redis caching)
# ═══════════════════════════════════════════════════════════════════════════

class AnalyticsRepository:
    """Query engine for dashboards — uses TimescaleDB with Redis query caching."""

    def __init__(self, cache: CacheClient) -> None:
        self.cache = cache
        self._events = _EventStore()
        self._sessions = _SessionStore()

    async def query_events(
        self,
        tenant_id: str,
        query_params: dict,
        limit: int = 100,
    ) -> list[dict]:
        # Cache key must include `limit` — without it, a /sessions?limit=1 call
        # would otherwise serve its 1-event result to /platforms, /protocols,
        # /devices, /rewards (all of which call with the same {user_id} filter
        # but larger limits), making the rollups undercount.
        cache_key = CacheKey.analytics_query(
            tenant_id, CacheKey.hash_query(f"{query_params}|limit={limit}")
        )
        cached = await self.cache.get_json(cache_key)
        if cached:
            return cached

        results = await self._events.find_many(
            filters={"tenant_id": tenant_id, **query_params},
            limit=limit,
        )
        await self.cache.set_json(cache_key, results, TTL.MEDIUM)
        return results

    async def record_event(self, event_id: str, data: dict) -> dict:
        return await self._events.insert(event_id, data)

    async def get_event(self, event_id: str) -> dict:
        return await self._events.find_by_id_or_fail(event_id)

    async def dashboard_summary(self, tenant_id: str) -> dict:
        events = await self._events.count(filters={"tenant_id": tenant_id})
        sessions = await self._sessions.count(filters={"tenant_id": tenant_id})
        return {
            "period": "24h",
            "total_events": events,
            "total_sessions": sessions,
            "unique_users": 0,
            "top_event_types": [],
        }


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGN REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class CampaignRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("campaigns")


# ═══════════════════════════════════════════════════════════════════════════
# CONSENT REPOSITORY (DynamoDB-backed)
# ═══════════════════════════════════════════════════════════════════════════

class ConsentRepository(BaseRepository):
    """
    Consent records and data subject requests.
    In production backed by DynamoDB for single-digit-ms reads.
    """
    def __init__(self) -> None:
        super().__init__("consent_records")

    async def get_consent(self, tenant_id: str, user_id: str) -> Optional[dict]:
        records = await self.find_many(
            filters={"tenant_id": tenant_id, "user_id": user_id}, limit=1
        )
        return records[0] if records else None


# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATION REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class WebhookRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("webhooks")


class AlertRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("alerts")


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN REPOSITORY (DynamoDB-backed)
# ═══════════════════════════════════════════════════════════════════════════

class AdminRepository(BaseRepository):
    """Tenant management, billing, API key records."""
    def __init__(self) -> None:
        super().__init__("tenants")


class APIKeyRepository(BaseRepository):
    """API key storage (hashed keys in production)."""
    def __init__(self) -> None:
        super().__init__("api_keys")


# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE CONCRETE STORES (used by composite repos above)
# ═══════════════════════════════════════════════════════════════════════════

class _ProfileStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("profiles")


class _EventStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("events")


class _SessionStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("sessions")


# ═══════════════════════════════════════════════════════════════════════════
# PROFILE 360 — MULTI-ENTITY / DELEGATION / FLOWS / BEHAVIOR (additive)
# ═══════════════════════════════════════════════════════════════════════════
#
# These repositories layer on top of the existing IdentityRepository without
# disturbing it. They use the same JSONB-backed BaseRepository pattern so they
# work in both the in-memory local mode and production PostgreSQL.
#
# Tables auto-created on first use:
#   entities              — humans, agents, organizations, system actors
#   identity_clusters     — multiple identifiers per entity
#   agent_configs         — user/org-owned LLM agents (config + ownership)
#   agent_executions      — execution log with reasoning / confidence
#   delegations           — scoped, time-bound, revocable permissions
#   wallets               — owned wallets per entity
#   assets                — token / nft / fiat / credit catalog
#   transfers             — financial flows attributed to actor + agent + event
#   behavior_profiles     — derived: automation_ratio, decision_latency, etc.
#   journey_chains        — cross-journey memory links
# ═══════════════════════════════════════════════════════════════════════════


class EntityRepository(BaseRepository):
    """Multi-entity identity: humans, agents, organizations, system actors.

    Existing IdentityRepository profile rows continue to work unchanged. New
    code paths upsert here too; the entity_id is the canonical reference for
    delegation, flows, behavior, and the Profile 360 graph extensions.
    """

    VALID_TYPES = ("human", "agent", "organization", "system")

    def __init__(self) -> None:
        super().__init__("entities")

    async def create_entity(
        self,
        entity_id: str,
        tenant_id: str,
        entity_type: str,
        display_name: str = "",
        parent_entity_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        if entity_type not in self.VALID_TYPES:
            from shared.common.common import BadRequestError
            raise BadRequestError(
                f"Invalid entity_type: {entity_type}. Must be one of {self.VALID_TYPES}"
            )
        return await self.insert(entity_id, {
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "entity_type": entity_type,
            "display_name": display_name,
            "parent_entity_id": parent_entity_id,
            "metadata": metadata or {},
        })

    async def list_by_tenant(
        self, tenant_id: str, entity_type: Optional[str] = None, limit: int = 100,
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if entity_type:
            filters["entity_type"] = entity_type
        return await self.find_many(filters=filters, limit=limit)


class IdentityClusterRepository(BaseRepository):
    """Multiple identifiers (wallet, email, device, social, etc.) per entity."""

    def __init__(self) -> None:
        super().__init__("identity_clusters")

    async def link(
        self,
        cluster_id: str,
        entity_id: str,
        tenant_id: str,
        identifier_type: str,
        identifier_value: str,
        confidence: float = 1.0,
        provenance: Optional[dict] = None,
    ) -> dict:
        return await self.insert(cluster_id, {
            "cluster_id": cluster_id,
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
            "confidence": confidence,
            "linked_at": utc_now().isoformat(),
            "unlinked_at": None,
            "provenance": provenance or {},
        })

    async def unlink(self, cluster_id: str) -> Optional[dict]:
        record = await self.find_by_id(cluster_id)
        if record is None:
            return None
        record["unlinked_at"] = utc_now().isoformat()
        return await self.update(cluster_id, record)

    async def list_for_entity(self, entity_id: str) -> list[dict]:
        results = await self.find_many(
            filters={"entity_id": entity_id}, limit=500,
        )
        return [r for r in results if not r.get("unlinked_at")]


class AgentConfigRepository(BaseRepository):
    """Configuration for user/org-owned LLM agents (distinct from system workers)."""

    def __init__(self) -> None:
        super().__init__("agent_configs")

    async def register(
        self,
        agent_id: str,
        owner_entity_id: str,
        tenant_id: str,
        model: str,
        tools: Optional[list] = None,
        constraints: Optional[dict] = None,
        risk_tolerance: str = "medium",
    ) -> dict:
        return await self.insert(agent_id, {
            "agent_id": agent_id,
            "owner_entity_id": owner_entity_id,
            "tenant_id": tenant_id,
            "model": model,
            "tools": tools or [],
            "constraints": constraints or {},
            "risk_tolerance": risk_tolerance,
            "policy_version": 1,
        })

    async def list_for_owner(self, owner_entity_id: str) -> list[dict]:
        return await self.find_many(
            filters={"owner_entity_id": owner_entity_id}, limit=200,
        )


class AgentExecutionRepository(BaseRepository):
    """Per-execution log with reasoning, confidence, policy log."""

    def __init__(self) -> None:
        super().__init__("agent_executions")

    async def record(
        self,
        execution_id: str,
        agent_id: str,
        tenant_id: str,
        delegation_id: Optional[str],
        triggered_by_event_id: Optional[str],
        status: str,
        reasoning: str = "",
        confidence: float = 0.0,
        policy_log: Optional[dict] = None,
        input_snapshot: Optional[dict] = None,
        output: Optional[dict] = None,
        error: Optional[dict] = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
    ) -> dict:
        now = utc_now().isoformat()
        return await self.insert(execution_id, {
            "execution_id": execution_id,
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "delegation_id": delegation_id,
            "triggered_by_event_id": triggered_by_event_id,
            "status": status,
            "reasoning": reasoning,
            "confidence": confidence,
            "policy_log": policy_log or {},
            "input_snapshot": input_snapshot or {},
            "output": output,
            "error": error,
            "started_at": started_at or now,
            "ended_at": ended_at,
        })

    async def list_for_agent(self, agent_id: str, limit: int = 50) -> list[dict]:
        return await self.find_many(
            filters={"agent_id": agent_id}, limit=limit,
        )

    async def list_failed(self, tenant_id: str, limit: int = 50) -> list[dict]:
        results = await self.find_many(
            filters={"tenant_id": tenant_id, "status": "failed"}, limit=limit,
        )
        return results


class DelegationRepository(BaseRepository):
    """Scoped, time-bound, revocable entity-to-entity delegations.

    Hot-path lookup `active_for(grantee_entity_id)` is cached in Redis with a
    60-second TTL, invalidated on grant/revoke. The DelegationProjector worker
    mirrors active rows to Neptune as DELEGATES edges for graph traversal.
    """

    def __init__(self, cache: Optional[CacheClient] = None) -> None:
        super().__init__("delegations")
        self._cache = cache

    async def grant(
        self,
        delegation_id: str,
        tenant_id: str,
        grantor_entity_id: str,
        grantee_entity_id: str,
        scope: dict,
        starts_at: Optional[str] = None,
        ends_at: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        record = await self.insert(delegation_id, {
            "delegation_id": delegation_id,
            "tenant_id": tenant_id,
            "grantor_entity_id": grantor_entity_id,
            "grantee_entity_id": grantee_entity_id,
            "scope": scope,
            "starts_at": starts_at or utc_now().isoformat(),
            "ends_at": ends_at,
            "revoked_at": None,
            "revoked_by_entity_id": None,
            "metadata": metadata or {},
        })
        await self._invalidate_cache(grantee_entity_id)
        return record

    async def revoke(
        self, delegation_id: str, revoked_by_entity_id: str,
    ) -> Optional[dict]:
        record = await self.find_by_id(delegation_id)
        if record is None or record.get("revoked_at"):
            return record
        record["revoked_at"] = utc_now().isoformat()
        record["revoked_by_entity_id"] = revoked_by_entity_id
        updated = await self.update(delegation_id, record)
        await self._invalidate_cache(record["grantee_entity_id"])
        return updated

    async def active_for(self, grantee_entity_id: str) -> list[dict]:
        """Return every currently-active delegation for an entity.

        Cached for 60s; invalidated on grant/revoke. The caller iterates and
        applies scope checks; this repo does no policy interpretation.
        """
        cache_key = f"delegations:active:{grantee_entity_id}"
        if self._cache is not None:
            cached = await self._cache.get_json(cache_key)
            if cached is not None:
                return cached

        all_for_grantee = await self.find_many(
            filters={"grantee_entity_id": grantee_entity_id}, limit=200,
        )
        now_iso = utc_now().isoformat()
        active = [
            d for d in all_for_grantee
            if not d.get("revoked_at")
            and (d.get("starts_at") or "") <= now_iso
            and (not d.get("ends_at") or d["ends_at"] > now_iso)
        ]

        if self._cache is not None:
            await self._cache.set_json(cache_key, active, TTL.SHORT)
        return active

    async def _invalidate_cache(self, grantee_entity_id: str) -> None:
        if self._cache is not None:
            await self._cache.delete(f"delegations:active:{grantee_entity_id}")


class WalletRepository(BaseRepository):
    """Wallets owned by an entity (an entity may own many)."""

    def __init__(self) -> None:
        super().__init__("entity_wallets")

    async def link_wallet(
        self,
        wallet_id: str,
        owner_entity_id: str,
        tenant_id: str,
        chain: str,
        address: str,
    ) -> dict:
        return await self.insert(wallet_id, {
            "wallet_id": wallet_id,
            "owner_entity_id": owner_entity_id,
            "tenant_id": tenant_id,
            "chain": chain,
            "address": address,
            "linked_at": utc_now().isoformat(),
        })


class AssetRepository(BaseRepository):
    """Asset catalog: tokens, NFTs, fiat units, credits."""

    def __init__(self) -> None:
        super().__init__("assets")


class TransferRepository(BaseRepository):
    """Asset movements between entities, attributed to actor + agent + event."""

    def __init__(self) -> None:
        super().__init__("transfers")

    async def record_transfer(
        self,
        transfer_id: str,
        tenant_id: str,
        from_entity_id: str,
        to_entity_id: str,
        asset_id: str,
        amount: str,
        attributed_agent_id: Optional[str] = None,
        attributed_event_id: Optional[str] = None,
        delegation_id: Optional[str] = None,
        tx_hash: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        return await self.insert(transfer_id, {
            "transfer_id": transfer_id,
            "tenant_id": tenant_id,
            "from_entity_id": from_entity_id,
            "to_entity_id": to_entity_id,
            "asset_id": asset_id,
            "amount": str(amount),
            "occurred_at": utc_now().isoformat(),
            "attributed_agent_id": attributed_agent_id,
            "attributed_event_id": attributed_event_id,
            "delegation_id": delegation_id,
            "tx_hash": tx_hash,
            "metadata": metadata or {},
        })

    async def list_for_entity(
        self, entity_id: str, limit: int = 100,
    ) -> list[dict]:
        # Two queries because find_many takes equality filters only;
        # union is fine for our scale.
        as_from = await self.find_many(
            filters={"from_entity_id": entity_id}, limit=limit,
        )
        as_to = await self.find_many(
            filters={"to_entity_id": entity_id}, limit=limit,
        )
        seen: set[str] = set()
        merged: list[dict] = []
        for r in (*as_from, *as_to):
            tid = r.get("transfer_id") or r.get("id")
            if tid and tid not in seen:
                seen.add(tid)
                merged.append(r)
        merged.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
        return merged[:limit]


class BehaviorProfileRepository(BaseRepository):
    """Derived behavior snapshots: automation_ratio, decision_latency, etc.

    Recomputed by the BehaviorScorer / RiskScorer / IntentInferrer workers.
    Profile 360 endpoints read the latest snapshot per entity.
    """

    def __init__(self) -> None:
        super().__init__("behavior_profiles")

    async def upsert_snapshot(
        self,
        entity_id: str,
        tenant_id: str,
        window_start: str,
        window_end: str,
        automation_ratio: float = 0.0,
        decision_latency_ms: int = 0,
        top_patterns: Optional[list] = None,
        anomaly_flags: Optional[list] = None,
        risk_score: float = 0.0,
        predicted_next: Optional[dict] = None,
    ) -> dict:
        snapshot = {
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "window_start": window_start,
            "window_end": window_end,
            "automation_ratio": automation_ratio,
            "decision_latency_ms": decision_latency_ms,
            "top_patterns": top_patterns or [],
            "anomaly_flags": anomaly_flags or [],
            "risk_score": risk_score,
            "predicted_next": predicted_next or {},
            "computed_at": utc_now().isoformat(),
        }
        # One row per entity (latest snapshot wins). Use entity_id as key.
        existing = await self.find_by_id(entity_id)
        if existing:
            return await self.update(entity_id, snapshot)
        return await self.insert(entity_id, snapshot)


class JourneyChainRepository(BaseRepository):
    """Cross-journey memory: link multiple journeys for one entity over time."""

    def __init__(self) -> None:
        super().__init__("journey_chains")

    async def upsert_chain(
        self,
        chain_id: str,
        entity_id: str,
        tenant_id: str,
        first_journey_id: str,
        last_journey_id: str,
        journey_count: int,
        spans_started_at: str,
        spans_last_seen_at: str,
        historical_context: Optional[dict] = None,
    ) -> dict:
        record = {
            "chain_id": chain_id,
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "first_journey_id": first_journey_id,
            "last_journey_id": last_journey_id,
            "journey_count": journey_count,
            "spans_started_at": spans_started_at,
            "spans_last_seen_at": spans_last_seen_at,
            "historical_context": historical_context or {},
        }
        existing = await self.find_by_id(chain_id)
        if existing:
            return await self.update(chain_id, record)
        return await self.insert(chain_id, record)


# ═══════════════════════════════════════════════════════════════════════════
# ECONOMIC GRAPH LAYER — Agent economies and Profile360 telemetry (additive)
# ═══════════════════════════════════════════════════════════════════════════


class PaymentIntentRepository(BaseRepository):
    """Pre-execution economic decisions made by autonomous agents.

    PaymentIntent rows intentionally model more than successful payments: quote
    requests, retries, budget evaluation, abandonment, and compute/API purchase
    attempts all live here so the graph can trace intent -> quote -> evaluation
    -> authorization -> settlement -> execution -> outcome.
    """

    def __init__(self) -> None:
        super().__init__("payment_intents")

    async def record_intent(
        self,
        intent_id: str,
        tenant_id: str,
        agent_id: str,
        amount: str,
        currency: str,
        provider: str,
        protocol: str = "",
        endpoint: str = "",
        capability_requested: str = "",
        settlement_status: str = "pending",
        retry_count: int = 0,
        resource_id: Optional[str] = None,
        facilitator_id: Optional[str] = None,
        quote_id: Optional[str] = None,
        authorization_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        abandoned_reason: Optional[str] = None,
        metadata: Optional[dict] = None,
        occurred_at: Optional[str] = None,
    ) -> dict:
        return await self.insert(intent_id, {
            "intent_id": intent_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "amount": str(amount),
            "currency": currency,
            "provider": provider,
            "protocol": protocol,
            "endpoint": endpoint,
            "capability_requested": capability_requested,
            "settlement_status": settlement_status,
            "retry_count": retry_count,
            "resource_id": resource_id,
            "facilitator_id": facilitator_id,
            "quote_id": quote_id,
            "authorization_id": authorization_id,
            "execution_id": execution_id,
            "abandoned_reason": abandoned_reason,
            "occurred_at": occurred_at or utc_now().isoformat(),
            "metadata": metadata or {},
        })

    async def list_for_agent(self, agent_id: str, limit: int = 100) -> list[dict]:
        rows = await self.find_many(filters={"agent_id": agent_id}, limit=limit)
        rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
        return rows[:limit]


class SettlementEventRepository(BaseRepository):
    """Settlement attempts and terminal outcomes for PaymentIntent records."""

    def __init__(self) -> None:
        super().__init__("settlement_events")

    async def record_event(
        self,
        settlement_event_id: str,
        tenant_id: str,
        intent_id: str,
        agent_id: str,
        status: str,
        amount: str,
        currency: str,
        provider: str = "",
        protocol: str = "",
        facilitator_id: Optional[str] = None,
        retry_count: int = 0,
        failure_reason: Optional[str] = None,
        tx_hash: Optional[str] = None,
        metadata: Optional[dict] = None,
        occurred_at: Optional[str] = None,
    ) -> dict:
        return await self.insert(settlement_event_id, {
            "settlement_event_id": settlement_event_id,
            "tenant_id": tenant_id,
            "intent_id": intent_id,
            "agent_id": agent_id,
            "status": status,
            "amount": str(amount),
            "currency": currency,
            "provider": provider,
            "protocol": protocol,
            "facilitator_id": facilitator_id,
            "retry_count": retry_count,
            "failure_reason": failure_reason,
            "tx_hash": tx_hash,
            "occurred_at": occurred_at or utc_now().isoformat(),
            "metadata": metadata or {},
        })

    async def list_for_intent(self, intent_id: str, limit: int = 100) -> list[dict]:
        rows = await self.find_many(filters={"intent_id": intent_id}, limit=limit)
        rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
        return rows[:limit]

    async def list_for_agent(self, agent_id: str, limit: int = 100) -> list[dict]:
        rows = await self.find_many(filters={"agent_id": agent_id}, limit=limit)
        rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
        return rows[:limit]


class EconomicResourceRepository(BaseRepository):
    """Purchasable capabilities: inference, GPU compute, APIs, data, memory."""

    VALID_RESOURCE_TYPES = (
        "inference", "gpu_compute", "api_access", "dataset", "memory_retrieval",
        "execution_right", "orchestration_service", "agent_service",
    )

    def __init__(self) -> None:
        super().__init__("economic_resources")

    async def upsert_resource(
        self,
        resource_id: str,
        tenant_id: str,
        resource_type: str,
        provider: str,
        capability: str,
        protocol: str = "",
        endpoint: str = "",
        pricing: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        record = {
            "resource_id": resource_id,
            "tenant_id": tenant_id,
            "resource_type": resource_type,
            "provider": provider,
            "capability": capability,
            "protocol": protocol,
            "endpoint": endpoint,
            "pricing": pricing or {},
            "metadata": metadata or {},
            "updated_at": utc_now().isoformat(),
        }
        existing = await self.find_by_id(resource_id)
        if existing:
            return await self.update(resource_id, record)
        return await self.insert(resource_id, record)


class FacilitatorRepository(BaseRepository):
    """Payment facilitators, x402 facilitators, trust brokers, authorization rails."""

    def __init__(self) -> None:
        super().__init__("facilitators")

    async def upsert_facilitator(
        self,
        facilitator_id: str,
        tenant_id: str,
        name: str,
        facilitator_type: str,
        protocols: Optional[list] = None,
        trust_score: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> dict:
        record = {
            "facilitator_id": facilitator_id,
            "tenant_id": tenant_id,
            "name": name,
            "facilitator_type": facilitator_type,
            "protocols": protocols or [],
            "trust_score": trust_score,
            "metadata": metadata or {},
            "updated_at": utc_now().isoformat(),
        }
        existing = await self.find_by_id(facilitator_id)
        if existing:
            return await self.update(facilitator_id, record)
        return await self.insert(facilitator_id, record)


class AgentEconomicIdentityRepository(BaseRepository):
    """Derived long-running economic identity for an autonomous agent."""

    def __init__(self) -> None:
        super().__init__("agent_economic_identities")

    async def upsert_identity(
        self,
        agent_id: str,
        tenant_id: str,
        recurring_spend: Optional[dict] = None,
        provider_preferences: Optional[list] = None,
        capability_preferences: Optional[list] = None,
        execution_dependencies: Optional[list] = None,
        trust_relationships: Optional[list] = None,
        protocol_affinity: Optional[list] = None,
        pricing_tolerance: Optional[dict] = None,
        specialization_patterns: Optional[list] = None,
        failure_rates: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        record = {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "recurring_spend": recurring_spend or {},
            "provider_preferences": provider_preferences or [],
            "capability_preferences": capability_preferences or [],
            "execution_dependencies": execution_dependencies or [],
            "trust_relationships": trust_relationships or [],
            "protocol_affinity": protocol_affinity or [],
            "pricing_tolerance": pricing_tolerance or {},
            "specialization_patterns": specialization_patterns or [],
            "failure_rates": failure_rates or {},
            "metadata": metadata or {},
            "computed_at": utc_now().isoformat(),
        }
        existing = await self.find_by_id(agent_id)
        if existing:
            return await self.update(agent_id, record)
        return await self.insert(agent_id, record)


# ═══════════════════════════════════════════════════════════════════════════
# OPERATIONAL INTELLIGENCE REPOSITORIES
# ═══════════════════════════════════════════════════════════════════════════


class InvestigationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("investigations")

    async def create(self, case: dict) -> dict:
        return await self.insert(case["id"], case)

    async def list_by_tenant(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        return await self.find_many(filters=filters, limit=limit)


class GovernanceRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("governance_decisions")

    async def create(self, decision: dict) -> dict:
        return await self.insert(decision["id"], decision)

    async def list_by_tenant(
        self,
        tenant_id: str,
        principal_id: Optional[str] = None,
        allowed: Optional[bool] = None,
        limit: int = 50,
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if principal_id:
            filters["principal_id"] = principal_id
        results = await self.find_many(filters=filters, limit=limit * 2)
        if allowed is not None:
            results = [r for r in results if r.get("allowed") == allowed]
        return results[:limit]


class EventReplayRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("event_replay_jobs")

    async def create(self, job: dict) -> dict:
        return await self.insert(job["id"], job)

    async def list_by_tenant(self, tenant_id: str, limit: int = 50) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)

    async def list_queued(self, limit: int = 50) -> list[dict]:
        return await self.find_many(filters={"status": "queued"}, limit=limit)


class EventEnvelopeRepository(BaseRepository):
    """Durable store for ingested EventPipelineEnvelopes available for replay."""

    def __init__(self) -> None:
        super().__init__("event_envelopes")

    async def create(self, envelope: dict) -> dict:
        return await self.insert(envelope["id"], envelope)

    async def list_replayable(
        self,
        tenant_id: str,
        source_tag: str = "",
        event_types: Optional[list[str]] = None,
        from_time: str = "",
        to_time: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        results = await self.find_many(
            filters={"tenantId": tenant_id, "replayable": True}, limit=limit
        )
        if source_tag:
            results = [r for r in results if source_tag in (r.get("tags") or [])]
        if event_types:
            results = [r for r in results if r.get("type") in event_types]
        if from_time:
            results = [r for r in results if r.get("occurredAt", "") >= from_time]
        if to_time:
            results = [r for r in results if r.get("occurredAt", "") <= to_time]
        return results
