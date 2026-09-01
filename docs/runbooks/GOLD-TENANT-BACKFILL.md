---
title: Runbook — Gold Tenant Backfill
slug: runbooks/gold-tenant-backfill
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/repositories/lake.py
  - scripts/gold_tenant_backfill.py
last_synced_commit: "a4276ce1"
---

# Runbook — Gold Tenant Backfill

## Purpose

`GoldRepository.materialize()` (`repositories/lake.py`) keys every Gold row by:

    record_id = sha256(f"{tenant_id}:{metric_name}:{entity_id}:{entity_type}")[:24]

Before this was fixed, `tenant_id` was not part of that hash. Two tenants
materializing the same `(metric_name, entity_id, entity_type)` collided on
one `record_id` and silently overwrote each other's Gold value — whichever
tenant wrote last "won" the row, and the earlier tenant's value is gone.
Existing Gold rows written under the old formula are still stored under a key
that does not match what `materialize()` computes for their own
`tenant_id` / `metric_name` / `entity_id` / `entity_type` today.

`scripts/gold_tenant_backfill.py` finds every such mismatch and moves the row
to its correct, tenant-scoped key. Run it once per environment after the
`materialize()` fix ships, and again any time you suspect stray tenant-less
keys remain — it is fully idempotent (a clean second run reports
`rekeyed: 0`).

## Preconditions

- The tenant-inclusive `materialize()` fix must already be deployed (check
  `repositories/lake.py` — `GoldRepository.materialize` should hash
  `tenant_id` first, and `GoldRepository.compute_record_id` should exist).
  Running the backfill before the fix ships just moves rows back onto
  colliding keys on the very next write.
- Read access to run a dry run; write access (`--apply`) should be limited to
  an operator who has completed the backup step below.
- `AETHER_ENV` and, in staging/production, `DATABASE_URL` set the same way
  the service itself is configured — the script reuses
  `repositories.repos.get_pool()`'s pool selection, so it talks to whatever
  the running service talks to. In local mode it operates on the shared
  in-memory Gold store instead.

## Backup

Before `--apply` against a real database, snapshot every `gold_*` table:

    pg_dump "$DATABASE_URL" \
      --table='gold_*' \
      --format=custom \
      --file="gold_backup_$(date -u +%Y%m%dT%H%M%SZ).dump"

Keep the dump until verification (below) is complete. Restoring a table from
it is the rollback path.

## Step 1 — Dry run (always first)

Dry run is the default — `--apply` is required to write anything:

    python scripts/gold_tenant_backfill.py

Or scoped to one domain while triaging:

    python scripts/gold_tenant_backfill.py --domain market

Read the report before doing anything else:

- `scanned` / `rekeyed` / `collisions` / `skipped`, per domain and totaled.
- Every `collision_detail` entry: which row would win (`winner`, by latest
  `updated_at`) and which would be left behind (`losers`) at their current,
  stale key. A collision never deletes anything — losers are logged in full
  (`id`, `tenant_id`, `metric_name`, `entity_id`, `entity_type`, `value`,
  `updated_at`) so you can inspect or manually recover them before or after
  `--apply`.
- `--json` for a machine-readable copy to attach to the change ticket.

If `collisions` is non-zero, read "Collision policy" below before applying.

## Step 2 — Apply

Local / in-memory (dev, CI):

    AETHER_ENV=local python scripts/gold_tenant_backfill.py --apply

Against a real database, `--apply` alone is refused — pass `--confirm-prod`
too, as an explicit second confirmation that you took the backup above:

    python scripts/gold_tenant_backfill.py --apply --confirm-prod

For a large table, use `--domain` to work through domains one at a time, and
`--batch-size` / `--limit` to bound how much a single run reads. Re-run the
same command until `rekeyed: 0` and `collisions` stops changing — pagination
ties can occasionally leave a row for the next pass, which is safe because
the script is idempotent (rows already at their canonical key are left
alone).

## Collision policy

A collision is two or more **current** rows resolving to the same
tenant-scoped `record_id` — typically a stale pre-fix row left over next to a
row that was already correctly re-materialized after the fix shipped, for
the same tenant/metric/entity/type. The policy is conservative and
deterministic:

1. The row with the latest `updated_at` wins and is written (or left, if
   already correct) at the canonical key.
2. Every other row in the group is left **untouched** at its current key —
   never deleted. It reappears in `collision_detail.losers` on every
   subsequent run until an operator resolves it by hand (merge, delete, or
   re-point downstream readers, per the specific incident) — the script does
   not pretend a logged collision is "resolved" just because it has been
   reported once.
3. Ties on `updated_at` break on `id`, purely for a stable, repeatable
   outcome — not a claim about which row is more correct.
4. The same policy applies if a row is written to the target key by live
   traffic *while the backfill is running* — the apply step re-checks the
   target immediately before writing and will not blind-overwrite a row that
   was not there when the table was scanned.

## Verification

- Re-run the dry run: `rekeyed: 0` and an unchanged `collisions` count from
  the last apply means the domain is settled.
- Spot-check a few moved rows through the normal Gold read path
  (`GoldRepository.get_metrics` / the Profile 360 and intelligence surfaces
  that consume it), scoped to the tenant the row now carries, and confirm
  the value matches what the report said would move.
- `AETHER_ENV=local python -m pytest tests/unit/test_gold_backfill.py -q -n0`
  (from `Backend Architecture/aether-backend`) and
  `python scripts/validate_temporal_integrity.py` (from repo root) should
  both still pass.

## Rollback

The script never deletes data it cannot still locate: a moved row's content
is fully preserved at its new key, and collision losers are left in place at
their old key. To roll back a specific domain:

1. Restore the domain's table from the backup dump:

       pg_restore --data-only --table=gold_<domain> -d "$DATABASE_URL" \
         "gold_backup_<timestamp>.dump"

2. Or, for a single row, use the `moved` entries in the run's `--json` report
   (each has `from`, `to`, and the row's identity fields) to hand-write it
   back to its pre-backfill key — this is a lookup of where the row used to
   live, not a data restore, since the content never left the table.

There is no in-place "undo" command; the backup dump is the source of truth
for a full rollback.

## Cross-tenant corruption caveat

**This script cannot recover data that was already overwritten before it
ever runs.** The tenant-less key collided on *write*, not on read: if tenant
A and tenant B both materialized the same `(metric_name, entity_id,
entity_type)` before the fix shipped, only the **last writer's** value
survived under the shared key — the earlier tenant's value was silently
discarded at write time, long before this script exists to look at it. The
backfill moves whatever row currently exists to the tenant-scoped key that
matches its own stored `tenant_id` field; it has no way to know, and does not
claim, that this was the *only* tenant that ever wrote there.

If you have reason to believe a specific tenant lost data this way (e.g. a
support report of a missing or wrong Gold value with no corresponding
write), that value is not recoverable from Gold. Check whether the
originating Bronze/Silver record still exists and, if so, re-run
materialization for that tenant explicitly; otherwise escalate per the
section below. A clean rekey (`collisions: 0`) is not proof that no
historical cross-tenant overwrite occurred — it only means the *currently
surviving* rows are each stored at the one key their own fields resolve to.

## Never do

- Never hand-edit a Gold row's `id` or `tenant_id` directly in the database
  to "fix" a collision — that bypasses the audit trail this script produces.
  Re-run with `--apply` (idempotent) or resolve losers explicitly per the
  collision policy.
- Never run `--apply --confirm-prod` without a fresh backup — `--confirm-prod`
  exists specifically to force a deliberate pause before mutating production.
- Never delete a collision's logged losers by hand while treating the
  collision as "resolved" — deleting them destroys the last remaining
  evidence of the pre-fix state (see the caveat above).

## Escalation

If `collisions` keeps growing across repeated runs (rather than settling to
a stable count), or a spot-check in Verification shows a wrong tenant's value
on a metric read, capture the run's `--json` report and the affected
`record_id`s and escalate to `platform@aether`. Do not delete collision
losers by hand while an investigation is open.
