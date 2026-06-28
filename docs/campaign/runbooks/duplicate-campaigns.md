---
title: "Runbook: Duplicate Campaign Records"
slug: campaign/runbooks/duplicate-campaigns
section: operations
visibility: I
audience: [ops]
---

# Runbook: Duplicate Campaign Records

**Trigger:** Tenant reports duplicate entries in Campaign Registry, or Campaign 360 shows split spend for what should be one campaign.

## Symptoms

- Two or more rows in `campaigns` with the same `name` and overlapping date ranges for the same tenant.
- `campaign_external_refs` with the same `(platform, external_account_id, external_campaign_id)` tuple pointing to different `campaign_id` values.
- Spend or touchpoint totals appear split across two campaign UUIDs.

## Root Cause

Duplicates can arise from:
1. A connector sync race during the initial import (two worker threads created the campaign before the `ON CONFLICT` index was in place on an older schema version).
2. Manual data entry creating a custom campaign that duplicates an externally-imported one.
3. A backfill run that created a new canonical record before the existing one was detected.

## Verification

```sql
-- Find external refs pointing to more than one campaign for the same provider key
SELECT platform, external_account_id, external_campaign_id, COUNT(DISTINCT campaign_id) AS n
FROM campaign_external_refs
WHERE tenant_id = '<tenant_id>'
GROUP BY platform, external_account_id, external_campaign_id
HAVING COUNT(DISTINCT campaign_id) > 1;
```

## Resolution Steps

**Do NOT auto-merge campaigns based on display name similarity.** Follow these steps manually.

1. **Identify the canonical UUID to keep**

   Prefer the UUID that:
   - Was created first (`campaigns.created_at` ASC).
   - Has the most `spend_records` and `silver_campaign_touchpoint_facts` rows referencing it.

2. **Re-point external refs**

   ```sql
   UPDATE campaign_external_refs
   SET campaign_id = '<keeper_uuid>', updated_at = NOW()
   WHERE tenant_id = '<tenant_id>'
     AND campaign_id = '<duplicate_uuid>';
   ```

3. **Re-point aliases**

   ```sql
   UPDATE campaign_aliases
   SET campaign_id = '<keeper_uuid>', updated_at = NOW()
   WHERE tenant_id = '<tenant_id>'
     AND campaign_id = '<duplicate_uuid>'
     AND valid_until IS NULL;
   ```

4. **Re-point fact table rows** (spend, touchpoints, attribution)

   ```sql
   UPDATE spend_records
   SET campaign_id = '<keeper_uuid>'::text
   WHERE tenant_id = '<tenant_id>' AND campaign_id = '<duplicate_uuid>';

   UPDATE silver_campaign_touchpoint_facts
   SET campaign_id = '<keeper_uuid>'::text
   WHERE tenant_id = '<tenant_id>' AND campaign_id = '<duplicate_uuid>';

   UPDATE attribution_credits
   SET campaign_id = '<keeper_uuid>'::text
   WHERE tenant_id = '<tenant_id>' AND campaign_id = '<duplicate_uuid>';
   ```

5. **Archive the duplicate campaign**

   ```sql
   UPDATE campaigns
   SET archived_at = NOW(), status = 'archived', updated_at = NOW()
   WHERE campaign_id = '<duplicate_uuid>' AND tenant_id = '<tenant_id>';
   ```

6. **Verify**

   - `campaign_external_refs` for the provider key now has exactly one `campaign_id`.
   - Campaign 360 totals are consolidated under the keeper UUID.
   - No open Mapping Reviews reference the archived UUID.

## Prevention

- The `ON CONFLICT (tenant_id, platform, external_account_id, external_campaign_id)` constraint in `campaign_external_refs` prevents duplicates from connector syncs under normal operation.
- If the constraint is triggered (error in sync logs), investigate the connector for concurrent writes.
