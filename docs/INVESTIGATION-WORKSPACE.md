---
title: Investigation Workspace
slug: ai/investigation-workspace
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/investigations.py
  - Backend Architecture/aether-backend/services/intelligence/routes.py
flags:
  - AETHER_RECOMMENDATIONS_ENABLED
  - AETHER_DECISION_RECORDS_ENABLED
  - AETHER_OUTCOME_FEEDBACK_ENABLED
related:
  - ai/decision-outcome-intelligence
  - ai/recommendation-families
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
last_synced_commit: "a681289"
---
# Investigation Workspace

Every recommendation can be opened as an investigation workspace without leaving Aether. The workspace is read-only, tenant-scoped, and composed from the existing OODA records and graph/profile/evidence references.

## Endpoint

`GET /v1/intelligence/recommendations/{recommendation_id}/investigation`

The response includes the recommendation, confidence breakdown, evidence, related profile/entity summary, related graph edges when available, related events, attribution path, candidate actions, decision history, action history, outcome history, prior similar tenant outcomes, governance flags, data freshness, and suppression reason.

When the recommendation carries canonical path references (populated by `_compute_path_refs` in the recommendation family), the workspace also returns:
- `graph_paths` — list of canonical `path_id` strings (SHA256[:32]) linking to saved `TraversalSnapshot` records
- `snapshot_ref` — the `snapshot_id` of the traversal snapshot most relevant to this recommendation

## Tenant isolation

The route first verifies that the recommendation belongs to the authenticated tenant. Decision, action, outcome, and prior outcome reads are filtered by tenant id. Optional graph lookup degrades gracefully and filters tenant-tagged neighbors when graph context is present.

## Governance and rollout

Investigation is read-only and requires `read` permission. It does not approve, execute, mutate graph state, emit lifecycle events, or bypass elevated/critical authorization metadata requirements. Roll out after recommendation preview so analysts can inspect evidence before deciding whether to persist and act on generated recommendations.
