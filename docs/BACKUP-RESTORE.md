---
title: Backup & Restore
slug: operations/backup-restore
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Backup & Restore

Provider-agnostic backup/restore guidance for the durable stores. Local dev is
in-memory (no backup needed); staging/production back the managed services.

## What to back up

- **PostgreSQL** (primary durable store: billing, usage, contracts, configs,
  audit, retention) — automated daily snapshots + PITR where available.
- **Graph endpoint** (Neptune) — provider snapshots.
- **Object storage** (audit exports, artifacts) — versioned bucket.
- **Secret manager** — backed up by the provider; rotate, don't export.

## Restore drill

1. Restore PostgreSQL to a point in time; run `alembic upgrade head` if needed.
2. Validate tenant isolation + audit-ledger integrity post-restore.
3. Reconcile billing/usage windows; re-run data-quality checks.
4. Confirm retention + legal-hold metadata survived the restore.

## Retention coupling

Backups inherit erasure/retention semantics — a GDPR erasure must propagate to
backups per your retention policy. See [Data Retention Review](DATA-RETENTION-REVIEW.md)
and [Data Durability](DATA-DURABILITY.md). Test restores on a cadence.
