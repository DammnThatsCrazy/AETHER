"""
Aether Service — Realtime (Profile 360 + Channel Subscriptions)

SSE-first, WebSocket-second fan-out of Profile 360 events filtered to a
specific (tenant_id, entity_id). Backed by RealtimeHub which subscribes to
the shared EventConsumer.

Also provides a channel-protocol WebSocket endpoint that implements the full
RealtimeSubscribeMessage / RealtimeEventMessage / RealtimeAckMessage contract
from packages/shared/operational-intelligence.ts.

Endpoints:
    GET /v1/realtime/sse?entity_id=...        Server-Sent Events stream (Profile 360)
    WS  /v1/realtime/ws?entity_id=...         WebSocket stream (Profile 360, entity-scoped)
    WS  /v1/realtime/ws/subscribe             Channel-protocol WebSocket (multi-channel)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from shared.common.common import BadRequestError
from shared.events.events import EventConsumer
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_consumer
from services.realtime.hub import get_hub
from services.realtime.channel_hub import get_channel_hub
from services.operational_intelligence.models import (
    RealtimeSubscribeMessage,
    RealtimeUnsubscribeMessage,
    RealtimeAckMessage,
    RealtimeHeartbeatMessage,
)

logger = get_logger("aether.service.realtime")
router = APIRouter(prefix="/v1/realtime", tags=["Profile 360 / Realtime"])

# Minimum permission required to subscribe to each named channel.
# Channels not listed default to "read".
_CHANNEL_PERMISSIONS: dict[str, str] = {
    "investigation.workspace": "write",
    "agent.coordination":      "write",
    "governance.audit":        "read",
    "tenant.alerts":           "read",
    "tenant.events":           "read",
    "entity.profile":          "read",
    "entity.relationships":    "read",
    "journey.timeline":        "read",
    "cluster.membership":      "read",
    "web3.wallets":            "read",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


@router.websocket("/ws/subscribe")
async def ws_channel_subscribe(websocket: WebSocket) -> None:
    """Channel-protocol WebSocket — implements the full RealtimeSubscribeMessage contract.

    Protocol (client drives):
      1. Connect (no query params required)
      2. Send RealtimeSubscribeMessage JSON   → server responds with RealtimeAckMessage
      3. Receive RealtimeEventMessage JSON    → one per qualifying event
      4. Receive RealtimeHeartbeatMessage     → every ~15 s
      5. Optionally send RealtimeUnsubscribeMessage to shed channels
      6. Disconnect at any time

    Cursors are monotonic (wall-clock-ms:sequence) — reconnect with the last
    received cursor to resume from that point (server-side replay is deferred;
    cursor is accepted and acked for forward compat).
    """
    state = websocket.scope.get("state")
    tenant = getattr(state, "tenant", None) if state is not None else None
    if tenant is None or not getattr(tenant, "tenant_id", None):
        await websocket.close(code=4401, reason="unauthenticated")
        return
    if not tenant.has_permission("read"):
        await websocket.close(code=4403, reason="forbidden")
        return

    from dependencies.providers import get_registry
    consumer = get_registry().consumer
    channel_hub = get_channel_hub()
    await channel_hub.attach(consumer)

    await websocket.accept()
    metrics.increment("realtime_ws_channel_connected")

    # channel_name → asyncio.Queue — built after first subscribe message
    active_queues: dict[str, asyncio.Queue] = {}
    # Merged queue: all channel queues drain into this for unified pump
    merged_queue: asyncio.Queue = asyncio.Queue(maxsize=1024)

    async def _pump_to_merged(ch: str, q: asyncio.Queue) -> None:
        """Forward from a per-channel queue into the merged queue."""
        try:
            while True:
                msg = await q.get()
                await merged_queue.put(msg)
        except asyncio.CancelledError:
            pass

    pump_tasks: list[asyncio.Task] = []

    async def _handle_subscribe(data: dict[str, Any]) -> None:
        nonlocal active_queues
        try:
            sub = RealtimeSubscribeMessage(**data)
        except Exception as exc:
            await websocket.send_json({
                "action": "ack",
                "requestId": data.get("requestId", ""),
                "accepted": False,
                "error": {"code": "invalid_message", "message": str(exc), "requestId": data.get("requestId", "")},
            })
            return

        if sub.tenantId != tenant.tenant_id:
            await websocket.send_json({
                "action": "ack",
                "requestId": sub.requestId,
                "accepted": False,
                "error": {"code": "forbidden", "message": "tenantId mismatch", "requestId": sub.requestId},
            })
            return

        # Per-channel permission check before subscribing
        for ch in sub.channels:
            required = _CHANNEL_PERMISSIONS.get(ch, "read")
            if not tenant.has_permission(required):
                await websocket.send_json({
                    "action": "ack",
                    "requestId": sub.requestId,
                    "accepted": False,
                    "error": {
                        "code": "forbidden",
                        "message": f"insufficient permission for channel {ch!r} (requires {required!r})",
                        "requestId": sub.requestId,
                    },
                })
                return

        new_channels = [ch for ch in sub.channels if ch not in active_queues]
        if new_channels:
            new_queues = await channel_hub.subscribe(sub.tenantId, list(new_channels))
            for ch, q in new_queues.items():
                active_queues[ch] = q
                t = asyncio.create_task(_pump_to_merged(ch, q))
                pump_tasks.append(t)

        await websocket.send_json({
            "action": "ack",
            "requestId": sub.requestId,
            "accepted": True,
            "cursor": sub.cursor,
        })
        logger.info(
            "realtime_channel_subscribed",
            extra={"tenant_id": tenant.tenant_id, "channels": list(sub.channels)},
        )

    async def _handle_unsubscribe(data: dict[str, Any]) -> None:
        try:
            unsub = RealtimeUnsubscribeMessage(**data)
        except Exception:
            return
        shed: dict[str, asyncio.Queue] = {}
        for ch in unsub.channels:
            if ch in active_queues:
                shed[ch] = active_queues.pop(ch)
        if shed:
            await channel_hub.unsubscribe(tenant.tenant_id, shed)

    try:
        # Bidirectional loop: read client messages; pump outbound events & heartbeats
        while True:
            # Non-blocking check for inbound client messages
            recv_task = asyncio.create_task(websocket.receive_json())
            pump_task = asyncio.create_task(
                asyncio.wait_for(merged_queue.get(), timeout=15.0)
            )
            done, pending = await asyncio.wait(
                [recv_task, pump_task], return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            if recv_task in done:
                try:
                    data = recv_task.result()
                    action = data.get("action") if isinstance(data, dict) else None
                    if action == "subscribe":
                        await _handle_subscribe(data)
                    elif action == "unsubscribe":
                        await _handle_unsubscribe(data)
                except Exception:
                    # Client disconnected or sent bad JSON
                    break

            if pump_task in done:
                try:
                    outbound = pump_task.result()
                    await websocket.send_text(outbound)
                except asyncio.TimeoutError:
                    # Heartbeat
                    await websocket.send_json({"action": "heartbeat", "serverTime": _utc_now()})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    finally:
        for t in pump_tasks:
            t.cancel()
        if active_queues:
            await channel_hub.unsubscribe(tenant.tenant_id, active_queues)
        metrics.increment("realtime_ws_channel_disconnected")
