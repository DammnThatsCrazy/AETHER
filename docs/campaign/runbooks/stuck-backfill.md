---
title: "Runbook: Stuck Campaign ID Backfill"
slug: campaign/runbooks/stuck-backfill
section: operations
visibility: I
audience: [ops]
---

# Runbook: Stuck Campaign ID Backfill

**Trigger:** `CampaignBackfillStuck` alert fires (reprocess requested but no completions for 20+ minutes), or `campaign_backfill_progress` gauge stops advancing.

## Symptoms

- `scripts/campaign/backfill_campaign_ids.py` appears to hang or exits early with a partial count.
- `campaign_backfill_progress` metric plateau below 100%.
- Spend records remain with `external_campaign_id IS NULL` after a backfill run.

## Diagnosis

1. **Check the audit log**

   ```bash
   ls -lth /var/log/aether/campaign/backfill_*.json | head -5
   cat /var/log/aether/campaign/backfill_<latest>.json | python -m json.tool
   ```

   Look for: `status`, `records_scanned`, `newly_registered`, `ambiguous`, `unresolved`, `failed`.

2. **Check for DB connection errors**

   In the audit log or stderr, look for `asyncpg.TooManyConnectionsError` or `ConnectionRefusedError`. This means the backfill worker is saturating the DB connection pool.

3. **Check for lock contention**

   ```sql
   SELECT pid, wait_event_type, wait_event, query
   FROM pg_stat_activity
   WHERE state = 'active' AND query ILIKE '%spend_records%';
   ```

4. **Check for ambiguous rows blocking progress**

   If `ambiguous` count is large, the backfill cannot auto-resolve those rows. They are left as `campaign_resolution_status = 'unresolved'` and the script moves on. This is expected behavior, not a bug.

## Resolution

**For DB connection saturation:**

Reduce batch size:
```bash
python scripts/campaign/backfill_campaign_ids.py \
  --tenant-id <tenant_id> \
  --batch-size 200 \
  --cursor <last_processed_id>
```

**For lock contention:**

Run during off-peak hours or with a lower batch size. Backfill is idempotent — safe to resume with `--cursor`.

**For ambiguous rows:**

These require manual Mapping Review resolution. After resolving open reviews:
```bash
python scripts/campaign/backfill_campaign_ids.py \
  --tenant-id <tenant_id> \
  --dry-run  # verify scope
python scripts/campaign/backfill_campaign_ids.py \
  --tenant-id <tenant_id>
```

**For persistent failures:**

Check the `failed` count in the audit log. Investigate the first failing row:
```sql
SELECT * FROM spend_records WHERE spend_id = '<failing_id>';
```

## Verification

After backfill completes:
```sql
SELECT COUNT(*) FROM spend_records
WHERE tenant_id = '<tenant_id>' AND external_campaign_id IS NULL;
-- Should be 0 for rows where platform is known
```

The `CampaignBackfillStuck` alert should auto-resolve once `campaign_reprocess_completed_total` starts incrementing again.
