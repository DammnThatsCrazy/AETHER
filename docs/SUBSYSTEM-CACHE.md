---
title: Cache / Redis Subsystem
slug: data/cache
section: architecture
visibility: P
audience: [dev-senior, architect, ops]
status: stable
since_version: 0.1.0
source_files: [services/backend/shared/cache/cache.py]
canonical_owner: backend@aether
estimated_read_minutes: 4
toc_depth: 3
source_hashes:
  "services/backend/shared/cache/cache.py": "sha256:753e8d1a02710bedd08d966ccf5b02b4dfa5e36129448024c5db5fdc1eeddadc"
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
# Atomic set-if-not-exists (returns True if claimed, False if already set)
claimed = await cache.set_nx("aether:idempotency:key", "1", ttl=TTL.DAY)
```

`set_nx` is used for idempotency claims on ingestion events — it atomically marks an event as seen without a separate get+set round-trip, eliminating the race condition where two concurrent requests both observe a miss and both proceed. Every backend implements it: Redis uses `SET NX EX`, and the DynamoDB backend (lean staging/production) uses a conditional `PutItem` that succeeds only when the key is absent or its `ttl` has passed, since DynamoDB deletes expired items lazily. Ingestion treats a cache error as a successful claim, so a backend missing `set_nx` silently disables duplicate detection; a unit test pins the DynamoDB backend to the Redis backend's full operation set.

## Failure Modes

- Redis unreachable in production → `RuntimeError` at startup (fail-closed)
- Redis unreachable in local → falls back to in-memory dict
- TTL expired → returns `None` (cache miss)
