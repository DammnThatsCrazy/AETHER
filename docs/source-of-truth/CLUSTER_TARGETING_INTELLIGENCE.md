---
source_files:
  - packages/shared/targeting-intelligence.ts
  - Backend Architecture/aether-backend/services/targeting_intelligence/models.py
  - Backend Architecture/aether-backend/services/targeting_intelligence/policy.py
  - Backend Architecture/aether-backend/services/targeting_intelligence/service.py
  - Backend Architecture/aether-backend/services/targeting_intelligence/leakage.py
  - Backend Architecture/aether-backend/services/targeting_intelligence/routes.py
last_synced_commit: HEAD
---

# Cluster Targeting Intelligence — Source of Truth

## Overview

Observation-first targeting intelligence across Aether tenant UI, Kyber,
Campaign360, Cluster360, Profile360, Path Intelligence, and OODA Suggestion
Intelligence. The product question it answers:

> If I want Cluster A to receive the same kinds of campaigns, suggestions,
> information, or interactions that Clusters C, D, E, and F received, while
> excluding Clusters Z, T, and S — can Aether observe whether that happened,
> whether it worked, whether exclusions leaked, what journey differences
> emerged, and what OODA suggestions should be generated next?

After this implementation the answer is yes.

**Aether does not execute campaigns.** It observes, attributes, recommends,
and exports evidence-backed implementation packages; execution happens in the
tenant's external platforms. `executionByAether` is hard-`false` and
`externalExecutionRequired` hard-`true` on every intent and export — the
backend rejects any payload claiming otherwise.

## Evidence chain (every targeting recommendation traces it)

```txt
TargetingIntent → TargetingEligibilitySnapshot → TargetingObservation
→ TargetingOutcomeSnapshot → Suggestion → Outcome
```

Every object carries `tenant_id`, `evidence_refs`, timestamps
(`as_of`/`observed_at`/`computed_at`), confidence scores, and — where
applicable — `policy_decision_ids`.

## Conflict precedence (strictest safe rule)

`policy.py` resolves cluster/entity rule conflicts in this order — earlier
always wins:

1. `hard_consent_block` (consent absent/revoked)
2. `regulatory_policy_block`
3. `fraud_risk_exclusion`
4. `tenant_manual_exclusion`
5. `holdout_control`
6. `inclusion`
7. `similarity_reference_inclusion`

Every resolution emits an auditable policy decision record referenced from
eligibility snapshots.

## Capabilities

- **Targeting intents** — tenant-declared/provider-observed/suggestion-
  generated/operator-reviewed/system-inferred intents over include/exclude/
  reference/holdout/suppress cluster rules with graph mode + hop depth and
  identity/membership/path/evidence thresholds.
- **Eligibility snapshots** — idempotent per `(tenant, intent, as_of)`;
  cluster member counts; threshold application; recompute-safe.
- **Provider mapping quality** — mapping rate, sync freshness, unresolved
  aliases, touchpoint/identity/cluster resolution rates → `qualityScore`;
  below-threshold quality **blocks targeting suggestions**
  (`blocksSuggestions`) rather than emitting low-confidence advice.
- **Targeting observations** — reached clusters/entities vs the snapshot's
  intended sets, per provider/campaign ref.
- **Exclusion leakage detection** — excluded-but-reached findings with
  leakage rate, likely causes (provider ignored exclusion, wrong audience
  upload, identity resolved after launch, cluster overlap, lookalike
  expansion, UTM mapping error), and severity bands.
- **Holdouts** — measurement/risk/manual/review/validation holdouts with
  contamination tracking; measurement-side incrementality holdouts are
  referenced, not duplicated.
- **Journey deltas** — before/after population-stage deltas per cluster vs
  comparison/holdout clusters; frequency pressure / overexposure scoring;
  negative outcome attribution (unsubscribes, complaints, churn signals,
  fraud signals, refunds, support burden) in correlated — never causal —
  language unless Path Intelligence classification supports stronger claims.
- **Export packages** — evidence-backed implementation packages (include/
  reference/exclude/holdout cluster lists + implementation notes) the tenant
  applies in their own external platform; audited; flag-gated.
- **OODA suggestions** — leakage/overexposure/negative-outcome/similar-
  cluster/holdout-contamination suggestions through the canonical suggestion
  framework, evidence-chained and blocked on poor mapping quality.
- **Recompute/backfill** — idempotent, audited recomputation controls.

## Routes

Tenant (flag `AETHER_CLUSTER_TARGETING_INTELLIGENCE_ENABLED`):
`/v1/targeting-intelligence/*` (intents, snapshots, observations, outcome
snapshots, leakage, holdouts, journey-deltas, exports, suggestions) plus
campaign/cluster-scoped reads `GET /v1/campaigns/{id}/targeting-intelligence`
and `GET /v1/clusters/{id}/targeting-impact` (owned by this package's
routers — campaign/cluster services are untouched).
Kyber (operator-gated; `KYBER_TARGETING_INTELLIGENCE_ENABLED`):
`/v1/admin/kyber/targeting/*` — fleet health, leakage queue, mapping-quality
diagnostics, recompute controls, release readiness, audit trail. Aggregates
never expose raw tenant-private data.

## Frontend

- Aether: Campaign360 **Targeting Intelligence** tab (intended vs observed,
  snapshot summary, leakage findings, mapping quality, copy: "Aether does not
  execute this campaign. Execution happens in your external platforms."),
  Cluster360 **Targeting Impact** tab (funnel, negative outcomes,
  overexposure, journey deltas), targeting suggestion cards with export
  action, export package UI ("This package is for your external platform.
  Aether does not execute it.").
- Kyber: Targeting Intelligence page (fleet health, leakage queue, mapping
  diagnostics, recompute controls, release readiness, audit) + OODA
  Suggestion Command Center targeting evidence drawer.

## Feature flags (default OFF)

`AETHER_CLUSTER_TARGETING_INTELLIGENCE_ENABLED`,
`AETHER_TARGETING_EXPORTS_ENABLED`,
`AETHER_TARGETING_OODA_SUGGESTIONS_ENABLED`,
`KYBER_TARGETING_INTELLIGENCE_ENABLED`.

## Storage

Migration `20260711_targeting_intelligence.py` — store-backing tables for
intents, eligibility snapshots, observations, outcome snapshots, leakage
findings, holdouts, journey deltas, export packages, and audit.

## Governance and safety

- Tenant isolation everywhere; cross-tenant reads are NotFound.
- Consent precedence is absolute; consent-blocked clusters/entities can
  never become eligible regardless of other rules.
- Suggestions are governed proposals; exports are packages, not executions.
- All operator actions (recompute, exports) are audited.

## Testing

`BE/tests/targeting_intelligence/`: conflict-precedence truth table,
non-execution invariants (executionByAether=True rejected), snapshot
idempotency, leakage fixtures + severity banding, holdout honoring, journey
delta math, overexposure, negative outcome counts, export completeness +
immutability, suggestion evidence chains + quality blocking, recompute
idempotency, tenant isolation, flag gating, operator permission, release
readiness. Frontend: Campaign360/Cluster360 tab tests asserting the exact
non-execution copy, suggestion card + export action tests, Kyber page
component tests.

## Known limitations / non-goals

- Impact metrics activate as silver exposure/touchpoint/conversion and
  journey-stage data accumulate; coverage/evidence fields make gaps visible
  rather than inferring.
- No campaign execution, scheduling, sending, bidding, or in-platform
  targeting mutation — ever, under any flag in this release.
