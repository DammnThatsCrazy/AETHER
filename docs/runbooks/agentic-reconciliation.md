---
title: Agentic Reconciliation Runbook
slug: operations/agentic-reconciliation
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: experimental
since_version: "8.11.0"
---

# Agentic Reconciliation Runbook

Aether reconciliation is read-only by default. It compares accepted agentic
Bronze observations with typed Silver facts, canonical activity, and graph outbox
records so operators can see missing pipeline stages without replaying or
mutating provider systems.

## Kyber diagnostics

Use tenant-scoped Kyber endpoints:

```bash
GET /v1/admin/kyber/agentic-observability/pipeline-health
GET /v1/admin/kyber/agentic-observability/lineage/{source_event_id}
POST /v1/admin/kyber/agentic-observability/reconcile
```

`pipeline-health` returns Bronze, Silver, canonical activity, outbox status, and
backlog counts for the active tenant. `lineage` explains one source event across
pipeline stages. `reconcile` scans recent Bronze records and reports stage gaps.

## Gap meanings

| Gap | Meaning | Typical action |
| --- | --- | --- |
| `bronze_missing` | No accepted source event exists for the event id. | Verify ingestion and tenant scope. |
| `silver_missing` | Bronze exists but no typed Silver fact exists. | Review normalizer/projector errors before replay. |
| `canonical_activity_missing` | Silver may exist but journey/profile activity lineage is missing. | Re-run canonical activity projector after review. |
| `graph_outbox_missing` | Activity exists but no graph projection work was queued. | Rebuild graph outbox from Silver after review. |

## Safety invariant

Diagnostics and reconciliation do not execute provider actions, sign provider
requests, send messages, post content, trade, settle, or revoke access. They only
read Aether pipeline state and report evidence-backed gaps.
