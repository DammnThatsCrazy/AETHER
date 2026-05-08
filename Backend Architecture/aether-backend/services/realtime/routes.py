"""
Aether Service — Realtime (Profile 360)

SSE-first, WebSocket-second fan-out of Profile 360 events filtered to a
specific (tenant_id, entity_id). Backed by RealtimeHub which subscribes to
the shared EventConsumer.

Endpoints:
    GET /v1/realtime/sse?entity_id=...        Server-Sent Events stream
    WS  /v1/realtime/ws?entity_id=...         WebSocket stream
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from shared.common.common import BadRequestError
from shared.events.events import EventConsumer
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_consumer
from services.realtime.hub import get_hub

logger = get_logger("aether.service.realtime")
router = APIRouter(prefix="/v1/realtime", tags=["Profile 360 / Realtime"])


async def _ensure_attached(consumer: EventConsumer) -> None:
    hub = get_hub()
    await hub.attach(consumer)


@router.get("/sse")
async def sse_stream(
    request: Request,
    entity_id: str = Query(...),
    consumer: EventConsumer = Depends(get_consumer),
):
    """SSE stream of Profile 360 events for the given entity_id."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    await _ensure_attached(consumer)
    hub = get_hub()
    queue = await hub.subscribe(tenant.tenant_id, entity_id)

    async def gen():
        # Initial hello so clients can confirm the stream is live.
        yield f"event: hello\ndata: {json.dumps({'entity_id': entity_id})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: profile\ndata: {msg}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat keeps proxies from killing the connection.
                    yield ": keepalive\n\n"
        finally:
            await hub.unsubscribe(tenant.tenant_id, entity_id, queue)

    metrics.increment("realtime_sse_connected")
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.websocket("/ws")
async def ws_stream(
    websocket: WebSocket,
    entity_id: str = Query(...),
):
    """WebSocket stream of Profile 360 events for the given entity_id.

    Tenant comes from the upstream auth middleware that populated
    `websocket.scope['state'].tenant`. If the middleware did not run for
    websockets, the connection is closed.
    """
    state = websocket.scope.get("state")
    tenant = getattr(state, "tenant", None) if state is not None else None
    if tenant is None or not getattr(tenant, "tenant_id", None):
        await websocket.close(code=4401, reason="unauthenticated")
        return
    if not tenant.has_permission("read"):
        await websocket.close(code=4403, reason="forbidden")
        return

    # The consumer is owned by the registry; we only need it to attach the hub.
    from dependencies.providers import get_registry
    consumer = get_registry().consumer
    await _ensure_attached(consumer)

    hub = get_hub()
    queue = await hub.subscribe(tenant.tenant_id, entity_id)
    await websocket.accept()
    metrics.increment("realtime_ws_connected")
    try:
        await websocket.send_json({"type": "hello", "entity_id": entity_id})
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "keepalive"})
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(tenant.tenant_id, entity_id, queue)
