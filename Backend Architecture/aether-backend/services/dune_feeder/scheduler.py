"""
Aether Service — Dune Analytics Scheduled Polling Worker

Asyncio background worker that periodically polls the Dune Analytics API for
configured query schedules and feeds results through the governed Bronze ingest
pipeline (freshness gate → quality gate → Bronze land).

Design constraints (same as DuneFeederService):
- No graph/Neptune imports or writes.
- Silver/Gold promotion remains explicit operator actions.
- Graph state is NEVER touched here.
- All polling is credential-gated: requires DUNE_API_KEY env var or per-schedule
  vault reference; skips with status="skipped" when neither is available.
- Live API calls are gated by AETHER_ENV != "local"; in local mode the worker
  logs intent but never calls the external Dune API.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from shared.logger.logger import get_logger, metrics

from services.dune_feeder.models import (
    DuneQueryResult,
    FeederIngestRequest,
    ScheduleCreateRequest,
    ScheduledQueryConfig,
    ScheduleRunSummary,
)

logger = get_logger("aether.service.dune_feeder.scheduler")

_TICK_INTERVAL_SECONDS = 60
_DUNE_RESULTS_URL = "https://api.dune.com/api/v1/query/{query_id}/results"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_live() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() != "local"


# ── Schedule store ────────────────────────────────────────────────────────────

class ScheduledQueryStore:
    """Persistence layer for ScheduledQueryConfig records."""

    def __init__(self) -> None:
        from repositories.repos import BaseRepository
        self._repo = BaseRepository("dune_scheduled_queries")

    async def create(self, req: ScheduleCreateRequest, tenant_scope: Optional[str]) -> ScheduledQueryConfig:
        config = ScheduledQueryConfig(
            schedule_id=str(uuid.uuid4()),
            tenant_scope=tenant_scope,
            query_id=req.query_id,
            query_name=req.query_name,
            source_tag=req.source_tag,
            domain=req.domain,
            interval_seconds=req.interval_seconds,
            max_age_seconds=req.max_age_seconds,
            quality_threshold=req.quality_threshold,
            schema=req.schema,
            required_fields=req.required_fields,
            api_key_ref=req.api_key_ref,
            enabled=req.enabled,
            created_at=_utc_now_iso(),
        )
        await self._repo.insert(config.schedule_id, config.model_dump())
        return config

    async def list_all(self, tenant_scope: Optional[str] = None) -> list[ScheduledQueryConfig]:
        filters = {"tenant_scope": tenant_scope} if tenant_scope is not None else None
        rows = await self._repo.find_many(filters=filters)
        return [ScheduledQueryConfig(**r) for r in rows]

    async def get(self, schedule_id: str) -> Optional[ScheduledQueryConfig]:
        row = await self._repo.find_by_id(schedule_id)
        return ScheduledQueryConfig(**row) if row else None

    async def delete(self, schedule_id: str) -> bool:
        row = await self._repo.find_by_id(schedule_id)
        if row is None:
            return False
        await self._repo.delete(schedule_id)
        return True

    async def update_run_status(
        self,
        schedule_id: str,
        *,
        status: str,
        detail: Optional[str] = None,
    ) -> None:
        row = await self._repo.find_by_id(schedule_id)
        if row is None:
            return
        row["last_run_at"] = _utc_now_iso()
        row["last_run_status"] = status
        row["last_run_detail"] = detail
        await self._repo.insert(schedule_id, row)


# ── Dune API pull ─────────────────────────────────────────────────────────────

async def _fetch_dune_results(query_id: str, api_key: str) -> DuneQueryResult:
    """Call the Dune API and return a DuneQueryResult."""
    import httpx

    url = _DUNE_RESULTS_URL.format(query_id=query_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers={"X-Dune-API-Key": api_key})
        resp.raise_for_status()
        body = resp.json()

    result = body.get("result", {})
    rows = result.get("rows", [])
    metadata = result.get("metadata", {})
    execution_id = body.get("execution_id", f"exec-{uuid.uuid4()}")

    return DuneQueryResult(
        query_id=str(query_id),
        execution_id=execution_id,
        query_name=metadata.get("query_name", f"dune_query_{query_id}"),
        query_version=str(metadata.get("query_version", "")),
        rows=rows,
        pulled_at=_utc_now_iso(),
    )


# ── Polling worker ────────────────────────────────────────────────────────────

class DunePollingWorker:
    """
    Async background worker.

    On each tick (every _TICK_INTERVAL_SECONDS):
    1. Load all enabled ScheduledQueryConfig records.
    2. For each config whose next-run time has passed, call Dune and ingest.
    3. Update last_run_at / last_run_status on the config.
    """

    def __init__(self) -> None:
        self._store = ScheduledQueryStore()

    def _resolve_api_key(self, config: ScheduledQueryConfig) -> Optional[str]:
        """Return the Dune API key for this config, or None if not configured."""
        if config.api_key_ref:
            # Vault lookup would go here in production.
            # For now, treat api_key_ref as a direct env var name (safe for staging).
            key = os.getenv(config.api_key_ref)
            if key:
                return key
        return os.getenv("DUNE_API_KEY")

    def _is_due(self, config: ScheduledQueryConfig) -> bool:
        if not config.enabled:
            return False
        if config.last_run_at is None:
            return True
        try:
            last = datetime.fromisoformat(config.last_run_at)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed >= config.interval_seconds

    async def _run_one(self, config: ScheduledQueryConfig) -> ScheduleRunSummary:
        """Execute one scheduled poll. Returns a run summary."""
        from services.dune_feeder.service import dune_feeder_service

        ran_at = _utc_now_iso()

        if not _is_live():
            logger.info(
                "Dune scheduler: local mode — skipping live pull",
                extra={"schedule_id": config.schedule_id, "query_id": config.query_id},
            )
            await self._store.update_run_status(
                config.schedule_id, status="skipped", detail="local mode"
            )
            return ScheduleRunSummary(
                schedule_id=config.schedule_id,
                query_id=config.query_id,
                source_tag=config.source_tag,
                ran_at=ran_at,
                status="skipped",
                detail="local mode — no external API call",
            )

        api_key = self._resolve_api_key(config)
        if not api_key:
            detail = "no Dune API key configured (set DUNE_API_KEY or api_key_ref)"
            logger.warning(
                "Dune scheduler: no API key",
                extra={"schedule_id": config.schedule_id},
            )
            await self._store.update_run_status(
                config.schedule_id, status="skipped", detail=detail
            )
            return ScheduleRunSummary(
                schedule_id=config.schedule_id,
                query_id=config.query_id,
                source_tag=config.source_tag,
                ran_at=ran_at,
                status="skipped",
                detail=detail,
            )

        try:
            query_result = await _fetch_dune_results(config.query_id, api_key)

            ingest_req = FeederIngestRequest(
                query_result=query_result,
                source_tag=config.source_tag,
                domain=config.domain,
                tenant_scope=config.tenant_scope,
                schema=config.schema,
                required_fields=config.required_fields,
                max_age_seconds=config.max_age_seconds,
                quality_threshold=config.quality_threshold,
            )
            resp = await dune_feeder_service.ingest(ingest_req)

            detail = f"accepted={resp.rows_accepted} rejected={resp.rows_rejected}"
            await self._store.update_run_status(
                config.schedule_id, status="ok", detail=detail
            )
            metrics.increment(
                "dune_scheduler_run",
                labels={"status": "ok", "query_id": config.query_id},
            )
            logger.info(
                "Dune scheduler: poll complete",
                extra={
                    "schedule_id": config.schedule_id,
                    "query_id": config.query_id,
                    "rows_accepted": resp.rows_accepted,
                    "rows_rejected": resp.rows_rejected,
                },
            )
            return ScheduleRunSummary(
                schedule_id=config.schedule_id,
                query_id=config.query_id,
                source_tag=config.source_tag,
                ran_at=ran_at,
                status="ok",
                rows_submitted=resp.rows_submitted,
                rows_accepted=resp.rows_accepted,
                rows_rejected=resp.rows_rejected,
                detail=detail,
            )

        except Exception as exc:
            detail = str(exc)[:200]
            logger.error(
                "Dune scheduler: poll failed",
                extra={
                    "schedule_id": config.schedule_id,
                    "query_id": config.query_id,
                    "error": detail,
                },
            )
            await self._store.update_run_status(
                config.schedule_id, status="error", detail=detail
            )
            metrics.increment(
                "dune_scheduler_run",
                labels={"status": "error", "query_id": config.query_id},
            )
            return ScheduleRunSummary(
                schedule_id=config.schedule_id,
                query_id=config.query_id,
                source_tag=config.source_tag,
                ran_at=ran_at,
                status="error",
                detail=detail,
            )

    async def _tick(self) -> list[ScheduleRunSummary]:
        """Load configs, run due jobs, return summaries."""
        try:
            configs = await self._store.list_all()
        except Exception as exc:
            logger.warning(f"Dune scheduler: failed to load configs: {exc}")
            return []

        summaries: list[ScheduleRunSummary] = []
        for config in configs:
            if self._is_due(config):
                summary = await self._run_one(config)
                summaries.append(summary)
        return summaries

    async def run(self) -> None:
        """Main loop — runs until cancelled."""
        logger.info("Dune polling worker started")
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Dune scheduler tick error: {exc}")
            await asyncio.sleep(_TICK_INTERVAL_SECONDS)
        logger.info("Dune polling worker stopped")


# ── Module-level singleton + entry point ──────────────────────────────────────

_worker = DunePollingWorker()

# Expose store for use by routes without re-instantiating.
schedule_store = _worker._store


async def start_dune_polling_worker() -> None:
    """Entry point called by the app lifespan."""
    await _worker.run()
