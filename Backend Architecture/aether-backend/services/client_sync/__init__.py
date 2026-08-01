"""Client-sync feed service + emitter + route (C1).

The durable catch-up channel: GET /v1/client-sync?cursor= replays change events
since a cursor. Producers call enqueue_sync_change() at their mutation sites; the
realtime SSE/WS transport remains the optional low-latency push. See
docs/source-of-truth/CROSS_DEVICE_CONTINUITY.md and decision-log D5.
"""
