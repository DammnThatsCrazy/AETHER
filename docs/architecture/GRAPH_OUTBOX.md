---
title: Agentic Graph Outbox
slug: architecture/agentic-graph-outbox
section: architecture
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/pipeline.py
  - Backend Architecture/aether-backend/repositories/agentic_observability_repos.py
---

# Agentic Graph Outbox

The PR-2 foundation introduces `agentic_projection_outbox` for generic agent observations. Request routes persist graph projection work as queued outbox records instead of performing untracked direct graph writes.

Each outbox record includes tenant, source event, canonical activity, mutation domain, mutation type, payload, idempotency key, status, attempt counters, timestamps, and error fields. The current route response uses `graph_projection_status=outbox_queued` when graph work has been durably queued.

Worker retry, exponential backoff, dead-letter handling, and Kyber replay controls are intentionally left for the next PR-2 hardening slice.

## Worker behavior

`services/agentic_observability/outbox_worker.py` processes only tenant-scoped
`graph` domain records with `queued` or `failed` status. Successful records move
to `completed`; repeated failures record `last_error_code`, `last_error_message`,
`next_attempt_at`, and eventually `dead_lettered_at` after the retry limit. The
worker rejects unscoped runs so graph projection cannot accidentally scan across
tenants.

## Migration

The formal Alembic migration `20260703_agentic_observability_pipeline.py` creates
the Bronze, typed Silver, and projection outbox tables with tenant, time,
lineage, and idempotency indexes. The existing JSONB repository compatibility
layer can continue writing `id`, `tenant_id`, and `data` while typed projectors
adopt the first-class columns.
