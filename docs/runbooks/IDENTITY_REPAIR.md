---
title: Runbook — Identity Repair
slug: runbooks/identity-repair
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/identity/resolver.py
  - Backend Architecture/aether-backend/services/identity/redirects.py
  - Backend Architecture/aether-backend/services/identity/graph_reconciliation.py
  - Backend Architecture/aether-backend/services/identity/reconciliation_routes.py
last_synced_commit: "41c79d4"
---

# Runbook — Identity Repair

Repair identity when entities were merged that should not have been, a survivor
redirect is wrong, or the identity repository and graph backend have drifted.
Merge/split/recompute are **tenant-scoped operator actions** (`write`
permission); the cross-tenant reconciliation trigger is **Kyber-operator-gated**
(`require_kyber_operator`). Nothing here crosses a tenant boundary except the
operator reconciliation surface, which is fail-closed.

## Model recap

Identity links entities with non-revoked `SAME_AS` edges. A merge records a
survivor canonical entity and tombstones the merged subject
(`merged_into_entity_id`); reads redirect through the survivor chain via
`resolve_entity_redirect` (bounded by `max_hops=10`, with a visited-set cycle
guard). A split unwinds an incorrect merge, revoking the specific `SAME_AS`
edges rather than deleting vertices (a vertex may be shared).

## Symptoms → actions

### Two people were merged into one entity
Use the **fragment-aware split**. Always preview first — it is non-mutating:

1. **Preview.** `POST /v1/identity/split/preview` with the `fragments`
   (`alias_ids`, `observation_ids`, `signal_groups`) and a `mode`. The preview
   returns the impact (aliases/observations/edges to move or revoke, journeys
   and dimensions affected, risk notes) and, if the split is not allowed, a
   `rejection_reason` — it never mutates.
2. **Execute.** `POST /v1/identity/split/execute` with the same fragments +
   `mode`:
   - `create_new_entity` — mint a fresh canonical entity for the fragments.
   - `restore_pre_merge_entity` — restore the entity from a prior merge; requires
     `source_merge_event_id`.
   - `move_to_existing_entity` — attach fragments to another active same-tenant
     entity; requires `target_entity_id`.
   The execute path writes a split event with the fragment payload and
   selectively revokes/rewrites edges; it is audited.

**Blocked with `campaign_only_sameness_blocked`.** The sameness rested only on
campaign-class signals, which the merge policy excludes from identity. This is a
guard, not a bug — the split is refused because the merge should not have been
identity-linked on that basis; fix the upstream signal, don't force the split.

### A merged entity's profile/reads resolve to the wrong survivor
Check the redirect chain. `resolve_entity_redirect(repo, tenant_id, entity_id)`
follows `merged_into_entity_id` to the surviving canonical id; reads return the
additive `resolved_entity_id` + `redirected` fields (`redirect_fields`). A wrong
survivor means the merge itself was wrong — split it (above); do not hand-edit
`merged_into_entity_id`. A redirect that stops early (hit `max_hops`) or a cycle
indicates a corrupted chain — escalate with the entity id.

### Repository and graph disagree (edges present in one, missing/revoked in the other)
Run reconciliation. It diffs the repo's non-revoked `SAME_AS` edges against the
graph backend and classifies drift as `missing_in_graph` (repo has it, graph does
not) or `missing_in_repo` (graph has it, repo revoked/lacks it).

- **Tenant view:** `GET /v1/identity/reconciliation` (`read` permission) returns
  the latest persisted run, or `?refresh=true` runs a fresh, tenant-scoped check.
  The summary is `{tenant_id, checked, in_sync, drift, drift_count, computed_at}`.
- **Operator trigger:** `POST /v1/admin/kyber/identity/reconciliation`
  (`require_kyber_operator`) reconciles an arbitrary tenant, optionally bounded to
  `entity_ids`. A non-zero `drift_count` emits a drift event and persists the run.

Reconciliation reports drift; it does not silently rewrite the graph. Investigate
each drift entry — `missing_in_graph` after a merge usually means a best-effort
graph mirror failed and a recompute will re-assert it; `missing_in_repo` means the
graph carries an edge the repo revoked (re-run after confirming the revoke was
intended).

After review, a Kyber operator may call
`POST /v1/admin/kyber/identity/reconciliation/repair`. The operation is
fail-closed and defaults to `dry_run: true`; provide a stable `request_id` for
idempotent retries plus an operator reason. The identity repository is the
authoritative source: an apply run mirrors active repository edges that are
missing from the graph and soft-revokes graph-only edges. The durable repair
record captures actor, intent, and per-edge outcomes. Tenant sessions cannot
invoke this cross-tenant repair surface.

### After a merge/split, downstream (journeys, attribution, profile) looks stale
Recompute. `POST /v1/identity/recompute` (`write`) re-runs resolution for the
entity; merge/split/suppression also enqueue recompute/invalidate/reattribute work
with the triggering event id as the correlation id. Confirm via the entity's
`GET /v1/identity/entities/{id}/audit` history.

## Health check

`GET /v1/identity/health` returns tenant-scoped safe counts (subjects by status,
open conflicts, recent merges/splits, tombstone integrity, last drift). Use it as
the first read when triaging — a spike in conflicts or a stale last-drift stamp
points at where to look.

## Escalation

If reconciliation reports drift that a recompute does not clear, or a split
preview and execute disagree, capture the reconciliation run, the relevant
merge/split events, and the entity ids, and escalate to `platform@aether`. Never
hand-edit `SAME_AS` edges, `merged_into_entity_id`, or graph vertices directly.
