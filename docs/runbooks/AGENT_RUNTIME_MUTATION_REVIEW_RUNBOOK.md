---
title: "Agent Runtime & Mutation Review Runbook"
slug: runbooks/agent-runtime-mutation-review
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/agent/runtime_repository.py
  - Backend Architecture/aether-backend/services/agent/mutation_commit.py
canonical_owner: platform@aether
last_synced_commit: "ac900d5"
---

# Agent Runtime & Mutation Review Runbook

Covers the supervised agent runtime (run lifecycle, stale-run recovery) and the
staged graph-mutation review→commit seam. Agent-originated graph mutations are
never applied directly: they go through verify → stage → operator review →
approve → commit, with a durable audit trail and best-effort verified rollback.

## Rollout flags

`AETHER_STAGED_GRAPH_MUTATION_REVIEW_ENABLED` (review→commit),
`AETHER_AGENT_RUNTIME_DURABLE_ENABLED`, `AETHER_AGENT_WORKER_BRIDGE_ENABLED`,
`KYBER_AGENT_COMMAND_CENTER_ENABLED`, `KYBER_ONE_PERSON_OPS_ENABLED`. With
review disabled, `commit_approved_mutations`/`rollback_mutation` refuse
(`BadRequestError`) — batches stage and stay `approved`, uncommitted.

## Stuck / stale runs

1. A run whose heartbeat aged past the stale threshold is surfaced by
   `list_stuck_runs`. The sweep (`sweep_stale_runs`) marks it `stale` and emits
   a `run.stale` event so an operator (or recovery) can replay it.
2. `replay_run` produces a FRESH queued run with a new idempotency suffix — it
   never resurrects the dead run. Replaying an active run conflicts by design.
3. Worker callbacks are permission-boundaried: an operator token cannot spoof a
   worker status update, and a worker credential cannot read operator views.

## Mutation commit outcomes

1. **Committed**: the batch is `committed`; each mutation is `committed` with a
   rollback receipt and a `mutation.committed` audit event.
2. **Partial failure**: a bad mutation (e.g. unsupported target) fails while the
   good ones commit; the batch is `quarantined` — the failure is loud, per
   mutation, never silent.
3. **Graph write failure**: a graph error marks the mutation `failed_commit` and
   preserves the error string; nothing is half-applied.
4. **Validator/CIS block**: a `GraphWriteValidator` rejection or a CIS
   `quarantine` band skips the graph write and quarantines the mutation.
5. Commit is idempotent — a duplicate commit does not re-apply.

## Rollback

`rollback_mutation` attempts the inverse (vertex/edge drop), then READS THE
GRAPH BACK to verify absence. If the inverse errors or the artifact is still
present, the mutation is marked `rollback_repair_required` and a durable repair
task is opened — a rollback that could not fully restore state is never reported
as a clean undo. Successful rollbacks are idempotent.

## Never do

- Never apply an agent mutation directly to the graph, bypassing review.
- Never mark a rollback clean when the inverse failed — leave it
  `rollback_repair_required` and work the repair task.
- Never grant worker credentials operator permissions (or vice versa).

See also: `docs/source-of-truth/KYBER_ONE_PERSON_OPERATIONS.md`,
`docs/source-of-truth/EXTERNAL_AGENT_TELEMETRY_PLANE.md`,
`Agent Layer/README.md`.
