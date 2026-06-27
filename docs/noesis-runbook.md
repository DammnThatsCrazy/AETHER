---
title: Noesis — Operations Runbook
slug: noesis-runbook
section: operations
visibility: I
audience: [dev-senior, architect, ops]
status: stable
---

# Noesis — Operations Runbook

Operational procedures for diagnosing and recovering Noesis in production.

## Check overall health

```bash
curl -s /v1/noesis/health | jq .
```

Returns `"status": "ok"` when all checks pass, `"status": "degraded"` with individual check breakdown when any dependency is unhealthy.

## Flush rate limits for a tenant

Rate limit counters are stored in Redis under `noesis:rl:{tenant_id}:*`. To reset a specific tenant's QPM and daily counters:

```bash
# Find all rate-limit keys for a tenant
redis-cli KEYS "noesis:rl:{tenant_id}:*"

# Delete them
redis-cli DEL noesis:rl:{tenant_id}:qpm:* noesis:rl:{tenant_id}:daily:*
```

To flush all Noesis rate limit keys (use with caution in production):

```bash
redis-cli --scan --pattern "noesis:rl:*" | xargs redis-cli DEL
```

## Flush token budget for a tenant

Token budget counters are stored under `noesis:tokens:daily:{tenant_id}:{date}` and `noesis:tokens:monthly:{tenant_id}:{month}`.

```bash
# Get today's date
DATE=$(date +%Y-%m-%d)
MONTH=$(date +%Y-%m)

# Check current spend
redis-cli GET "noesis:tokens:daily:{tenant_id}:${DATE}"
redis-cli GET "noesis:tokens:monthly:{tenant_id}:${MONTH}"

# Reset daily (e.g. after a billing issue or test run)
redis-cli DEL "noesis:tokens:daily:{tenant_id}:${DATE}"

# Check and reset global daily budget
redis-cli GET "noesis:tokens:global:daily:${DATE}"
redis-cli DEL "noesis:tokens:global:daily:${DATE}"
```

## Verify token budget state

To confirm token tracking is working (non-zero after a few queries):

```bash
DATE=$(date +%Y-%m-%d)
redis-cli GET "noesis:tokens:global:daily:${DATE}"
# Should be > 0 after any LLM-path query
```

If this key is always 0 or missing after LLM queries, the `NoesisTokenBudget.check_and_reserve` flow may not be reaching the LLM provider. Check that `NOESIS_LLM_ENABLED=true` and the API key is set.

## Replay audit events by request_id

Every Noesis query is recorded with `event_type="noesis.query"` and a `resource_id` equal to the `request_id` UUID.

To find a specific request in the audit ledger:

```sql
SELECT *
FROM audit_events
WHERE event_type = 'noesis.query'
  AND resource_id = '<request_id>'
ORDER BY created_at DESC
LIMIT 1;
```

The `metadata` column contains: `intent`, `mode`, `effective_tenant_id`, `surface`, `confidence`, and `outcome`.

To list all Noesis queries for a tenant in the last hour:

```sql
SELECT resource_id, action, outcome, metadata->>'mode' AS mode, created_at
FROM audit_events
WHERE event_type = 'noesis.query'
  AND tenant_id = '<tenant_id>'
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC;
```

## Respond to circuit-open alerts

When the graph client or LLM provider circuit opens, Noesis logs `"Circuit breaker OPENED"` at ERROR level with `circuit=graph_client` or `circuit=llm_provider`.

**Immediate response:**
1. Check `GET /v1/noesis/health` — `graph_client` failures will show as graph-related check failures.
2. Verify the downstream service (Neptune/graph DB or LLM API) is reachable.
3. The circuit transitions to HALF_OPEN automatically after 30 seconds (`recovery_timeout_s`). One probe is allowed through; on success the circuit closes.

**If the circuit will not recover automatically:**
- For graph: check Neptune connection string (`NEPTUNE_ENDPOINT`), security group rules, and Neptune cluster health.
- For LLM provider: check API key validity, provider status page, and `NOESIS_LLM_TIMEOUT_MS` setting.

**Manual circuit reset (emergency only):**
The `NoesisCircuitBreaker.reset()` method is available for testing. In production, prefer fixing the underlying dependency and letting the automatic recovery handle the transition.

## Diagnose a slow or stuck query

1. Find the `request_id` from the `X-Request-ID` response header or the audit ledger.
2. Check the execution trace in Kyber's Noesis UI for intent, mode, and provider.
3. Look for `noesis_provider_timeout` and `noesis_provider_error` metrics.
4. If the LLM provider is timing out, reduce `NOESIS_LLM_TIMEOUT_MS` or increase `NOESIS_LLM_MAX_RETRIES`.
5. For graph timeouts, check Neptune cluster load and query plan.

## Enable debug mode (temporary)

To expose `query_debug` in Kyber responses:

```bash
NOESIS_DEBUG_ENABLED=true
```

This is **Kyber-only** — Aether surface responses never receive `query_debug` regardless of this flag. Default is `false` in production.

## Enable multi-hop graph traversal

```bash
NOESIS_MULTI_HOP_ENABLED=true
```

When enabled, graph queries with `depth > 1` in the query plan perform k-hop BFS traversal (in-memory) or parameterized Gremlin `repeat(both().simplePath()).times(N)` on Neptune. Maximum depth is hard-capped at 3.

## LLM provider switchover

To switch from Anthropic to OpenAI:

```bash
NOESIS_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
NOESIS_LLM_MODEL=gpt-4o-mini   # or override
```

To switch back to Anthropic (default):

```bash
NOESIS_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
NOESIS_LLM_MODEL=claude-haiku-4-5-20251001
```

The provider is resolved at startup by `ProductionNoesisPlanProvider`. A restart is required after changing these vars.

## Startup validation errors

If `NOESIS_ENABLED=true` and startup validation fails, the service will raise `RuntimeError` with a list of configuration errors. Common errors:

| Error | Fix |
|-------|-----|
| `ANTHROPIC_API_KEY not set` | Set the env var or disable LLM (`NOESIS_LLM_ENABLED=false`) |
| `Redis not reachable` | Fix Redis connection string or disable Noesis |
| `NOESIS_RATE_LIMIT_QPM must be a positive integer` | Check env var value |

Check the startup logs for the full list of errors before the service aborts.
