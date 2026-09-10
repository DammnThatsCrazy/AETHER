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
source_hashes:
  "Backend Architecture/aether-backend/services/intelligence/outcome_ledger.py": "sha256:8edf9b6a8db71127202f8225cb8b03330eef96f058ae555eb38a7a576cdbf206"
  "Backend Architecture/aether-backend/services/intelligence/routes.py": "sha256:c9c080216395b71d176710000889bc5d4d8a108c829f61cc7d61fa6840f7cb20"
  "Backend Architecture/aether-backend/services/profile/routes.py": "sha256:f51979fa82968ca97bdac3520fd411b20e578c1734547077c594be2c42a6ed4f"
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

Action and graph evidence remains tenant-safe at the boundary: graph
neighbours are filtered before aggregation limits, and an action dispatch is
reserved idempotently before a connector can be called. A queued plan or a
failed connector is represented as such; the ledger does not turn it into an
observed delivery or fabricate provider evidence.

Outcome observations retain optional finding and investigation provenance when
they originate from a finding-backed loop, while aggregation continues to use
the existing recommendation/action/outcome repositories.

## Governance and rollout

The ledger is read-only and requires tenant `read` permission. It does not mutate graph records or emit lifecycle events. Feature flags remain disabled by default for gradual rollout.


## Value review and EBR inputs

Outcome Ledger metrics now feed tenant Value Review, customer health, expansion scoring, renewal risk scoring, and EBR generation. Commercial claims should reference observed outcomes and distinguish expected, pending, and observed value.
