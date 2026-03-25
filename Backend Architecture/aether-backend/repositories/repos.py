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
from dataclasses import dataclass, field
from typing import Any, Optional, TypeVar

from shared.common.common import NotFoundError, utc_now
from shared.cache.cache import CacheClient, CacheKey, TTL
from shared.graph.graph import GraphClient, Vertex, Edge, VertexType, EdgeType
from shared.events.events import Event, EventProducer, Topic
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


# Shared connection pool (singleton)
_pool: Optional[Any] = None


async def get_pool() -> Any:
    """Get or create the shared asyncpg connection pool."""
    global _pool
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

    _pool = await asyncpg.create_pool(
        url, min_size=2, max_size=20,
        command_timeout=30, statement_cache_size=100,
    )
    logger.info(f"Database pool created (asyncpg, {url.split('@')[-1] if '@' in url else url})")
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

class BaseRepository(ABC):
    """
    Base for relational repositories.

    Production: asyncpg queries against PostgreSQL (auto-creates table).
    Local: in-memory dicts for development.
    """

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        self._store: dict[str, dict] = {}  # in-memory fallback
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
                    if all(r.get(k) == v for k, v in filters.items())
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
                if all(r.get(k) == v for k, v in filters.items())
            ])

        await self._ensure_table()
        conditions = ["1=1"]
        params: list[Any] = []
        idx = 1
        if filters:
            for key, value in filters.items():
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
        cache_key = CacheKey.analytics_query(
            tenant_id, CacheKey.hash_query(str(query_params))
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
