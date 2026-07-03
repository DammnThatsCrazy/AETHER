---
title: Agentic Graph Backlog Runbook
owners:
  - agentic-observability
last_synced_commit: pending
---

# Agentic Graph Backlog Runbook

Agentic graph projection is intentionally asynchronous. Accepted observations are
written to Bronze/Silver/canonical activity first, then graph mutations are stored
in `agentic_projection_outbox` for worker projection.

## Detection

A backlog exists when queued or failed `agentic_projection_outbox` records grow for
a tenant while ingestion remains healthy.

Check by tenant:

```bash
python -m services.agentic_observability.outbox_worker --tenant-id <tenant_id>
```

The worker requires an explicit tenant scope. Do not run unscoped cross-tenant
projection jobs.

## Triage

1. Confirm the observation API is accepting events.
2. Confirm `bronze_agentic_observations` contains the source events.
3. Confirm typed Silver rows and `canonical_activity` rows exist for the same
   `source_event_id`.
4. Inspect queued, failed, and dead-lettered rows in `agentic_projection_outbox`.
5. Check `last_error_code` and `last_error_message` for graph connectivity or
   contract validation failures.

## Recovery

1. Restore Neptune or graph service availability.
2. Re-run the tenant-scoped worker.
3. Verify rows move from `queued`/`failed` to `completed`.
4. Dead-lettered rows require operator review before replay.

## Safety invariant

The graph worker projects Aether-owned graph mutations only. It never executes
external provider actions, signs provider requests, sends messages, posts
content, trades, settles, or revokes access.
