---
title: "Runbook: Spend Records Missing Campaign Attribution"
slug: campaign/runbooks/missing-spend-attribution
section: operations
visibility: I
audience: [ops]
---

# Runbook: Spend Records Missing Campaign Attribution

**Trigger:** `CampaignSpendMappingRateLow` fires (spend mapping rate below 70%), or tenant reports missing spend in Campaign 360.

## Symptoms

- `campaign_spend_mapping_rate` gauge below 0.7 for a tenant.
- `spend_records` rows with `campaign_resolution_status IN ('unresolved', 'not_applicable')`.
- Campaign 360 spend total is lower than the ad platform dashboard.

## Diagnosis

1. **Quantify the gap**

   ```sql
   SELECT campaign_resolution_status, COUNT(*), SUM(spend)
   FROM spend_records
   WHERE tenant_id = '<tenant_id>'
     AND period_start >= NOW() - INTERVAL '7 days'
   GROUP BY campaign_resolution_status;
   ```

2. **Check for missing external refs**

   ```sql
   SELECT DISTINCT platform, external_account_id, external_campaign_id
   FROM spend_records
   WHERE tenant_id = '<tenant_id>'
     AND campaign_resolution_status = 'unresolved'
     AND external_campaign_id IS NOT NULL
   LIMIT 20;
   ```

   If these external IDs are not in `campaign_external_refs`, the connector sync may not have run or the campaign was created after the spend was imported.

3. **Check connector sync health**

   ```
   GET /v1/campaign-sources/<source_id>/health
   ```

   Look for `last_sync_at` — if stale by more than 24 hours, the source is not syncing.

4. **Check for open Mapping Reviews**

   ```
   GET /v1/mapping-review?status=open&limit=50
   ```

## Resolution

**If external refs are missing (connector hasn't synced):**

1. Trigger a manual sync:
   ```
   POST /v1/campaign-sources/<source_id>/sync
   ```
2. Monitor `campaign_source_sync_total{status="success"}` for the platform.
3. After sync, re-run backfill for the affected date range.

**If Mapping Reviews exist:**

Resolve them via the Mapping Review UI or API. After resolution, reprocessing is triggered automatically.

**If `external_campaign_id IS NULL` on spend rows (pre-migration data):**

Run the backfill script:
```bash
python scripts/campaign/backfill_campaign_ids.py \
  --tenant-id <tenant_id> \
  --dry-run
python scripts/campaign/backfill_campaign_ids.py \
  --tenant-id <tenant_id>
```

## Verification

- `campaign_spend_mapping_rate` rises above 0.7 within 30 minutes of resolution.
- `CampaignSpendMappingRateLow` alert auto-resolves.
- Campaign 360 spend totals match the ad platform within the expected variance (currency conversion, attribution window).
