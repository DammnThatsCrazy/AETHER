---
source_files:
  - Backend Architecture/aether-backend/services/suggestions/models.py
  - Backend Architecture/aether-backend/services/suggestions/lifecycle.py
  - Backend Architecture/aether-backend/services/suggestions/scorer.py
  - Backend Architecture/aether-backend/services/suggestions/policy.py
  - Backend Architecture/aether-backend/services/suggestions/service.py
  - Backend Architecture/aether-backend/services/suggestions/routes.py
  - Backend Architecture/aether-backend/services/suggestions/events.py
  - Backend Architecture/aether-backend/services/suggestions/dispatcher.py
  - Backend Architecture/aether-backend/services/suggestions/outcome.py
  - Backend Architecture/aether-backend/config/settings.py
  - packages/shared/suggestions.ts
last_synced_commit: HEAD
---

# OODA Suggestion Intelligence — Source of Truth

## Overview

The Suggestion Intelligence layer is AETHER's unified OODA (Observe → Orient → Suggest → Review → Approve → Execute → Measure → Learn → Close) lifecycle engine. It binds all intelligence primitives — Noesis, Recommendations, Notification Intelligence, Data Quality, SDK Health/Drift, Governance, and Realtime — into a single canonical `Suggestion` entity with full lifecycle management.

**Readiness target:** production-grade, governed, auditable, tenant-scoped, safe by default.

---

## 1. OODA Lifecycle Phases

| Phase | Statuses | Description |
|-------|----------|-------------|
| Observe | `detected` | Raw signal detected from a source adapter |
| Orient | `oriented` | Signal classified and enriched |
| Suggest | `suggested`, `delivered` | Presented to tenant or operator |
| Review | `review_required`, `approved`, `rejected`, `suppressed` | Human gate for high-risk actions |
| Act | `executing`, `executed`, `failed` | Automated or approved execution |
| Measure | `measured` | Outcome captured and scored |
| Learn | `learned` | Learning signal fed back to source |
| Closed | `closed`, `expired` | Terminal state |

---

## 2. Canonical Status Transitions

```
detected → oriented → suggested → review_required → approved → executing → executed → measured → learned → closed
                   ↘             ↗                 ↘ rejected → closed
                    delivered                       ↘ suppressed → closed
                         ↘ measured → closed
```

Full legal transition table is defined in `services/suggestions/lifecycle.py:LEGAL_TRANSITIONS`.

**Key invariants:**
- `requires_approval=True` blocks `suggested → approved` shortcut; must go through `review_required` first.
- `closed` is terminal: no transitions out.
- `reviewed_at` and `reviewed_by` are set on `approved`, `rejected`, `suppressed`.
- `closed_at` is set on `closed`.
- Every transition appends an immutable `SuggestionAuditEvent` to `audit_trail`.

---

## 3. Priority Scoring

Priority score formula (all inputs clamped to [0.0, 1.0]):

```
priority_score = (
    impact_score       * 0.30
  + confidence_score   * 0.20
  + urgency_score      * 0.20
  + evidence_quality   * 0.15
  + tenant_value       * 0.15
  - risk_score         * reversibility_penalty
)
```

Reversibility penalties:
- `reversible=True` → penalty 0.20
- `reversible=False` → penalty 0.40
- `reversible=None` → penalty 0.30

Priority thresholds:
- score ≥ 0.90 → P0
- score ≥ 0.75 → P1
- score ≥ 0.50 → P2
- score ≥ 0.25 → P3
- score < 0.25 → info

Class floor overrides (minimum priority regardless of score):
- `SECURITY`, `RELIABILITY`, `IDENTITY`, `GRAPH_HEALTH`, `GOVERNANCE` → minimum P1

---

## 4. Approval Policy

Requires human approval when **any** of these conditions hold:
- `suggestion_class` ∈ {SECURITY, GOVERNANCE, IDENTITY, GRAPH_HEALTH, RELIABILITY}
- `risk_score ≥ 0.7`
- `reversible = False`
- Subject is external-facing (delivery beyond the platform boundary)
- Graph-mutating actions

Policy evaluation is performed by `services/suggestions/policy.py:evaluate_suggestion_policy()`, which returns a `SuggestionPolicyDecision` stored on the `Suggestion.policy_decision` field.

---

## 5. Tenant Isolation

Every query, storage operation, event, cache key, realtime message, and frontend response is scoped by `tenant_id`. The `SuggestionRepository` enforces:

```python
# Every query includes tenant_id filter — no exceptions
filters = {"tenant_id": tenant_context.tenant_id, ...}
```

Tenant A **cannot** read, modify, or receive events from Tenant B's suggestions.

---

## 6. Secret Redaction

All responses passing through the tenant-facing API surface are redacted:

**`redact_for_tenant()`** removes:
1. **Operator-only fields:** `operator_notes`, `source_ref`, `lineage_event_ids`, `graph_refs`, `profile_refs`, `journey_refs`, `audit_trail`, `policy_decision`
2. **Sensitive keys (recursive deep-redact):** `api_key`, `key_hash`, `secret`, `token`, `password`, `credentials`, `authorization`, `session_token`, `refresh_token`, `private_key`, `connection_string`, `oauth_token`, `webhook_secret`, `x_api_key`, `client_secret`, `access_token`, `bearer`, `cookie`, `set_cookie`, `operator_context`

---

## 7. Noesis Integration (Read-Only)

Noesis handles 5 suggestion-specific read-only intents:

| Intent | Description |
|--------|-------------|
| `suggestion_lookup` | List open suggestions for a subject/filter |
| `suggestion_summary` | Count totals by class, priority, status |
| `suggestion_review_queue` | List `review_required` suggestions |
| `suggestion_explain` | Explain a specific suggestion (what/why/impact) |
| `suggestion_outcome_lookup` | Show recorded outcome for a suggestion |

**Noesis MUST NOT:** approve, reject, execute, suppress, or mutate suggestion state. These constraints are enforced in `services/noesis/service.py:_suggestion_dispatch()`.

---

## 8. Source Adapters

| Adapter | Source | Key behavior |
|---------|--------|-------------|
| `notification_adapter.py` | Notification Intelligence | Maps delivery events → suggestions; idempotent via source_ref |
| `recommendation_adapter.py` | Recommendation engine | Maps retarget recs → suggestions; idempotent via rec_id |
| `data_quality_adapter.py` | Data Quality drift events | P0/P1 for critical drift; suppresses low-severity noise |
| `sdk_health_adapter.py` | SDK Health monitoring | SDK silence (P1) and ingestion failure (P0/P1) |
| `sdk_drift_adapter.py` | SDK Drift incidents | REPLAY_STORM (P1/P2), SCHEMA_DRIFT (P2), STALENESS (P3) |
| `graph_adapter.py` | Graph events | identity_merge_candidate requires approval; GRAPH_HEALTH class |
| `profile360_adapter.py` | Profile 360 | stale profile (P3), churn risk (P2), LTV opportunity (P2/P3) |
| `governance_adapter.py` | Governance decisions | ≥3 policy denials → P1/P2 security suggestion; requires approval |
| `reliability_adapter.py` | SLO breaches | SLO breach → P0/P1 reliability suggestion |
| `noesis_adapter.py` | Noesis NL queries | Read-only query delegation; no mutation |

All adapters implement idempotency via `find_by_source_ref(tenant_id, source, source_id)` before creating.

---

## 9. Event Topics

All suggestion lifecycle transitions emit events on these topics (defined in `shared/events/events.py`):

```
aether.suggestions.detected
aether.suggestions.oriented
aether.suggestions.created
aether.suggestions.review_required
aether.suggestions.approved
aether.suggestions.rejected
aether.suggestions.suppressed
aether.suggestions.executing
aether.suggestions.executed
aether.suggestions.delivered
aether.suggestions.outcome_recorded
aether.suggestions.closed
aether.suggestions.failed
aether.suggestions.expired
```

Events are non-blocking: failures are logged as warnings and never corrupt persisted state.

---

## 10. Realtime Channels

| Channel | Permission | Description |
|---------|-----------|-------------|
| `suggestions.feed` | read | All lifecycle transitions |
| `suggestions.review` | read | Review-required and approval events |
| `suggestions.outcomes` | read | Outcome recorded events |

---

## 11. API Routes

### Tenant routes (`/v1/suggestions/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/suggestions` | List open suggestions |
| POST | `/v1/suggestions/query` | Query with body-based filters |
| GET | `/v1/suggestions/summary` | Summary counts |
| GET | `/v1/suggestions/review-queue` | Review queue |
| GET | `/v1/suggestions/{id}` | Get suggestion |
| POST | `/v1/suggestions/{id}/approve` | Approve |
| POST | `/v1/suggestions/{id}/reject` | Reject (requires reason) |
| POST | `/v1/suggestions/{id}/suppress` | Suppress |
| POST | `/v1/suggestions/{id}/execute` | Execute (requires approval + flag) |
| POST | `/v1/suggestions/{id}/deliver` | Deliver |
| POST | `/v1/suggestions/{id}/outcome` | Record outcome |
| GET | `/v1/suggestions/{id}/audit` | Audit trail |

### Kyber operator routes (`/v1/admin/kyber/suggestions/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/admin/kyber/suggestions` | Cross-tenant list |
| GET | `/v1/admin/kyber/suggestions/summary` | Cross-tenant summary |
| GET | `/v1/admin/kyber/suggestions/review-queue` | Cross-tenant review queue |
| GET | `/v1/admin/kyber/suggestions/quality` | Quality report |
| GET | `/v1/admin/kyber/suggestions/outcomes` | Outcomes tracker |

### Aether tenant-safe routes (`/v1/aether/suggestions/`)
All responses are redacted via `redact_for_tenant()`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/aether/suggestions` | Tenant-safe list |
| GET | `/v1/aether/suggestions/{id}` | Tenant-safe detail |
| POST | `/v1/aether/suggestions/{id}/feedback` | Submit feedback |

---

## 12. Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `AETHER_SUGGESTIONS_ENABLED` | `false` | Master switch |
| `AETHER_SUGGESTIONS_AUTODELIVERY_ENABLED` | `false` | Auto-deliver approved suggestions |
| `AETHER_SUGGESTIONS_EXECUTION_ENABLED` | `false` | Allow execution (explicit opt-in required) |
| `AETHER_SUGGESTIONS_NOESIS_ENABLED` | `true` | Noesis suggestion intent handling |
| `AETHER_SUGGESTIONS_RECOMMENDATION_ADAPTER_ENABLED` | `true` | Recommendation adapter |
| `AETHER_SUGGESTIONS_NOTIFICATION_ADAPTER_ENABLED` | `true` | Notification adapter |
| `AETHER_SUGGESTIONS_DATA_QUALITY_ADAPTER_ENABLED` | `true` | Data quality adapter |
| `AETHER_SUGGESTIONS_SDK_HEALTH_ADAPTER_ENABLED` | `true` | SDK health adapter |
| `AETHER_SUGGESTIONS_GRAPH_ADAPTER_ENABLED` | `true` | Graph adapter |
| `KYBER_SUGGESTIONS_ENABLED` | `true` | Kyber operator routes |
| `AETHER_TENANT_SUGGESTIONS_ENABLED` | `true` | Tenant-safe routes |

**Execution is disabled by default.** `AETHER_SUGGESTIONS_EXECUTION_ENABLED=false` must be explicitly set to `true` before any automated execution can occur.

---

## 13. TypeScript Contracts

All frontend contracts are defined in `packages/shared/suggestions.ts`:

- `OodaPhase` — union of 8 lifecycle phases
- `SuggestionStatus` — union of 15 statuses
- `SuggestionClass` — union of 17 intelligence classes
- `SuggestionSource` — union of 15 signal sources
- `SuggestionPriority` — P0 | P1 | P2 | P3 | info
- `Suggestion` — full entity interface
- `TenantSafeSuggestion` — redacted tenant view (no operator fields)
- `SuggestionQueryRequest`, `SuggestionSummary` — query/aggregate interfaces
- Action requests: `SuggestionApproveRequest`, `SuggestionRejectRequest`, `SuggestionSuppressRequest`, `SuggestionFeedbackRequest`, `SuggestionOutcomeRequest`

Realtime channel additions are in `packages/shared/operational-intelligence.ts`:
- `RealtimeChannel`: `suggestions.feed | suggestions.review | suggestions.outcomes`
- `IntelligenceEventName`: 14 `suggestion.*` event names added
