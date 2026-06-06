---
title: Noesis GA Production Contract
slug: noesis-ga-contract
section: architecture
visibility: I
audience: [dev-senior, product, security]
status: stable
---

# Noesis GA Production Contract

## Overview

Noesis is Aether's graph-native natural-language intelligence layer. It provides read-only query capabilities against the tenant intelligence graph through both Aether (tenant-facing) and Kyber (operator-facing) surfaces.

**GA status:** Deterministic read-only Noesis.
**LLM-assisted planning:** Feature-flagged, off by default. Available when `NOESIS_LLM_ENABLED=true` and a provider is configured.

## Supported Surfaces

| Surface | Audience | Cross-tenant | Debug output |
|---------|----------|-------------|-------------|
| `aether` | Tenant users | Never | Never |
| `kyber` | Internal operators | Operator-only | Operator-only |

## Supported GA Intents

| Intent | Description | Surfaces | Read target |
|--------|-------------|----------|-------------|
| `entity_search` | Search tenant-scoped entities by name/type | aether, kyber | EntityRepository |
| `graph_lookup` | Traverse graph neighbors for a specific entity | aether, kyber | GraphClient |
| `alert_lookup` | List unresolved alert records | aether, kyber | AlertRepository |
| `tenant_summary` | Aggregate tenant health/status | kyber only | AdminRepository, AnalyticsRepository, AlertRepository, EntityRepository |
| `profile_lookup` | Search human/user profiles | aether, kyber | EntityRepository |
| `wallet_lookup` | Search wallet records | aether, kyber | WalletRepository |
| `agent_lookup` | Search agent configurations | aether, kyber | AgentConfigRepository, EntityRepository |
| `health_lookup` | SDK/provider health, failed agents, analytics | aether, kyber | ProvidersRepository, AgentExecutionRepository, AnalyticsRepository |
| `campaign_reward_lookup` | Campaign and reward records | aether, kyber | CampaignRepository, BaseRepository("rewards") |
| `risk_cluster_lookup` | Entities sorted by risk score | aether, kyber | EntityRepository |

## Unsupported Prompt Behavior

Prompts that cannot be classified into a supported intent:
- Return a fallback response with `mode: "fallback"` and `intent: "unsupported"`.
- Include an `error` object with `code: "unsupported_intent"`.
- Include a `refine_query` action suggesting supported question types.
- Never hallucinate unsupported capabilities.
- Never issue hidden or generated queries.
- Never expose debug data to tenant users.
- Never bypass tenant/RBAC scope.
- Never mutate data.

## Write-Like Prompt Behavior

Prompts containing mutation verbs (delete, modify, export, execute, etc.) or prompt injection patterns:
- Return a safe rejection response with `mode: "fallback"`.
- Include an `error` object with `code: "rejected_write_like"` or `code: "rejected_injection"`.
- Log the attempt with structured audit logging.
- Increment safety metrics.
- Never execute the requested operation.

## Data Freshness

- Repository data reflects the most recent committed state in the backing store.
- Graph data reflects the most recent committed state in Neptune (production) or in-memory (local).
- Analytics summaries may be cached for up to 5 minutes (CacheClient TTL).
- No real-time streaming guarantees.

## Latency Expectations

| Component | Target | Maximum |
|-----------|--------|---------|
| Total request | < 500ms | 2000ms |
| Deterministic planner | < 5ms | 20ms |
| Repository dispatch | < 200ms | 1000ms |
| Graph traversal | < 300ms | 1500ms |
| LLM provider (when enabled) | < 3000ms | 5000ms |

## Answer Precision

| Category | Behavior |
|----------|----------|
| Exact match | Entity/wallet/agent lookups with specific ID |
| Approximate | Risk-sorted listings, search by partial name |
| Partial | Results capped at `limit` (default 10, max 50) |
| Unavailable | Intent not supported → fallback response |

## Access Control

| Role | Aether access | Kyber access | Cross-tenant | Debug |
|------|---------------|-------------|-------------|-------|
| VIEWER (with read) | Own tenant only | Own tenant only | No | No |
| EDITOR (with read) | Own tenant only | Own tenant only | No | No |
| ADMIN | Own tenant only | Any tenant | Yes | Yes |
| Operator (kyber:read) | N/A | Any tenant | Yes | Yes |

## Debug/Provenance Output

The `query_debug` field contains:
- `plan`: The resolved QueryPlan (intent, target, filters, limit, confidence, source).
- `read_only`: Always `true`.
- `validated`: Always `true`.

This field is:
- **Never returned** to Aether surface users.
- **Returned only** to Kyber operators with admin or kyber:read permission.
- **Never stored** in conversation persistence (redacted before storage).

## Request/Response Schema

### Request: `POST /v1/noesis/query`

```json
{
  "message": "string (1-2000 chars, required)",
  "surface": "aether | kyber (required)",
  "tenant_id": "string (optional, max 128 chars)",
  "conversation_id": "string (optional, max 128 chars, reserved for future use)",
  "context": {
    "current_page": "string (optional)",
    "selected_entity_id": "string (optional)",
    "selected_entity_type": "string (optional)",
    "time_range": "string (optional)",
    "filters": {}
  }
}
```

### Response

```json
{
  "data": {
    "answer": "string",
    "mode": "deterministic | llm_text_to_query | fallback",
    "intent": "string",
    "confidence": 0.0-1.0,
    "entities": [],
    "results": [],
    "graph": { "nodes": [], "edges": [], "highlights": [] },
    "actions": [],
    "query_debug": null | { "plan": {}, "read_only": true, "validated": true },
    "warnings": [],
    "error": null | { "code": "string", "message": "string", "details": {} }
  }
}
```

## Feature Flags

| Flag | Default | Description |
|------|---------|-------------|
| `NOESIS_ENABLED` | `true` | Master kill switch |
| `NOESIS_LLM_ENABLED` | `false` | Enable LLM-assisted planning |
| `NOESIS_DEBUG_ENABLED` | `true` | Allow debug output for operators |
| `NOESIS_CROSS_TENANT_ENABLED` | `true` | Allow Kyber cross-tenant queries |
| `NOESIS_RATE_LIMIT_QPM` | `60` | Max queries per minute per tenant |
| `NOESIS_DAILY_QUOTA` | `1000` | Max daily queries per tenant |
| `NOESIS_CANARY_TENANTS` | `""` | Comma-separated tenant allowlist (empty = all) |

## Rate Limits

- Per-tenant: `NOESIS_RATE_LIMIT_QPM` queries per minute.
- Per-tenant daily: `NOESIS_DAILY_QUOTA` queries per day.
- LLM mode: stricter limits may apply per provider token budget.

## Rollout Stages

1. Internal Kyber only (operators).
2. Selected internal users via canary tenant list.
3. Selected pilot tenants.
4. All eligible tenants.
5. Broader GA after monitoring period.

## Incident Response

1. **Kill switch:** Set `NOESIS_ENABLED=false` to disable the endpoint entirely.
2. **LLM kill switch:** Set `NOESIS_LLM_ENABLED=false` to disable LLM planning.
3. **Cross-tenant kill switch:** Set `NOESIS_CROSS_TENANT_ENABLED=false`.
4. **Rollback:** Revert to previous deployment. Noesis is stateless for GA (conversations deferred).
5. **Monitoring:** Check `noesis_query`, `noesis_rejected`, `noesis_safety` metrics.
