---
title: Noesis Graph Intelligence
slug: internal/noesis
section: architecture
visibility: I
audience: [dev-senior]
status: production
source_files:
  - Backend Architecture/aether-backend/services/noesis/service.py
  - Backend Architecture/aether-backend/services/noesis/routes.py
  - Backend Architecture/aether-backend/services/noesis/models.py
  - Backend Architecture/aether-backend/services/noesis/provider.py
  - Backend Architecture/aether-backend/services/noesis/flags.py
  - frontend/shared/src/components/noesis-workspace.tsx
---

# Noesis

Noesis is Aether's graph-native natural-language intelligence layer. It exposes a shared read-only backend endpoint for both Kyber (internal operator console) and Aether (tenant-facing intelligence UI), plus dedicated frontend workspaces in each surface.

**Status:** Production (GA). Phase 0 (stabilize beta) and Phase 1 (production deterministic Noesis) are complete.

## GA contract

### Supported intents (10)

| Intent | Description |
|---|---|
| `entity_search` | Full-text entity search scoped to tenant |
| `graph_lookup` | Graph neighborhood traversal |
| `alert_lookup` | Unresolved alert listing |
| `tenant_summary` | Tenant analytics summary (Kyber only) |
| `profile_lookup` | Human/user profile lookup |
| `wallet_lookup` | Wallet record lookup |
| `agent_lookup` | Agent configuration lookup |
| `health_lookup` | SDK/provider health diagnostics |
| `campaign_reward_lookup` | Campaign and reward listing |
| `risk_cluster_lookup` | Risk-scored entity ranking |

Any prompt that does not match a supported intent falls back to a safe refinement response. Unsupported intents never execute.

### Unsupported behavior

Noesis is strictly read-only. The following are explicitly rejected:

- Write/mutation prompts (delete, modify, create, export, etc.)
- Injection patterns (ignore previous instructions, jailbreak, etc.)
- Raw SQL, GraphQL, Gremlin, or Cypher execution
- Cross-tenant queries from Aether surface
- Unbounded result sets (max 50 per query)
- Time ranges exceeding 90 days

## Backend contract

`POST /v1/noesis/query`

Request:

```json
{
  "message": "Show unresolved alerts for tenant Y.",
  "surface": "kyber",
  "tenant_id": "optional-tenant-id",
  "conversation_id": "optional-conversation-id",
  "context": {
    "current_page": "/noesis",
    "selected_entity_id": "optional-entity-id",
    "selected_entity_type": "optional-entity-type",
    "time_range": "7d",
    "filters": {}
  }
}
```

Response data contains:

- `answer`: concise natural-language answer.
- `mode`: `deterministic`, `llm_text_to_query`, or `fallback`.
- `intent`: allowlisted routed intent.
- `confidence`: classifier/planner confidence from 0 to 1.
- `entities` and `results`: normalized redacted records.
- `graph`: nodes, edges, and highlight ids when graph context is available.
- `actions`: navigation, inspector, graph highlight, or refinement actions.
- `query_debug`: plan/debug details only for authorized Kyber operator contexts.
- `warnings` and `error`: clear guardrail feedback.

Response headers include:

- `x-request-id`: unique request identifier
- `x-correlation-id`: correlation ID for distributed tracing
- `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-reset`: rate limit info (placeholder)

## Safety layer

Every query passes through `_check_safety()` before classification:

1. **Injection detection**: matches against known injection patterns
2. **Write-verb detection**: rejects prompts where a write keyword is the main verb (but allows passive usage like "show deleted alerts")
3. **Read-only guard**: `_assert_read_only()` validates the plan intent and filter values before dispatch

All rejections return a safe `NoesisResponse` with intent `rejected` and a clear error message. They do not raise exceptions.

## Tenant isolation and RBAC

Noesis reads `request.state.tenant`, requires the existing `read` permission, and computes an effective tenant scope before planning. Aether requests always use the authenticated tenant and reject any different `tenant_id`. Kyber requests may only query another tenant when the caller is an admin or has operator-style permission. Repository filters and graph result filtering are applied with the effective tenant id before composing the answer.

## LLM text-to-query seam

The provider seam is intentionally structured-plan-only. A provider returns a `QueryPlan`; Noesis validates that the intent is allowlisted, the tenant id does not change, limits are bounded, filters are supported, time ranges are safe, and the final dispatcher is read-only. If no provider plan is available, Noesis falls back to deterministic routing or a refinement response. Tests use a mocked provider and do not require live API keys.

The `ProductionNoesisPlanProvider` is gated by `NOESIS_LLM_ENABLED` (default false) and includes its own plan validation layer.

## Feature flags

All flags are read from environment variables via `NoesisFlags`:

| Flag | Default | Description |
|---|---|---|
| `NOESIS_ENABLED` | true | Master kill-switch |
| `NOESIS_LLM_ENABLED` | false | LLM provider enabled |
| `NOESIS_DEBUG_ENABLED` | true | Debug info for Kyber |
| `NOESIS_CROSS_TENANT_ENABLED` | true | Cross-tenant queries |
| `NOESIS_RATE_LIMIT_QPM` | 60 | Queries per minute |
| `NOESIS_DAILY_QUOTA` | 1000 | Daily query quota |
| `NOESIS_PROVIDER_TOKEN_BUDGET` | 100000 | LLM token budget |
| `NOESIS_CANARY_TENANTS` | (empty) | Comma-separated canary tenant IDs |

## Audit logging

Every query produces a `NoesisAuditEntry` with structured fields including request_id, tenant context, intent, mode, result count, rejection details, and provider information. Metrics are incremented for key dimensions.

## Redaction

All response payloads are deep-redacted for: api_key, secret, token, password, credentials, key_hash, authorization, session_token, refresh_token, private_key, connection_string, oauth_token, webhook_secret, x_api_key.

## Frontend surfaces

- Kyber `/noesis`: internal operator command workspace with prompts for SDK telemetry, cross-tenant health, unresolved alerts, risky clusters, agent activity, and graph drift.
- Aether `/noesis`: tenant-safe Ask Aether workspace with prompts for user segments, campaigns, abnormal purchase behavior, wallet activity, rewards, and Profile 360 explanation.

Both pages share the `NoesisWorkspace` UI component and render answers, result cards, graph context, actions, deep links, loading state, errors, warnings, and (Kyber-only) debug details.

## Deferred work

- Conversation store exists but is NOT wired into the GA query path. Will be enabled when persistence is standardized.
- Streaming responses deferred until backend supports incremental answer composition.
- Real rate limiting (currently placeholder headers and logging).
- Wire production LLM provider through the existing provider gateway when policy and keys are configured.
