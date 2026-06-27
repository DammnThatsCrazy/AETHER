---
title: Noesis — Operator Guide (Kyber)
slug: noesis-operator-guide
section: concepts
visibility: I
audience: [dev-senior, architect, ops]
status: stable
---

# Noesis — Operator Guide (Kyber)

This guide covers Noesis as seen by internal Aether operators using the Kyber surface. Kyber operators have cross-tenant read access and additional visibility into query execution details.

## Kyber vs Aether surface

| Feature | Aether (tenant) | Kyber (operator) |
|---------|----------------|-----------------|
| Scope | Own tenant only | All authorized tenants |
| `tenant_summary` intent | Blocked | Available |
| ScopeBar | Not shown | Shown on every response |
| ExecutionTrace | Not shown | Collapsible panel |
| `query_debug` field | Never returned | Returned when `NOESIS_DEBUG_ENABLED=true` |
| Cross-tenant flag | Never set | Set when querying across tenants |

## Effective tenant scope

Kyber operators can query a specific tenant by including a `tenant_id` field in the request body, or query all authorized tenants by omitting it. The ScopeBar on every response shows:

- **Surface**: always `kyber`
- **Effective tenant**: the tenant ID whose data was queried (or "all authorized tenants")
- **cross-tenant badge**: shown when the operator's own tenant differs from the queried tenant

## Execution trace panel

Every Kyber Noesis response includes a collapsible **Execution trace** panel showing:

- **Intent and mode**: what Noesis classified the query as, and whether it used deterministic routing or the LLM text-to-query path
- **Provider**: which LLM provider was used (if any) — `anthropic`, `openai`, or `—` for deterministic
- **Confidence**: classification confidence percentage
- **Evidence sources**: each data service queried, with resource type
- **Warnings**: any faithfulness warnings (LLM path claimed an identifier not found in evidence)
- **View in Audit Ledger**: link to the specific `request_id` in the audit log

## Supported intents

All 15 intents in the capability registry are available to Kyber operators. The `tenant_summary` intent is Kyber-only and is blocked for Aether tenants.

Call `GET /v1/noesis/capabilities` to retrieve the live capability list filtered for your surface:

```bash
curl -H "Authorization: Bearer $TOKEN" /v1/noesis/capabilities
```

## Circuit breaker status

The graph client and LLM provider calls are wrapped in circuit breakers. When a circuit opens (5 consecutive failures), fallback responses are returned immediately rather than queuing additional failures.

States: `closed` (normal) → `open` (fast-failing) → `half_open` (probing) → `closed`.

Recovery timeout is 30 seconds by default. Check `GET /v1/noesis/health` for current state.

## Health and readiness endpoint

```bash
GET /v1/noesis/health
```

Returns 200 when healthy, 503 when degraded:

```json
{
  "status": "ok",
  "checks": {
    "noesis_enabled": true,
    "conversation_redis": true,
    "rate_limiter_redis": true,
    "llm_provider_configured": true
  }
}
```

## Audit ledger queries

Every Noesis query is recorded in the `SecurityAuditLedger` with `event_type="noesis.query"`. Useful fields:

| Field | Description |
|-------|-------------|
| `resource_id` | The `request_id` UUID (links to execution trace) |
| `action` | The resolved intent (e.g. `entity_search`) |
| `outcome` | `success`, `rate_limited`, `rejected`, `unsupported`, etc. |
| `tenant_id` | The requesting tenant |
| `metadata.effective_tenant_id` | The tenant whose data was queried |
| `metadata.mode` | `deterministic` or `llm_text_to_query` |

To look up a specific query in the audit ledger, use `request_id` from the execution trace panel or from the `X-Request-ID` response header.

## Rate limits

Default limits (configurable via env vars):

| Scope | Default |
|-------|---------|
| Per-tenant QPM | `NOESIS_RATE_LIMIT_QPM` (default: 60) |
| Per-tenant daily | `NOESIS_RATE_LIMIT_DAILY` (default: 1000) |
| Token daily (per tenant) | `NOESIS_TENANT_TOKEN_DAILY_LIMIT` (default: 5000) |
| Token monthly (per tenant) | `NOESIS_TENANT_TOKEN_MONTHLY_LIMIT` (default: 50000) |
| Global daily token budget | `NOESIS_PROVIDER_TOKEN_BUDGET` (default: 100000) |

See the runbook for how to flush limits for a specific tenant.
