---
title: Outcome Ledger
slug: ai/outcome-ledger
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops, exec]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/outcome_ledger.py
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/profile/routes.py
flags:
  - AETHER_RECOMMENDATIONS_ENABLED
  - AETHER_DECISION_RECORDS_ENABLED
  - AETHER_OUTCOME_FEEDBACK_ENABLED
related:
  - ai/decision-outcome-intelligence
  - ai/recommendation-families
  - ai/investigation-workspace
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
---
# Outcome Ledger

The Outcome Ledger turns graph-native Decision & Outcome Intelligence records into tenant-visible ROI. It aggregates recommendations, decisions, actions, outcomes, and confidence feedback from the existing OODA repositories; it does not introduce a separate product layer.

## Endpoints

- `GET /v1/intelligence/outcome-ledger` — full tenant ledger with summary, items, groupings, confidence deltas, and loop ids.
- `GET /v1/intelligence/outcome-ledger/summary` — tenant-level summary metrics for dashboards.
- `GET /v1/intelligence/outcome-ledger/by-recommendation-type` — value and outcome distribution grouped by recommendation type.
- `GET /v1/intelligence/outcome-ledger/by-playbook` — value and outcome distribution grouped by playbook run membership.
- `GET /v1/profile/{entity_id}/outcome-ledger` — entity-level recommendations, decisions, actions, outcomes, value, and confidence deltas.

## Metric definitions

- **Recommendations generated/viewed**: recommendation rows for the tenant and rows whose status indicates a view or decision.
- **Decisions recorded**: tenant-scoped `DecisionRecord` rows linked to recommendations.
- **Actions logged**: tenant-scoped `ActionFeedback` rows linked through decisions.
- **Outcomes observed**: tenant-scoped `OutcomeObservation` rows.
- **Success/failure/neutral count and rate**: outcome label counts and count divided by observed outcomes.
- **Outcome capture rate**: unique recommendations with outcomes divided by generated recommendations.
- **Expected value**: sum of recommendation expected values.
- **Observed value**: sum of outcome values.
- **Pending value**: expected value minus observed value, floored at zero.
- **Confidence deltas over time**: recommendation feedback confidence deltas ordered by feedback timestamp.
- **Stale loops**: recommendations older than the stale threshold with no outcome.
- **Incomplete loops**: recommendations missing a decision, action, or outcome.
- **Failed loops**: recommendations with at least one failure outcome.

## Tenant value

The ledger lets a tenant answer: what did Aether recommend, what did the tenant decide, what action was taken, what outcome happened, what value was created, whether confidence improved, and which loops need follow-up. This makes the OODA loop commercially legible without bypassing approval or audit controls.

## Governance constraints

Ledger endpoints require tenant `read` permission, filter all repository reads by tenant id, and do not mutate rows, graph edges, or lifecycle events. Existing decision approval checks, action execution constraints, outcome/recommendation matching, and elevated/critical authorization metadata requirements remain enforced by the write APIs that create the source records.

## Feature flags and rollout

The source OODA capabilities remain behind the gradual-rollout flags:

- `AETHER_RECOMMENDATIONS_ENABLED`
- `AETHER_DECISION_RECORDS_ENABLED`
- `AETHER_OUTCOME_FEEDBACK_ENABLED`
- `AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD`

Roll out preview first for read-only analyst exploration, then enable persisted generation for write-scoped users, then enable decisions/actions/outcomes so the ledger can show capture rate and value.

## Family-aware value views

Outcome Ledger groupings by recommendation type show which recommendation families create value, which families are ignored, and which loops are stale, incomplete, or failed. Investigation links let analysts move from ledger anomalies back to evidence, decisions, actions, outcomes, and confidence updates.

## Playbook value linkage

Outcome Ledger aggregations include playbook-linked recommendation IDs so tenants can connect observed value and pending value back to reusable workflows. Playbook performance uses the same tenant-scoped recommendation, decision, action, outcome, and feedback repositories as the ledger. See [Playbooks](./PLAYBOOKS.md).
