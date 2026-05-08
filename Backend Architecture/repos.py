"""
Aether Backend — Repository Pattern
Each service accesses data stores through repository classes that abstract
query logic from business logic. Includes connection pooling, prepared
statements, and write-ahead logging hooks.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Optional, TypeVar

from shared.cache.cache import TTL, CacheClient, CacheKey
from shared.common.common import NotFoundError, utc_now
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger

logger = get_logger("aether.repository")

T = TypeVar("T", bound=dict)


# ═══════════════════════════════════════════════════════════════════════════
# BASE REPOSITORY (TimescaleDB / relational)
# ═══════════════════════════════════════════════════════════════════════════

class BaseRepository(ABC):
    """
    Abstract base for relational repositories.
    Stub uses in-memory dicts. Replace with asyncpg + PgBouncer pool.
    """

    def __init__(self, table_name: str):
        self.table_name = table_name
        self._store: dict[str, dict] = {}
        # --- PRODUCTION ---
        # self._pool = asyncpg.create_pool(dsn=settings.timescaledb.dsn, ...)

    async def find_by_id(self, record_id: str) -> Optional[dict]:
        return self._store.get(record_id)

    async def find_by_id_or_fail(self, record_id: str) -> dict:
        record = await self.find_by_id(record_id)
        if record is None:
            raise NotFoundError(self.table_name)
        return record

    async def find_many(
        self,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        results = list(self._store.values())
        if filters:
            results = [
                r for r in results
                if all(r.get(k) == v for k, v in filters.items())
            ]
        return results[offset : offset + limit]

    async def count(self, filters: dict[str, Any] | None = None) -> int:
        if not filters:
            return len(self._store)
        return len([
            r for r in self._store.values()
            if all(r.get(k) == v for k, v in filters.items())
        ])

    async def insert(self, record_id: str, data: dict) -> dict:
        data["id"] = record_id
        data["created_at"] = utc_now().isoformat()
        data["updated_at"] = utc_now().isoformat()
        self._store[record_id] = data
        logger.info(f"INSERT {self.table_name} id={record_id}")
        return data

    async def update(self, record_id: str, data: dict) -> dict:
        existing = await self.find_by_id_or_fail(record_id)
        existing.update(data)
        existing["updated_at"] = utc_now().isoformat()
        logger.info(f"UPDATE {self.table_name} id={record_id}")
        return existing

    async def delete(self, record_id: str) -> bool:
        if record_id in self._store:
            del self._store[record_id]
            logger.info(f"DELETE {self.table_name} id={record_id}")
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════
# IDENTITY REPOSITORY (Neptune graph + TimescaleDB)
# ═══════════════════════════════════════════════════════════════════════════

class IdentityRepository:
    """Manages user profiles in both the graph and relational store."""

    def __init__(self, graph: GraphClient, cache: CacheClient):
        self.graph = graph
        self.cache = cache
        self._profiles = BaseRepository("profiles")

    async def get_profile(self, tenant_id: str, user_id: str) -> Optional[dict]:
        # Check cache first
        key = CacheKey.profile(tenant_id, user_id)
        cached = await self.cache.get_json(key)
        if cached:
            return cached

        # Fall back to DB
        profile = await self._profiles.find_by_id(user_id)
        if profile:
            await self.cache.set_json(key, profile, TTL.PROFILE)
        return profile

    async def upsert_profile(self, tenant_id: str, user_id: str, data: dict) -> dict:
        # Write to relational
        existing = await self._profiles.find_by_id(user_id)
        if existing:
            profile = await self._profiles.update(user_id, data)
        else:
            profile = await self._profiles.insert(user_id, {**data, "tenant_id": tenant_id})

        # Write to graph
        vertex = Vertex(
            vertex_type=VertexType.USER,
            vertex_id=user_id,
            properties={"tenant_id": tenant_id, **data},
        )
        await self.graph.upsert_vertex(vertex)

        # Invalidate cache
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

        # Merge fields (primary wins on conflicts)
        for key, value in secondary.items():
            if key not in primary or primary[key] is None:
                primary[key] = value

        await self._profiles.update(primary_id, primary)
        await self._profiles.delete(secondary_id)

        # Create RESOLVED_AS edge in graph
        edge = Edge(
            edge_type=EdgeType.RESOLVED_AS,
            from_vertex_id=secondary_id,
            to_vertex_id=primary_id,
            properties={"merged_at": utc_now().isoformat()},
        )
        await self.graph.add_edge(edge)

        # Invalidate caches
        await self.cache.delete(CacheKey.profile(tenant_id, primary_id))
        await self.cache.delete(CacheKey.profile(tenant_id, secondary_id))

        return primary


# ═══════════════════════════════════════════════════════════════════════════
# ANALYTICS REPOSITORY (TimescaleDB + Redis caching)
# ═══════════════════════════════════════════════════════════════════════════

class AnalyticsRepository:
    """Query engine for dashboards — uses TimescaleDB with Redis query caching."""

    def __init__(self, cache: CacheClient):
        self.cache = cache
        self._events = BaseRepository("events")
        self._sessions = BaseRepository("sessions")

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


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGN REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class CampaignRepository(BaseRepository):
    def __init__(self):
        super().__init__("campaigns")


# ═══════════════════════════════════════════════════════════════════════════
# CONSENT REPOSITORY (DynamoDB-backed)
# ═══════════════════════════════════════════════════════════════════════════

class ConsentRepository(BaseRepository):
    """
    Consent records and data subject requests.
    In production backed by DynamoDB for single-digit-ms reads.
    """
    def __init__(self):
        super().__init__("consent_records")

    async def get_consent(self, tenant_id: str, user_id: str) -> Optional[dict]:
        records = await self.find_many(
            filters={"tenant_id": tenant_id, "user_id": user_id}, limit=1
        )
        return records[0] if records else None


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN REPOSITORY (DynamoDB-backed)
# ═══════════════════════════════════════════════════════════════════════════

class AdminRepository(BaseRepository):
    """Tenant management, billing, API key records."""
    def __init__(self):
        super().__init__("tenants")


# ═══════════════════════════════════════════════════════════════════════════
# ACTOR REPOSITORY  (multi-actor journey v1)
# Polymorphic principal: human | agent | system. Humans link 1:1 to
# user_profiles via human_user_id — no identity duplication.
# ═══════════════════════════════════════════════════════════════════════════

class ActorRepository:
    """Resolve and persist actors. Backed by Postgres `actors` table in prod."""

    HUMAN, AGENT, SYSTEM = "human", "agent", "system"

    def __init__(self, graph: GraphClient, cache: CacheClient):
        self.graph = graph
        self.cache = cache
        self._actors = BaseRepository("actors")
        # identifier → actor_id index for O(1) get_or_create
        self._index: dict[str, str] = {}

    @staticmethod
    def _identity_key(kind: str, identifier: str) -> str:
        return f"{kind}:{identifier}"

    async def get_or_create(
        self,
        kind: str,
        identifier: str,
        *,
        tenant_id: str = "",
        org_id: str = "",
        display_name: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        """Idempotent. Dedupes by (kind, identifier)."""
        if kind not in (self.HUMAN, self.AGENT, self.SYSTEM):
            raise ValueError(f"Invalid actor kind: {kind}")

        idx_key = self._identity_key(kind, identifier)
        cache_key = f"actor:{idx_key}"

        cached = await self.cache.get_json(cache_key)
        if cached:
            return cached

        existing_id = self._index.get(idx_key)
        if existing_id:
            actor = await self._actors.find_by_id(existing_id)
            if actor:
                await self.cache.set_json(cache_key, actor, TTL.PROFILE)
                return actor

        actor_id = str(uuid.uuid4()) if "uuid" in globals() else identifier
        record = {
            "actor_id": actor_id,
            "kind": kind,
            "human_user_id":   identifier if kind == self.HUMAN  else None,
            "agent_worker_id": identifier if kind == self.AGENT  else None,
            "system_name":     identifier if kind == self.SYSTEM else None,
            "tenant_id": tenant_id,
            "org_id": org_id,
            "display_name": display_name or identifier,
            "metadata": metadata or {},
        }
        await self._actors.insert(actor_id, record)
        self._index[idx_key] = actor_id

        # Mirror to graph as Actor vertex; link humans to existing User vertex.
        from shared.graph.graph import Vertex as _V, Edge as _E  # local import for stub
        actor_vertex = _V(
            vertex_type="Actor",
            vertex_id=actor_id,
            properties={"kind": kind, "tenant_id": tenant_id, "display_name": display_name},
        )
        await self.graph.upsert_vertex(actor_vertex)
        if kind == self.HUMAN:
            await self.graph.add_edge(_E(
                edge_type="REPRESENTS",
                from_vertex_id=actor_id,
                to_vertex_id=identifier,  # User vertex id == user_id
            ))

        await self.cache.set_json(cache_key, record, TTL.PROFILE)
        return record

    async def find_by_id(self, actor_id: str) -> Optional[dict]:
        return await self._actors.find_by_id(actor_id)


# ═══════════════════════════════════════════════════════════════════════════
# DELEGATION REPOSITORY
# Persist delegation grants; verify actions are within an active grant's
# scope. Revocation is fast: set revoked_at + publish revocation event.
# ═══════════════════════════════════════════════════════════════════════════

class DelegationRepository:
    """Manage delegations between actors and check authorization at write time."""

    def __init__(self, cache: CacheClient):
        self.cache = cache
        self._grants = BaseRepository("delegations")

    async def grant(
        self,
        delegator_actor_id: str,
        delegatee_actor_id: str,
        scope: list[str],
        *,
        expires_at: Optional[str] = None,
        constraints: Optional[dict] = None,
    ) -> dict:
        if delegator_actor_id == delegatee_actor_id:
            raise ValueError("delegator and delegatee must differ")
        delegation_id = str(uuid.uuid4()) if "uuid" in globals() else f"d-{delegator_actor_id}-{delegatee_actor_id}"
        record = {
            "delegation_id": delegation_id,
            "delegator_actor_id": delegator_actor_id,
            "delegatee_actor_id": delegatee_actor_id,
            "scope": list(scope),
            "constraints": constraints or {},
            "issued_at": utc_now().isoformat(),
            "expires_at": expires_at,
            "revoked_at": None,
        }
        await self._grants.insert(delegation_id, record)
        await self._invalidate_actor_cache(delegatee_actor_id)
        return record

    async def revoke(self, delegation_id: str, reason: str = "") -> dict:
        grant = await self._grants.find_by_id_or_fail(delegation_id)
        grant["revoked_at"] = utc_now().isoformat()
        grant["revoked_reason"] = reason
        await self._grants.update(delegation_id, grant)
        await self._invalidate_actor_cache(grant["delegatee_actor_id"])
        return grant

    async def authorize(
        self,
        delegatee_actor_id: str,
        required_scope: list[str],
        *,
        now_iso: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Return the active grant authorizing `required_scope` for the delegatee,
        or None if no grant covers it. Cache hit path is O(1).
        """
        cache_key = f"deleg:{delegatee_actor_id}"
        grants = await self.cache.get_json(cache_key)
        if grants is None:
            grants = await self._grants.find_many(
                filters={"delegatee_actor_id": delegatee_actor_id},
                limit=200,
            )
            await self.cache.set_json(cache_key, grants, TTL.SHORT)

        now_iso = now_iso or utc_now().isoformat()
        required = set(required_scope)
        for g in grants:
            if g.get("revoked_at"):
                continue
            if g.get("expires_at") and g["expires_at"] < now_iso:
                continue
            if required.issubset(set(g.get("scope", []))):
                return g
        return None

    async def _invalidate_actor_cache(self, delegatee_actor_id: str) -> None:
        await self.cache.delete(f"deleg:{delegatee_actor_id}")


# ═══════════════════════════════════════════════════════════════════════════
# JOURNEY REPOSITORY
# Multi-session aggregate. Open/extend/close lifecycle. Cross-journey link
# via preceded_by_journey_id. Hot path uses Redis-cached "open journey" key.
# ═══════════════════════════════════════════════════════════════════════════

class JourneyRepository:
    """Persist journeys and journey↔session links; mirror structure to graph."""

    OPEN, CONVERTED, ABANDONED, CLOSED = "open", "converted", "abandoned", "closed"

    def __init__(self, graph: GraphClient, cache: CacheClient):
        self.graph = graph
        self.cache = cache
        self._journeys = BaseRepository("journeys")
        self._sessions = BaseRepository("journey_sessions")

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def open(
        self,
        actor_id: str,
        project_id: str,
        entry_event_id: str,
        entry_attribution: dict,
        started_at: str,
        *,
        beneficiary_actor_id: Optional[str] = None,
        preceded_by_journey_id: Optional[str] = None,
    ) -> dict:
        journey_id = str(uuid.uuid4()) if "uuid" in globals() else entry_event_id
        record = {
            "journey_id": journey_id,
            "actor_id": actor_id,
            "beneficiary_actor_id": beneficiary_actor_id,
            "project_id": project_id,
            "state": self.OPEN,
            "started_at": started_at,
            "ended_at": None,
            "entry_event_id": entry_event_id,
            "entry_attribution": entry_attribution,  # frozen, immutable
            "last_event_at": started_at,
            "session_count": 0,
            "event_count": 1,
            "conversion_event_id": None,
            "exit_reason": None,
            "preceded_by_journey_id": preceded_by_journey_id,
            "metadata": {},
        }
        await self._journeys.insert(journey_id, record)
        await self.cache.set_json(self._open_key(project_id, actor_id), record, TTL.LONG)

        from shared.graph.graph import Vertex as _V, Edge as _E
        await self.graph.upsert_vertex(_V(
            vertex_type="Journey",
            vertex_id=journey_id,
            properties={"project_id": project_id, "state": self.OPEN, "started_at": started_at},
        ))
        await self.graph.add_edge(_E(
            edge_type="HAS_JOURNEY",
            from_vertex_id=actor_id,
            to_vertex_id=journey_id,
        ))
        if preceded_by_journey_id:
            await self.graph.add_edge(_E(
                edge_type="PRECEDED_BY",
                from_vertex_id=journey_id,
                to_vertex_id=preceded_by_journey_id,
            ))
        return record

    async def extend(self, journey_id: str, event_ts: str, session_id: Optional[str] = None) -> dict:
        journey = await self._journeys.find_by_id_or_fail(journey_id)
        journey["last_event_at"] = event_ts
        journey["event_count"] = journey.get("event_count", 0) + 1
        await self._journeys.update(journey_id, journey)
        if session_id:
            await self.attach_session(journey_id, session_id)
        await self.cache.set_json(
            self._open_key(journey["project_id"], journey["actor_id"]),
            journey, TTL.LONG,
        )
        return journey

    async def close(
        self,
        journey_id: str,
        *,
        reason: str,
        ended_at: str,
        conversion_event_id: Optional[str] = None,
    ) -> dict:
        journey = await self._journeys.find_by_id_or_fail(journey_id)
        new_state = self.CONVERTED if reason == "conversion" else (
            self.ABANDONED if reason == "inactivity" else self.CLOSED
        )
        journey.update({
            "state": new_state,
            "ended_at": ended_at,
            "exit_reason": reason,
            "conversion_event_id": conversion_event_id,
        })
        await self._journeys.update(journey_id, journey)
        await self.cache.delete(self._open_key(journey["project_id"], journey["actor_id"]))
        return journey

    async def attach_session(self, journey_id: str, session_id: str) -> None:
        link_id = f"{journey_id}:{session_id}"
        existing = await self._sessions.find_by_id(link_id)
        if existing:
            return
        journey = await self._journeys.find_by_id_or_fail(journey_id)
        seq = journey.get("session_count", 0) + 1
        await self._sessions.insert(link_id, {
            "journey_id": journey_id,
            "session_id": session_id,
            "sequence": seq,
        })
        journey["session_count"] = seq
        await self._journeys.update(journey_id, journey)
        from shared.graph.graph import Edge as _E
        await self.graph.add_edge(_E(
            edge_type="CONTAINS_SESSION",
            from_vertex_id=journey_id,
            to_vertex_id=session_id,
            properties={"sequence": seq},
        ))

    # ── lookups ───────────────────────────────────────────────────────────

    async def find_open(self, project_id: str, actor_id: str) -> Optional[dict]:
        cached = await self.cache.get_json(self._open_key(project_id, actor_id))
        if cached:
            return cached
        results = await self._journeys.find_many(
            filters={"project_id": project_id, "actor_id": actor_id, "state": self.OPEN},
            limit=1,
        )
        if results:
            await self.cache.set_json(self._open_key(project_id, actor_id), results[0], TTL.LONG)
            return results[0]
        return None

    async def find_most_recent_closed(
        self, project_id: str, actor_id: str
    ) -> Optional[dict]:
        all_for_actor = await self._journeys.find_many(
            filters={"project_id": project_id, "actor_id": actor_id},
            limit=200,
        )
        closed = [j for j in all_for_actor if j.get("state") != self.OPEN]
        closed.sort(key=lambda j: j.get("ended_at") or "", reverse=True)
        return closed[0] if closed else None

    @staticmethod
    def _open_key(project_id: str, actor_id: str) -> str:
        return f"journey:{project_id}:{actor_id}:open"


# Lightweight uuid fallback so the module loads even without `uuid` in globals.
import uuid  # noqa: E402  (placed at end so existing code is unaffected)
