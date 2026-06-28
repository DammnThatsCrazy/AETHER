---
title: Campaign Registry Migration Guide
slug: campaign/campaign-migration
section: operations
visibility: I
audience: [dev-senior, ops]
source_files:
  - Backend Architecture/aether-backend/alembic/versions/20260627_campaign_registry.py
  - scripts/campaign/backfill_campaign_ids.py
last_synced_commit: 7c85af5
---

# Campaign Registry Migration Guide

## Migration revision

`20260627_campaign_registry` — down_revision: `ca001b2c3d4e`

## What the migration creates

- `campaigns` — canonical campaign registry
- `campaign_external_refs` — provider ID → canonical UUID mapping
- `campaign_aliases` — UTM/tracking lookup aliases
- `campaign_resolution_reviews` — operator mapping review queue

## Fact table alterations

`spend_records`, `silver_campaign_touchpoint_facts`, and `attribution_credits` receive new nullable columns for external IDs and resolution metadata. All new columns have safe defaults (`NULL` or `'not_applicable'`) — existing rows remain valid.

## Running the migration

```bash
cd "Backend Architecture/aether-backend"
alembic upgrade head
```

## Rollback

```bash
alembic downgrade -1
```

Downgrade drops the four new tables (CASCADE) and reverses the ALTER TABLE additions. All historical measurement data in existing tables is preserved.

## Historical backfill

Pre-migration spend records have `external_campaign_id IS NULL`. Run the backfill script to map them:

```bash
# Dry run first:
python scripts/campaign/backfill_campaign_ids.py --dry-run --tenant-id <ID>

# Live run:
python scripts/campaign/backfill_campaign_ids.py --tenant-id <ID> --batch-size 500

# All tenants:
python scripts/campaign/backfill_campaign_ids.py --batch-size 1000
```

The script is idempotent. Already-canonical rows are skipped. A JSON audit log is written per run.

### Backfill report fields

| Field | Meaning |
|---|---|
| `scanned` | Total spend records processed |
| `already_canonical` | Rows already resolved (skipped) |
| `mapped` | Rows successfully resolved |
| `newly_registered` | New campaign registry entries created |
| `ambiguous` | Multiple candidates — Mapping Review created |
| `unresolved` | No candidates — Mapping Review created |
| `errors` | Unexpected errors (logged, not fatal) |

## Post-migration checks

```bash
# Verify migration is current:
alembic current

# Verify new tables exist:
psql $DATABASE_URL -c "SELECT COUNT(*) FROM campaigns;"

# Check backfill progress:
psql $DATABASE_URL -c "
  SELECT campaign_resolution_status, COUNT(*)
  FROM spend_records
  GROUP BY campaign_resolution_status;
"
```
