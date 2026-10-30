---
title: Outcome Ledger
slug: ai/outcome-ledger
section: architecture
visibility: I
audience: [architect, dev-senior, ops, buyer]
status: beta
since_version: 0.1.0
source_files: [services/api/intelligence/intelligence/outcome_ledger.py, services/api/intelligence/intelligence/routes.py, services/api/identity/profile/routes.py]
flags: [AETHER_RECOMMENDATIONS_ENABLED, AETHER_DECISION_RECORDS_ENABLED, AETHER_OUTCOME_FEEDBACK_ENABLED]
related: [ai/decision-outcome-intelligence]
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
source_hashes:
  "services/api/identity/profile/routes.py": "sha256:73c002b436a26ade807bfa2b0ff77a2ee574021ce86dadbdf4ff055b821c0dce"
  "services/api/intelligence/intelligence/outcome_ledger.py": "sha256:8edf9b6a8db71127202f8225cb8b03330eef96f058ae555eb38a7a576cdbf206"
  "services/api/intelligence/intelligence/routes.py": "sha256:dd995bcc1ae4e96d6c073e81c3c2fa28b681bce23ce18a02b1941683625839a5"
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

Every collection is read up to a limit (500 by default, the `limit` query
parameter on `GET /v1/intelligence/outcome-ledger`) with a one-row probe past
it. That route returns a `completeness` block: `limit`, `complete`, and a
per-collection `truncated` map. When `complete` is false the totals, rankings
and rates cover only the first `limit` rows of the truncated collections, and
the tenant Value page says so instead of presenting them as the whole ledger.

Outcome observations retain optional finding and investigation provenance when
they originate from a finding-backed loop, while aggregation continues to use
the existing recommendation/action/outcome repositories.

## Governance and rollout

The ledger is read-only and requires tenant `read` permission. It does not mutate graph records or emit lifecycle events. Feature flags remain disabled by default for gradual rollout.


## Value review and EBR inputs

Outcome Ledger metrics now feed tenant Value Review, customer health, expansion scoring, renewal risk scoring, and EBR generation. Commercial claims should reference observed outcomes and distinguish expected, pending, and observed value.
