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
