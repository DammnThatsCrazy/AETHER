---
title: Agentic Ingestion Pipeline
slug: architecture/agentic-ingestion-pipeline
section: architecture
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/pipeline.py
  - Backend Architecture/aether-backend/services/agentic_observability/routes.py
  - Backend Architecture/aether-backend/repositories/agentic_observability_repos.py
---

# Agentic Ingestion Pipeline

Aether's agentic ingestion pipeline is observation-first. It accepts externally observed agent activity and records enough lineage to replay, project, and audit it without executing external actions.

Current PR-2 foundation flow for generic agent observations:

```text
/v1/observability/agent/events
→ AgenticIngestionPipeline
→ bronze_agentic_observations
→ silver_agent_*_facts
→ canonical_activity
→ agentic_projection_outbox
```

## Guarantees in this slice

- Authenticated tenant context remains authoritative before the pipeline is called.
- Accepted generic agent observations are written to sanitized Bronze storage.
- A typed Silver fact row is selected by event family:
  - `silver_agent_tool_invocation_facts`
  - `silver_mcp_connection_facts`
  - `silver_agent_risk_facts`
  - `silver_agent_activity_facts`
- Relevant observations create `canonical_activity` rows with `activity_family=agent`.
- Graph mutations are no longer written directly from the generic agent event route; they are persisted to `agentic_projection_outbox` with `status=queued`.
- Sensitive credential-like keys are redacted before Bronze payload persistence.

## Remaining PR-2 hardening

- Add formal SQL migrations for every typed agentic Silver table.
- Route all compatibility observability endpoints through the same pipeline.
- Add workerized graph outbox draining, retry, backoff, dead-letter, replay, and reconciliation APIs.
- Add batch ingestion, signatures, quotas, and tenant rate limits.

## Formal storage migration

`Backend Architecture/aether-backend/alembic/versions/20260703_agentic_observability_pipeline.py`
adds the first formal PR2 table set for agentic observations. It creates
sanitized Bronze lineage, provider-neutral Silver fact tables, and a durable
projection outbox with tenant, idempotency, source-event, trace, provider,
authorization, and lifecycle indexes.

## Graph projection worker

`services/agentic_observability/outbox_worker.py` is the first tenant-scoped
consumer for `agentic_projection_outbox`. It deserializes recorded vertex and edge
mutations, writes them through the shared graph client, marks successful records
`completed`, and records retry/dead-letter state on failure. It is deliberately
limited to graph projection and does not execute external provider actions.
