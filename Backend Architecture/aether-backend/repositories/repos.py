"""Aether Backend — Repository Pattern with durable SQLite storage."""

from __future__ import annotations

import json
import os
import sqlite3
from abc import ABC
from pathlib import Path
from typing import Any, Optional, TypeVar

from shared.common.common import NotFoundError, utc_now
from shared.cache.cache import CacheClient, CacheKey, TTL
from shared.graph.graph import GraphClient, Vertex, Edge, VertexType, EdgeType
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger

logger = get_logger("aether.repository")
T = TypeVar("T", bound=dict)


def _state_dir(component: str) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    path = base / "aether" / component
    path.mkdir(parents=True, exist_ok=True)
    return path


def _repository_db_path() -> Path:
    explicit = os.environ.get("AETHER_REPOSITORY_DB_PATH")
    env = os.environ.get("AETHER_ENV", "local").lower()
    if explicit:
        path = Path(explicit)
    elif env == "local":
        path = _state_dir("repositories") / "repositories.sqlite3"
    else:
        raise RuntimeError(
            "AETHER_REPOSITORY_DB_PATH must be set in non-local environments to enable durable repository storage."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class _RepositoryMirror(dict):
    def __init__(self, repo: "BaseRepository"):
        super().__init__()
        self._repo = repo

    def clear(self) -> None:
        super().clear()
        self._repo._clear_db()


class BaseRepository(ABC):
    """Durable SQLite-backed repository used by service-level repositories."""

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        self._db_path = _repository_db_path()
        self._store = _RepositoryMirror(self)
        self._init_db()
        self._load_store()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table_name} (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )

    def _load_store(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(f"SELECT id, payload FROM {self.table_name}").fetchall()
        for row in rows:
            self._store[row["id"]] = json.loads(row["payload"])

    def _clear_db(self) -> None:
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.table_name}")

    async def find_by_id(self, record_id: str) -> Optional[dict]:
        return self._store.get(record_id)

    async def find_by_id_or_fail(self, record_id: str) -> dict:
        record = await self.find_by_id(record_id)
        if record is None:
            raise NotFoundError(self.table_name)
        return record

    async def find_many(self, filters: Optional[dict[str, Any]] = None, limit: int = 50, offset: int = 0, sort_by: str = "created_at", sort_order: str = "desc") -> list[dict]:
        results = list(self._store.values())
        if filters:
            results = [r for r in results if all(r.get(k) == v for k, v in filters.items())]
        reverse = sort_order == "desc"
        results.sort(key=lambda r: r.get(sort_by, ""), reverse=reverse)
        return results[offset: offset + limit]

    async def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        return len(await self.find_many(filters=filters, limit=10_000_000, offset=0, sort_by="created_at", sort_order="desc"))

    async def insert(self, record_id: str, data: dict) -> dict:
        now = utc_now().isoformat()
        record = {**data, "id": record_id, "created_at": now, "updated_at": now}
        self._store[record_id] = record
        with self._connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {self.table_name}(id, payload, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (record_id, json.dumps(record, default=str), now, now),
            )
        return record

    async def update(self, record_id: str, data: dict) -> dict:
        existing = await self.find_by_id_or_fail(record_id)
        existing.update(data)
        existing["updated_at"] = utc_now().isoformat()
        self._store[record_id] = existing
        with self._connect() as conn:
            conn.execute(
                f"UPDATE {self.table_name} SET payload = ?, updated_at = ? WHERE id = ?",
                (json.dumps(existing, default=str), existing["updated_at"], record_id),
            )
        return existing

    async def delete(self, record_id: str) -> bool:
        existed = record_id in self._store
        self._store.pop(record_id, None)
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.table_name} WHERE id = ?", (record_id,))
        return existed


class IdentityRepository:
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
        profile = await (self._profiles.update(user_id, data) if existing else self._profiles.insert(user_id, {**data, "tenant_id": tenant_id}))
        vertex = Vertex(vertex_type=VertexType.USER, vertex_id=user_id, properties={"tenant_id": tenant_id, **data})
        await self.graph.upsert_vertex(vertex)
        await self.cache.delete(CacheKey.profile(tenant_id, user_id))
        return profile

    async def merge_identities(self, tenant_id: str, primary_id: str, secondary_id: str) -> dict:
        primary = await self._profiles.find_by_id_or_fail(primary_id)
        secondary = await self._profiles.find_by_id_or_fail(secondary_id)
        for key, value in secondary.items():
            if key not in primary or primary[key] is None:
                primary[key] = value
        await self._profiles.update(primary_id, primary)
        await self._profiles.delete(secondary_id)
        edge = Edge(edge_type=EdgeType.RESOLVED_AS, from_vertex_id=secondary_id, to_vertex_id=primary_id, properties={"merged_at": utc_now().isoformat()})
        await self.graph.add_edge(edge)
        await self.cache.delete(CacheKey.profile(tenant_id, primary_id))
        await self.cache.delete(CacheKey.profile(tenant_id, secondary_id))
        return primary

    async def get_graph_neighbors(self, user_id: str) -> list[dict]:
        neighbors = await self.graph.get_neighbors(user_id, direction="out")
        return [{"id": v.vertex_id, "type": v.vertex_type, "properties": v.properties} for v in neighbors]


class AnalyticsRepository:
    def __init__(self, cache: CacheClient) -> None:
        self.cache = cache
        self._events = _EventStore()
        self._sessions = _SessionStore()

    async def query_events(self, tenant_id: str, query_params: dict, limit: int = 100) -> list[dict]:
        cache_key = CacheKey.analytics_query(tenant_id, CacheKey.hash_query(str(query_params)))
        cached = await self.cache.get_json(cache_key)
        if cached:
            return cached
        results = await self._events.find_many(filters={"tenant_id": tenant_id, **query_params}, limit=limit)
        await self.cache.set_json(cache_key, results, TTL.MEDIUM)
        return results

    async def record_event(self, event_id: str, data: dict) -> dict:
        return await self._events.insert(event_id, data)

    async def get_event(self, event_id: str) -> dict:
        return await self._events.find_by_id_or_fail(event_id)

    async def dashboard_summary(self, tenant_id: str) -> dict:
        events = await self._events.count(filters={"tenant_id": tenant_id})
        sessions = await self._sessions.count(filters={"tenant_id": tenant_id})
        return {"period": "24h", "total_events": events, "total_sessions": sessions, "unique_users": 0, "top_event_types": []}


class CampaignRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("campaigns")


class ConsentRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("consent_records")

    async def get_consent(self, tenant_id: str, user_id: str) -> Optional[dict]:
        records = await self.find_many(filters={"tenant_id": tenant_id, "user_id": user_id}, limit=1)
        return records[0] if records else None


class WebhookRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("webhooks")


class AlertRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("alerts")


class AdminRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("tenants")


class APIKeyRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("api_keys")


class _ProfileStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("profiles")


class _EventStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("events")


class _SessionStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("sessions")
