---
title: Noesis Graph Intelligence
slug: internal/noesis
section: architecture
visibility: I
audience: [dev-senior]
status: stable
source_files:
  - Backend Architecture/aether-backend/services/noesis/service.py
  - Backend Architecture/aether-backend/services/noesis/routes.py
  - Backend Architecture/aether-backend/services/noesis/models.py
  - Backend Architecture/aether-backend/services/noesis/provider.py
  - Backend Architecture/aether-backend/services/noesis/flags.py
  - frontend/shared/src/components/noesis-workspace.tsx
last_synced_commit: "60a5c024"
---

# Noesis

Noesis is Aether's graph-native natural-language intelligence layer. It exposes a shared read-only backend endpoint for both Kyber (internal operator console) and Aether (tenant-facing intelligence UI), plus dedicated frontend workspaces in each surface.

**Status:** Production (GA). Phase 0 (stabilize beta), Phase 1 (production deterministic Noesis), Phase 2 (LLM-assisted planner), and Phase 3 (rate limiting, canary gating, conversation persistence) are complete.

## GA contract

### Supported intents (30)

The allowlist in `models.py::SUPPORTED_INTENTS` covers the ten original GA
intents plus the read-only domain families added since. Every intent is
read-only, tenant-scoped, and resolved through a repository or read-only
adapter — never a write path.

**Core GA surface intents (10)**

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

**Communications Intelligence** (read-only, evidence-backed)

| Intent | Description |
|---|---|
| `communications_insight` | Evidence-backed communications intelligence: deliverability, human-qualified engagement, machine-activity inflation, campaign resolution coverage |

**Suggestion Intelligence** (read-only — Noesis never mutates suggestions)

| Intent | Description |
|---|---|
| `suggestion_lookup` | Look up individual suggestion records |
| `suggestion_summary` | Summarize suggestion activity and acceptance rates |
| `suggestion_review_queue` | Show the pending suggestion review queue |
| `suggestion_explain` | Explain the rationale behind a specific suggestion |
| `suggestion_outcome_lookup` | Look up outcomes and results for processed suggestions |

**Semantic-Sentiment Intelligence** (read-only)

| Intent | Description |
|---|---|
| `sentiment_explain` | Explain tenant-scoped, target-specific sentiment with evidence, freshness, model versions, and causal-confidence labels |
| `narrative_analysis` | Analyze tenant-scoped narratives, claims, adoption, rejection, and diffusion without unsupported causal claims |
| `semantic_profile_explain` | Summarize semantic state, stance, intent, active topics, evidence, and freshness for a Profile360 entity |

**Economic & Interoperability Intelligence** (read-only, flag-gated)

| Intent | Description |
|---|---|
| `stablecoin_flow_lookup` | Summarize observed stablecoin flow aggregates and peg status, including depeg signals |
| `derivatives_exposure_lookup` | Report observed derivatives positions and P&L snapshots (observation-only) |
| `derivatives_reconciliation_lookup` | Show reconciliation variances between venue-reported and projected derivatives state, plus unrecovered stream gaps |
| `interop_message_trace` | Trace a cross-chain message's observed lifecycle by correlation key or message id (observation-only) |
| `interop_path_reliability` | Summarize delivery outcomes per cross-chain path (delivered / failed / in-flight) |

**Observability Intelligence** (read-only)

| Intent | Description |
|---|---|
| `import_status_lookup` | Report observed tenant import sessions and lifecycle status |
| `job_status_lookup` | Summarize observed background jobs and status distribution |
| `measurement_integrity_lookup` | Report observed measurement results and value_state distribution (never recomputes or relabels a metric; a missing value is never reported as zero) |

**Risk360 / Fraud360 Intelligence** (read-only, flag-gated — default OFF)

| Intent | Description |
|---|---|
| `risk_assessment_explain` | Explain the stored Risk360 assessment for a subject: which risk dimensions are scored (with value states), the consolidated claim_state, the referenced decision policy, and any exposure summary. Requires `AETHER_RISK360_ENABLED` |
| `fraud_hypothesis_summarize` | Summarize stored Fraud360 hypotheses for a subject: matched pattern display names/families, lifecycle state and phase, materiality when set, and risk/network/flow/decision cross-references. Requires `AETHER_FRAUD360_ENABLED` |
| `risk_fraud_contradiction_lookup` | Surface honest contradictions or gaps between a subject's stored Risk360 assessment and its stored Fraud360 hypotheses (e.g., a material/confirmed fraud hypothesis whose subject's assessment has no scored fraud dimension). Requires both planes enabled |

These three intents are served by the `RiskFraudNoesisAdapter`
(`services/noesis/adapters/risk_fraud_adapter.py`) — read/list paths only over
`RiskAssessmentRepository` and `FraudHypothesisRepository`, plus the declarative
`FRAUD_PATTERNS` registry for display names. Noesis never creates, updates, or
relabels an assessment or hypothesis; absent data returns an honest
`sufficient=False` (a read that raises returns the same rather than crashing the
surface), and a disabled plane surfaces a `service_disabled` NoesisError in the
response.

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

The Risk360 / Fraud360 Intelligence intents are **not** gated by `NoesisFlags` —
they follow the platform's `risk_fraud_360` convergence flags
(`AETHER_RISK360_ENABLED` / `AETHER_FRAUD360_ENABLED`, both default OFF), read
from `settings.risk_fraud_360` in `service.py::_risk_fraud_dispatch`.

## Audit logging

Every query produces a `NoesisAuditEntry` with structured fields including request_id, tenant context, intent, mode, result count, rejection details, and provider information. Metrics are incremented for key dimensions.

## Redaction

All response payloads are deep-redacted for: api_key, secret, token, password, credentials, key_hash, authorization, session_token, refresh_token, private_key, connection_string, oauth_token, webhook_secret, x_api_key.

## Frontend surfaces

- Kyber `/noesis`: internal operator command workspace with prompts for SDK telemetry, cross-tenant health, unresolved alerts, risky clusters, agent activity, and graph drift.
- Aether `/noesis`: tenant-safe Ask Aether workspace with prompts for user segments, campaigns, abnormal purchase behavior, wallet activity, rewards, and Profile 360 explanation.

Both pages share the `NoesisWorkspace` UI component and render answers, result cards, graph context, actions, deep links, loading state, errors, warnings, and (Kyber-only) debug details.

## Deferred work

- Streaming responses deferred until backend supports incremental answer composition.
