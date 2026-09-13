"""Operator route for ingestion-level replay (WS-B4).

The minimal OPERATOR surface over :func:`services.ingestion.replay.replay_events`
— Kyber-operator-only (router-level ``require_kyber_operator``), targeting one
tenant's durable Bronze SDK events. Original-time preservation (Invariant #15)
is owned by the replay runner/adapter, not this route; this file only exposes
the run + its kill switch:

- ``dry_run`` defaults to True: an operator previews counts (rows scanned /
  would-replay / gateway-rejected / skipped) with ZERO publishes.
- A REAL run (``dry_run=false``) requires ``AETHER_INGESTION_REPLAY_ENABLED``
  (``settings.ingest_replay.enabled``) — the flag-gated adoption switch shared
  with the rest of WS-B. When the flag is OFF a real run is refused with a
  403 (``ForbiddenError``); the dry-run preview stays available so operators
  can always size a replay before it is enabled.

Mount marker (integration seam — main.py is OUT of the WS-B4 zone):
    # WS-B4: mount in main.py — app.include_router(kyber_replay_router)
The WS-B4 slice leaves this seam for the program tip; no main.py change here.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from config.settings import settings
from dependencies.providers import get_producer
from services.ingestion.replay import REPLAY_SOURCE_SERVICE, replay_events
from services.security.request_context import require_kyber_operator
from shared.common.common import ForbiddenError

kyber_replay_router = APIRouter(
    prefix="/v1/kyber/ingest/replay",
    tags=["Kyber Ingestion Replay"],
    dependencies=[Depends(require_kyber_operator)],
)


class ReplayRequest(BaseModel):
    """One operator-initiated replay scan request against a tenant's Bronze."""

    tenant_id: str = Field(
        ..., description="Target tenant whose durable Bronze events are replayed"
    )
    event_types: list[str] = Field(
        default_factory=list, description="Restrict to these original event types"
    )
    families: list[str] = Field(
        default_factory=list, description="Restrict to these Envelope-B families"
    )
    occurred_from: Optional[str] = Field(
        default=None, description="ISO-8601 inclusive lower bound on ORIGINAL occurrence"
    )
    occurred_to: Optional[str] = Field(
        default=None, description="ISO-8601 inclusive upper bound on ORIGINAL occurrence"
    )
    limit: Optional[int] = Field(
        default=None, ge=1, description="Cap on rows scanned (stable Bronze order)"
    )
    dry_run: bool = Field(
        default=True, description="Preview counts with zero publishes (safe default)"
    )
    replay_run_id: Optional[str] = Field(
        default=None,
        description="Caller-supplied run id — repeating a completed id is a no-op",
    )


async def replay_endpoint(
    body: ReplayRequest,
    producer: Any = Depends(get_producer),
) -> dict[str, Any]:
    """POST /v1/kyber/ingest/replay/events — run (or preview) an ingestion replay."""
    if not body.dry_run and not settings.ingest_replay.enabled:
        raise ForbiddenError(
            "ingestion-level replay is disabled "
            "(AETHER_INGESTION_REPLAY_ENABLED=false); "
            "pass dry_run=true to preview what a run would replay"
        )
    return await replay_events(
        body.tenant_id,
        event_types=body.event_types or None,
        families=body.families or None,
        occurred_from=body.occurred_from,
        occurred_to=body.occurred_to,
        limit=body.limit,
        dry_run=body.dry_run,
        producer=producer,
        replay_run_id=body.replay_run_id,
    )


@kyber_replay_router.post("/events", summary="Replay durable Bronze SDK events")
async def post_replay(body: ReplayRequest) -> dict[str, Any]:
    return await replay_endpoint(body)


@kyber_replay_router.get("/status", summary="Ingestion replay service status")
async def replay_status() -> dict[str, Any]:
    """Operator visibility: the kill-switch state + the bus source_service label
    replayed events carry (so operators can filter live-vs-replay downstream)."""
    return {
        "enabled": settings.ingest_replay.enabled,
        "source_service": REPLAY_SOURCE_SERVICE,
        "dry_run_default": True,
    }
