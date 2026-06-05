# Noesis

Noesis is Aether's graph-native natural-language intelligence layer. It exposes shared read-only backend APIs for both Kyber (internal operator console) and Aether (tenant-facing intelligence UI), plus dedicated frontend workspaces in each surface.

## Backend contract

`POST /v1/noesis/query`

Streaming variant: `POST /v1/noesis/query/stream` returns server-sent events with `status`, `answer`, and `final` events. The Aether and Kyber Noesis pages use this streaming endpoint and fall back only if a future client chooses to call the non-streaming query helper. The `final` event is the same normalized Noesis response payload.

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

- `conversation_id`: generated or reused conversation id for follow-up turns.
- `answer`: concise natural-language answer.
- `mode`: `deterministic`, `llm_text_to_query`, or `fallback`.
- `intent`: allowlisted routed intent.
- `confidence`: classifier/planner confidence from 0 to 1.
- `entities` and `results`: normalized redacted records.
- `graph`: nodes, edges, and highlight ids when graph context is available.
- `actions`: navigation, inspector, graph highlight, or refinement actions.
- `query_debug`: plan/debug details only for authorized Kyber operator contexts.
- `warnings` and `error`: clear guardrail feedback.

## Conversation endpoints

Noesis now uses the existing repository/storage pattern for lightweight conversation history:

- `GET /v1/noesis/conversations?surface=aether|kyber&tenant_id=optional`
- `GET /v1/noesis/conversations/{conversation_id}?surface=aether|kyber&tenant_id=optional`
- `POST /v1/noesis/conversations/{conversation_id}/messages`
- `GET /v1/noesis/conversations/export?surface=aether|kyber&tenant_id=optional`
- `DELETE /v1/noesis/conversations/{conversation_id}?surface=aether|kyber&tenant_id=optional`
- `POST /v1/noesis/conversations/purge-expired?retention_days=90&surface=optional` (operator/admin only)

Conversation records store user/assistant turns, a redacted response payload, surface, tenant scope, title, and timestamps. Stored assistant payloads intentionally omit `query_debug`. Export and delete endpoints use the same tenant/RBAC scope checks as history reads. Purge is operator/admin-only and can apply a retention window by surface or across Noesis history.

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

Noesis reads `request.state.tenant`, requires the existing `read` permission, and computes an effective tenant scope before planning or reading conversation history. Aether requests always use the authenticated tenant and reject any different `tenant_id`. Kyber requests may only query or list another tenant when the caller is an admin or has operator-style permission. Repository filters and graph result filtering are applied with the effective tenant id before composing the answer. Query, stream, export, delete, and purge operations emit security audit ledger events and query/export paths enforce lightweight per-tenant Noesis budgets.

## LLM text-to-query seam

The provider seam is intentionally structured-plan-only. A provider returns a `QueryPlan`; Noesis validates that the intent is allowlisted, the tenant id does not change, limits are bounded, and the final dispatcher is read-only. If no provider plan is available, Noesis falls back to deterministic routing or a refinement response. Tests use a mocked provider and do not require live API keys.

Supported configuration:

- `NOESIS_LLM_PLAN_JSON`: local/test JSON `QueryPlan` override.
- `NOESIS_LLM_PROVIDER=openai_compatible`: enables an OpenAI-compatible `/chat/completions` planner.
- `NOESIS_LLM_ENDPOINT`: OpenAI-compatible chat completions endpoint.
- `NOESIS_LLM_API_KEY`: planner API key.
- `NOESIS_LLM_MODEL`: optional model id.

The LLM receives only planner instructions and context; it does not execute any query or tool. Its JSON is parsed into a `QueryPlan` and then validated before read-only dispatch.

## Frontend surfaces

- Kyber `/noesis`: internal operator command workspace with prompts for SDK telemetry, cross-tenant health, unresolved alerts, risky clusters, agent activity, and graph drift.
- Aether `/noesis`: tenant-safe Ask Aether workspace with prompts for user segments, campaigns, abnormal purchase behavior, wallet activity, rewards, and Profile 360 explanation.

Both pages share the `NoesisWorkspace` UI component and render answers, result cards, graph context, actions, deep links, loading state, errors, warnings, conversation history, and (Kyber-only) debug details. Aether's graph page consumes `?entity=` or `?selected_entity=` query params, and Kyber's preserved graph explorer at `/noesis/graph` consumes `?focus=`, `?entity=`, or `?selected_entity=` so Noesis graph actions can deep-link into highlighted/open inspector states.

## Remaining follow-up work

- Add token-level answer streaming if the answer composer becomes incremental; current streaming emits status, answer, and final structured payload events.
- Add provider-gateway-native LLM category support when the shared provider registry grows first-class LLM providers; current support is OpenAI-compatible and fail-closed.
