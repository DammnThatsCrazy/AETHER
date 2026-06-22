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
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
last_synced_commit: 70aedff
---
# Outcome Ledger

The Outcome Ledger turns graph-native OODA records into tenant-visible ROI without creating a separate product layer. It aggregates recommendations, decisions, actions, outcomes, and confidence feedback using tenant-scoped repositories.

## APIs

- `GET /v1/intelligence/outcome-ledger`
- `GET /v1/intelligence/outcome-ledger/summary`
- `GET /v1/intelligence/outcome-ledger/by-recommendation-type`
- `GET /v1/intelligence/outcome-ledger/by-playbook`
- `GET /v1/profile/{entity_id}/outcome-ledger`

## Calculations

The ledger reports recommendations generated and viewed, decisions recorded, actions logged, outcomes observed, success/failure/neutral rates, expected value, observed value, value by recommendation type, value by playbook, value by entity, confidence deltas, outcome capture rate, stale loops, incomplete loops, and failed loops.

## Governance and rollout

The ledger is read-only and requires tenant `read` permission. It does not mutate graph records or emit lifecycle events. Feature flags remain disabled by default for gradual rollout.


## Value review and EBR inputs

Outcome Ledger metrics now feed tenant Value Review, customer health, expansion scoring, renewal risk scoring, and EBR generation. Commercial claims should reference observed outcomes and distinguish expected, pending, and observed value.
