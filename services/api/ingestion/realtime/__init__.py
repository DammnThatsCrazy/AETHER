"""Profile 360 — Realtime fan-out.

SSE-first (FastAPI native) and WebSocket (parallel) channels backed by a
Kafka consumer that filters events by (tenant_id, entity_id).
"""
