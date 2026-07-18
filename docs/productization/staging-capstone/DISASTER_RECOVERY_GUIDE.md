---
title: "Disaster Recovery Guide"
slug: productization/staging-capstone/disaster-recovery-guide
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 7
toc_depth: 2
---

# Disaster Recovery Guide

Recovery objectives and per-subsystem procedures. Many of the recovery
BEHAVIORS below are proven credentiallessly in `tests/chaos/`; this guide maps
them to a real incident and to the live procedures that finish the job.

## Objectives (targets, not yet validated at scale)

- **RPO:** durable stores (Postgres, ClickHouse, S3) are the system of record;
  target RPO is the backing store's backup interval. In-memory state is
  reconstructable from durable stores and provider re-scan.
- **RTO:** target is a redeploy plus store restore. Not yet timed against a real
  staging failover — record it during the first staging DR drill.

## Per-subsystem recovery

### Ingest / event bus
The durable event-outbox relay is at-least-once by construction: a crash between
publish and mark republishes on lease reclaim, and every consumer is idempotent
(covered by `tests/chaos/test_infra_interruptions.py` and
`tests/unit/test_outbox_relay.py`). Recovery = restart relay workers; leases
expire and are reclaimed. No manual replay needed for in-flight rows.

### Redis / cache outage
Cache-aside reads degrade to the origin loader on a hard Redis outage; the
system stays correct, just slower (proven in
`tests/chaos/test_infra_interruptions.py`). Recovery = restore Redis; cache
re-warms. Do not fail requests on a cache miss.

### ClickHouse / analytics outage
Analytics writes buffer during the outage and flush on recovery without loss
(proven in `tests/chaos/`). If the buffer bound is exceeded, spill to the
durable queue; never drop rows silently.

### Chain observers (stablecoin / interop / derivatives)
Scanning is checkpointed. On restart, resume from the checkpoint; reorgs rewind
below the fork and re-observe; rate-limited RPC degrades and resumes
(`tests/chaos/test_chain_observers.py`). Recovery = restore RPC endpoints and
let the observers catch up.

### Reward delivery
Durable outbox: undelivered jobs resume on worker restart; dead-lettered jobs
are replayed by operator `redeliver` once the downstream recovers
(`REWARD_DELIVERY_RUNBOOK`). A reward is never falsely marked delivered.

### Graph / agent mutations
Staged mutations and their commit status are durable. A failed commit is
recorded (`failed_commit`), never half-applied; a rollback that could not
restore state is `rollback_repair_required` with a repair task
(`AGENT_RUNTIME_MUTATION_REVIEW_RUNBOOK`). Recovery = work the repair queue.

## DR drill checklist

1. Restore durable stores from backup into an isolated environment.
2. Redeploy; run `scripts/staging_preflight.py`.
3. Restart workers; confirm outbox/relay drains and observers resume from
   checkpoints.
4. Reconcile per domain; record RTO/RPO actuals.

## Never do

- Never hand-edit durable state to "speed up" recovery.
- Never disable idempotency/lease checks during an incident.
- Never mark recovery complete without a reconciliation pass.

See also: `STAGING_DEPLOYMENT_GUIDE.md`, `docs/runbooks/` (per-domain),
`tests/chaos/`.
