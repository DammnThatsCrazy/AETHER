---
title: Noesis Graph Intelligence
slug: internal/noesis
section: architecture
visibility: I
audience: [dev-senior]
status: beta
source_files:
  - Backend Architecture/aether-backend/services/noesis/service.py
  - Backend Architecture/aether-backend/services/noesis/routes.py
  - frontend/shared/src/components/noesis-workspace.tsx
---

# Noesis

Noesis is Aether's graph-native natural-language intelligence layer. It exposes a shared read-only backend endpoint for both Kyber (internal operator console) and Aether (tenant-facing intelligence UI), plus dedicated frontend workspaces in each surface.

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

## Supported deterministic intents

Noesis works without an LLM key by mapping common language into read-only plans:

1. `entity_search`
2. `graph_lookup`
3. `alert_lookup`
4. `tenant_summary` (Kyber only)
5. `profile_lookup`, `wallet_lookup`, `agent_lookup`
6. `health_lookup`
7. `campaign_reward_lookup`
8. `risk_cluster_lookup`

All dispatch happens through existing repositories and the existing graph client. Noesis never executes raw SQL, raw GraphQL, raw Gremlin, mutations, reward execution, tenant modification, or internal operations.

## Tenant isolation and RBAC

Noesis reads `request.state.tenant`, requires the existing `read` permission, and computes an effective tenant scope before planning. Aether requests always use the authenticated tenant and reject any different `tenant_id`. Kyber requests may only query another tenant when the caller is an admin or has operator-style permission. Repository filters and graph result filtering are applied with the effective tenant id before composing the answer.

## LLM text-to-query seam

The provider seam is intentionally structured-plan-only. A provider returns a `QueryPlan`; Noesis validates that the intent is allowlisted, the tenant id does not change, limits are bounded, and the final dispatcher is read-only. If no provider plan is available, Noesis falls back to deterministic routing or a refinement response. Tests use a mocked provider and do not require live API keys.

## Frontend surfaces

- Kyber `/noesis`: internal operator command workspace with prompts for SDK telemetry, cross-tenant health, unresolved alerts, risky clusters, agent activity, and graph drift.
- Aether `/noesis`: tenant-safe Ask Aether workspace with prompts for user segments, campaigns, abnormal purchase behavior, wallet activity, rewards, and Profile 360 explanation.

Both pages share the `NoesisWorkspace` UI component and render answers, result cards, graph context, actions, deep links, loading state, errors, warnings, and (Kyber-only) debug details.

## Follow-up work

- Wire a production OpenAI/Claude-compatible provider through the existing provider gateway when policy and keys are configured.
- Add persisted conversations if a first-class conversation store is standardized.
- Expand graph deep-link query params to support automatic highlight/open-inspector behavior on every destination page.
- Add streaming responses once the backend supports incremental answer composition.
