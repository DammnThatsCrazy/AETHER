"""
Responsiveness repository.

Single-tenant snapshot tables. All state is stored as flat dicts in the shared
BaseRepository pattern (id + tenant_id + created_at + updated_at + payload
fields inline), so the in-memory backend and any future PostgreSQL migration
behave the same way. Each scope has its own record-id scheme so the same
BaseRepository instance can hold all responsiveness tables without collision.

Local in-memory keys (table names):
  * responsiveness_activation_milestones       key = tenant_id
  * responsiveness_heartbeat_state             key = tenant_id:source_id
  * responsiveness_provider_sync_state         key = tenant_id:provider_id
  * responsiveness_graph_hydration_state       key = tenant_id:graph_version
  * responsiveness_projection_state            key = tenant_id:projection_id
  * responsiveness_lens_projection_state       key = tenant_id:lens_id:graph_version:scope_hash
  * responsiveness_timeline_projection_state   key = tenant_id:timeline:scope_hash
  * responsiveness_query_execution_state       key = tenant_id:query:query_id
  * responsiveness_background_jobs             key = tenant_id:job:job_id
  * responsiveness_surface_readiness           key = tenant_id:surface:surface
  * responsiveness_measurements                key = tenant_id:measurement:id
  * responsiveness_performance_budgets         key = budget id
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResponsivenessRepository(BaseRepository):
    """Single-tenant responsiveness state, stored as flat BaseRepository rows."""

    def __init__(self) -> None:
        # One BaseRepository instance backs every responsiveness table; the
        # table_name is constant because BaseRepository stores by record id,
        # not by table. We never read/write across scopes by accident because
        # each method owns its own key scheme.
        super().__init__("responsiveness_state")

    # ── helpers ──────────────────────────────────────────────────────────

    async def _get(self, record_id: str) -> Optional[dict]:
        row = await self.find_by_id(record_id)
        if row is None:
            return None
        # strip the repo-injected metadata keys; the rest is the model payload
        return {
            k: v for k, v in row.items()
            if k not in ("id", "created_at", "updated_at", "tenant_id")
        }

    async def _put(
        self,
        record_id: str,
        tenant_id: str,
        payload: dict,
        *,
        already_exists: Optional[dict] = None,
    ) -> dict:
        now = _now()
        payload["tenant_id"] = tenant_id
        payload["updated_at"] = now
        if already_exists is not None:
            existing = dict(already_exists)
            # preserve created_at when present
            if existing.get("created_at"):
                payload.setdefault("created_at", existing["created_at"])
            # merge: caller's payload wins on conflict (latest write wins)
            merged = {**existing, **payload}
            merged["updated_at"] = now
            await self.update(record_id, merged)
            return merged
        record: dict[str, Any] = {
            "id": record_id,
            "tenant_id": tenant_id,
            "created_at": now,
            "updated_at": now,
            **payload,
        }
        await self.insert(record_id, record)
        return record

    # ── activation milestones ────────────────────────────────────────────

    async def get_activation_milestone(self, tenant_id: str) -> Optional[dict]:
        return await self._get(tenant_id)

    async def put_activation_milestone(self, tenant_id: str, payload: dict) -> dict:
        existing = await self.find_by_id(tenant_id)
        return await self._put(tenant_id, tenant_id, payload, already_exists=existing)

    # ── heartbeat state ──────────────────────────────────────────────────

    @staticmethod
    def heartbeat_record_id(tenant_id: str, source_id: str) -> str:
        return f"{tenant_id}:heartbeat:{source_id}"

    async def get_heartbeat_state(self, tenant_id: str, source_id: str) -> Optional[dict]:
        return await self._get(self.heartbeat_record_id(tenant_id, source_id))

    async def put_heartbeat_state(
        self, tenant_id: str, source_id: str, payload: dict
    ) -> dict:
        rid = self.heartbeat_record_id(tenant_id, source_id)
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    async def list_heartbeat_states(self, tenant_id: str) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id})
        out: list[dict] = []
        for r in rows:
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out

    # ── provider sync state ──────────────────────────────────────────────

    @staticmethod
    def provider_sync_record_id(tenant_id: str, provider_id: str) -> str:
        return f"{tenant_id}:provider_sync:{provider_id}"

    async def get_provider_sync_state(
        self, tenant_id: str, provider_id: str
    ) -> Optional[dict]:
        return await self._get(self.provider_sync_record_id(tenant_id, provider_id))

    async def put_provider_sync_state(
        self, tenant_id: str, provider_id: str, payload: dict
    ) -> dict:
        rid = self.provider_sync_record_id(tenant_id, provider_id)
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    async def list_provider_sync_states(self, tenant_id: str) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id})
        out: list[dict] = []
        for r in rows:
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out

    # ── graph hydration state ────────────────────────────────────────────

    @staticmethod
    def graph_hydration_record_id(tenant_id: str, graph_version: str) -> str:
        return f"{tenant_id}:graph_hydration:{graph_version}"

    async def get_graph_hydration_state(
        self, tenant_id: str, graph_version: str
    ) -> Optional[dict]:
        return await self._get(self.graph_hydration_record_id(tenant_id, graph_version))

    async def put_graph_hydration_state(
        self, tenant_id: str, graph_version: str, payload: dict
    ) -> dict:
        rid = self.graph_hydration_record_id(tenant_id, graph_version)
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    # ── projection state ─────────────────────────────────────────────────

    @staticmethod
    def projection_record_id(tenant_id: str, projection_id: str) -> str:
        return f"{tenant_id}:projection:{projection_id}"

    async def get_projection_state(
        self, tenant_id: str, projection_id: str
    ) -> Optional[dict]:
        return await self._get(self.projection_record_id(tenant_id, projection_id))

    async def put_projection_state(
        self, tenant_id: str, projection_id: str, payload: dict
    ) -> dict:
        rid = self.projection_record_id(tenant_id, projection_id)
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    async def list_projection_states(self, tenant_id: str) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id})
        out: list[dict] = []
        for r in rows:
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out

    # ── lens projection state ────────────────────────────────────────────

    @staticmethod
    def lens_projection_record_id(
        tenant_id: str, lens_id: str, graph_version: str, scope_hash: str
    ) -> str:
        return f"{tenant_id}:lens_projection:{lens_id}:{graph_version}:{scope_hash}"

    async def get_lens_projection_state(
        self,
        tenant_id: str,
        lens_id: str,
        graph_version: str,
        scope_hash: str,
    ) -> Optional[dict]:
        return await self._get(
            self.lens_projection_record_id(tenant_id, lens_id, graph_version, scope_hash)
        )

    async def put_lens_projection_state(
        self,
        tenant_id: str,
        lens_id: str,
        graph_version: str,
        scope_hash: str,
        payload: dict,
    ) -> dict:
        rid = self.lens_projection_record_id(tenant_id, lens_id, graph_version, scope_hash)
        existing = await self.find_by_id(rid)
        payload["lens_id"] = lens_id
        payload["graph_version"] = graph_version
        payload["scope_hash"] = scope_hash
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    async def list_lens_projection_states(self, tenant_id: str) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id})
        out: list[dict] = []
        for r in rows:
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out

    # ── timeline projection state ────────────────────────────────────────

    @staticmethod
    def timeline_projection_record_id(tenant_id: str, scope_hash: str) -> str:
        return f"{tenant_id}:timeline_projection:{scope_hash}"

    async def get_timeline_projection_state(
        self, tenant_id: str, scope_hash: str
    ) -> Optional[dict]:
        return await self._get(self.timeline_projection_record_id(tenant_id, scope_hash))

    async def put_timeline_projection_state(
        self, tenant_id: str, scope_hash: str, payload: dict
    ) -> dict:
        rid = self.timeline_projection_record_id(tenant_id, scope_hash)
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    # ── query execution state ────────────────────────────────────────────

    @staticmethod
    def query_execution_record_id(tenant_id: str, query_id: str) -> str:
        return f"{tenant_id}:query_execution:{query_id}"

    async def get_query_execution_state(
        self, tenant_id: str, query_id: str
    ) -> Optional[dict]:
        return await self._get(self.query_execution_record_id(tenant_id, query_id))

    async def put_query_execution_state(
        self, tenant_id: str, query_id: str, payload: dict
    ) -> dict:
        rid = self.query_execution_record_id(tenant_id, query_id)
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    # ── background jobs ──────────────────────────────────────────────────

    @staticmethod
    def background_job_record_id(tenant_id: str, job_id: str) -> str:
        return f"{tenant_id}:background_job:{job_id}"

    async def get_background_job(self, tenant_id: str, job_id: str) -> Optional[dict]:
        return await self._get(self.background_job_record_id(tenant_id, job_id))

    async def put_background_job(
        self, tenant_id: str, job_id: str, payload: dict
    ) -> dict:
        rid = self.background_job_record_id(tenant_id, job_id)
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    async def list_background_jobs(self, tenant_id: str) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id})
        out: list[dict] = []
        for r in rows:
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out

    # ── surface readiness ────────────────────────────────────────────────

    @staticmethod
    def surface_readiness_record_id(tenant_id: str, surface: str) -> str:
        return f"{tenant_id}:surface_readiness:{surface}"

    async def get_surface_readiness(
        self, tenant_id: str, surface: str
    ) -> Optional[dict]:
        return await self._get(self.surface_readiness_record_id(tenant_id, surface))

    async def put_surface_readiness(
        self, tenant_id: str, surface: str, payload: dict
    ) -> dict:
        rid = self.surface_readiness_record_id(tenant_id, surface)
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    async def list_surface_readiness(self, tenant_id: str) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id})
        out: list[dict] = []
        for r in rows:
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out

    # ── responsiveness measurements ──────────────────────────────────────

    @staticmethod
    def measurement_record_id(tenant_id: str, measurement_id: str) -> str:
        return f"{tenant_id}:measurement:{measurement_id}"

    async def put_measurement(
        self, tenant_id: str, measurement_id: str, payload: dict
    ) -> dict:
        rid = self.measurement_record_id(tenant_id, measurement_id)
        payload.setdefault("measured_at", _now())
        existing = await self.find_by_id(rid)
        return await self._put(rid, tenant_id, payload, already_exists=existing)

    async def list_measurements(
        self, tenant_id: str, limit: int = 200
    ) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)
        out: list[dict] = []
        for r in rows:
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out

    # ── performance budgets ──────────────────────────────────────────────

    async def get_performance_budgets(self) -> list[dict]:
        rows = await self.find_many(limit=500)
        out: list[dict] = []
        for r in rows:
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out

    async def put_performance_budgets(self, budgets: list[dict]) -> list[dict]:
        out: list[dict] = []
        for b in budgets:
            rid = b.get("id")
            if not rid:
                continue
            b["updated_at"] = _now()
            existing = await self.find_by_id(rid)
            out.append(await self._put(rid, b.get("tenant_id", ""), b, already_exists=existing))
        return out


    async def list_timeline_projection_states_for_tenant(self, tenant_id: str) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id})
        out: list[dict] = []
        for r in rows:
            if not r.get("id", "").startswith(f"{tenant_id}:timeline_projection:"):
                continue
            model = {
                k: v for k, v in r.items()
                if k not in ("id", "created_at", "updated_at", "tenant_id")
            }
            if model:
                out.append(model)
        return out
