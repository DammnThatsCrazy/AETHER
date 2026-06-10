---
title: Cache / Redis Subsystem
slug: data/cache
section: data
visibility: P
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/shared/cache/cache.py
canonical_owner: backend@aether
estimated_read_minutes: 4
toc_depth: 3
last_synced_commit: 8659b94
---

# Cache / Redis Subsystem

## Architecture

The cache layer provides TTL-based key-value caching for all backend services via `shared/cache/cache.py`.

**Backend selection:**
- `AETHER_ENV=local` → in-memory dict with TTL expiry
- `AETHER_ENV=staging/production` → Redis via `redis.asyncio`

## Key Classes

- `CacheClient` — Public API. Auto-selects backend on `connect()`.
- `CacheKey` — Namespace conventions: `aether:{service}:{resource}:{id}`
- `TTL` — Preset durations (SHORT=60s, MEDIUM=300s, LONG=3600s, etc.)

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `REDIS_HOST` | Yes (staging/prod) | `localhost` | Redis hostname |
| `REDIS_PORT` | No | `6379` | Redis port |
| `REDIS_DB` | No | `0` | Redis database number |
| `REDIS_PASSWORD` | If secured | — | Redis auth password |

## Startup

`CacheClient.connect()` is called during `ResourceRegistry.startup()` in `dependencies/providers.py`. If Redis is unreachable in non-local environments, a `RuntimeError` is raised (fail-closed).

## Health Check

`CacheClient.health_check()` sends a Redis `PING` command. Returns `True` if Redis responds, `False` otherwise. Exposed via `GET /v1/health` as the `cache` dependency.

## Operations

```python
cache = CacheClient()
await cache.connect()
await cache.set_json("key", {"data": 1}, ttl=TTL.MEDIUM)
value = await cache.get_json("key")
await cache.delete("key")
await cache.delete_pattern("aether:identity:*")
```

## Failure Modes

- Redis unreachable in production → `RuntimeError` at startup (fail-closed)
- Redis unreachable in local → falls back to in-memory dict
- TTL expired → returns `None` (cache miss)
