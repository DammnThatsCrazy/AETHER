"""Journey-service entrypoint.

Two surfaces:
  • FastAPI HTTP — health, manual journey close, on-demand backfill kickoff
  • Kafka consumer loop — `aether.sdk.events.validated` -> JourneyProcessor

Wiring is intentionally thin so the same processor runs under tests
and under the nightly batch reconciler.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException

from .processor import JourneyProcessor

logger = logging.getLogger("aether.journey")


# ---------------------------------------------------------------------
# Stub clients — production wires to asyncpg, gremlinpython, redis,
# clickhouse-driver, aiokafka.
# ---------------------------------------------------------------------

class _InMemoryCH:
    def __init__(self) -> None: self.rows: list[tuple[str, dict]] = []
    async def __call__(self, table: str, row: dict) -> None: self.rows.append((table, row))


class _InMemoryProducer:
    def __init__(self) -> None: self.published: list[tuple[str, dict]] = []
    async def publish(self, topic: str, payload: dict) -> None: self.published.append((topic, payload))


def build_processor() -> JourneyProcessor:
    # In-memory wiring for local dev / tests. Production swaps these for
    # the real GraphClient (Neptune), CacheClient (Redis), Postgres-backed
    # repos, ClickHouse async writer, and aiokafka producer.
    from shared.cache.cache import CacheClient            # type: ignore
    from shared.graph.graph import GraphClient            # type: ignore
    # Local import keeps the journey-service decoupled from shared-graph
    # availability at import time in test environments.
    import importlib
    repos = importlib.import_module("repos")              # Backend Architecture/repos.py

    cache = CacheClient()
    graph = GraphClient()
    return JourneyProcessor(
        actor_repo=repos.ActorRepository(graph, cache),
        journey_repo=repos.JourneyRepository(graph, cache),
        delegation_repo=repos.DelegationRepository(cache),
        snapshot_writer=__import__(
            "snapshot_writer", fromlist=["IcebergSnapshotWriter"]
        ).IcebergSnapshotWriter()
        if False else _lazy_snapshot_writer(),  # falls back to relative import
        clickhouse_writer=_InMemoryCH(),
        producer=_InMemoryProducer(),
    )


def _lazy_snapshot_writer():
    from .snapshot_writer import IcebergSnapshotWriter
    return IcebergSnapshotWriter()


# ---------------------------------------------------------------------
# Kafka consumer loop (stub — reads from an asyncio.Queue under tests)
# ---------------------------------------------------------------------

class EventConsumerLoop:
    def __init__(self, processor: JourneyProcessor) -> None:
        self.processor = processor
        self.queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass

    async def _run(self) -> None:
        while True:
            try:
                envelope = await self.queue.get()
                project_id = envelope.get("projectId") or "default"
                event = envelope.get("event") or envelope
                await self.processor.process(event, project_id=project_id)
            except asyncio.CancelledError:
                raise
            except Exception:                # noqa: BLE001
                logger.exception("journey-service: failed to process event")


# ---------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.processor = build_processor()
    app.state.consumer = EventConsumerLoop(app.state.processor)
    if os.getenv("JOURNEY_CONSUMER_AUTOSTART", "1") != "0":
        await app.state.consumer.start()
    try:
        yield
    finally:
        await app.state.consumer.stop()


app = FastAPI(title="aether-journey-service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "journey-service"}


@app.post("/v1/events")
async def ingest_event(payload: dict) -> dict:
    """Direct synchronous ingest for tests / replays.

    Bypasses Kafka. Production traffic enters via the consumer loop.
    """
    event = payload.get("event")
    project_id = payload.get("projectId")
    if not event or not project_id:
        raise HTTPException(400, "event and projectId required")
    outcome = await app.state.processor.process(event, project_id=project_id)
    return {
        "journey_id": outcome.journey_id,
        "is_new_journey": outcome.is_new_journey,
        "closed_journey_id": outcome.closed_journey_id,
    }


@app.post("/v1/journeys/{journey_id}/close")
async def force_close(journey_id: str, payload: dict) -> dict:
    reason = payload.get("reason", "manual")
    ended_at = payload.get("ended_at")
    journey = await app.state.processor.journeys.close(
        journey_id, reason=reason, ended_at=ended_at,
    )
    return {"journey_id": journey["journey_id"], "state": journey["state"]}
