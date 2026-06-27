---
title: "Runbook: UTM Ambiguity — Multiple Campaigns Match Same UTM Signal"
slug: campaign/runbooks/utm-ambiguity
section: operations
visibility: I
audience: [ops]
---

# Runbook: UTM Ambiguity — Multiple Campaigns Match Same UTM Signal

**Trigger:** `CampaignResolutionUnresolvedRateHigh` fires, or a tenant reports that UTM traffic is not attributed to any campaign in Campaign 360.

## Symptoms

- Open Mapping Reviews in the tenant's Mapping Review queue with evidence containing `utm_campaign` that matches more than one campaign alias.
- `campaign_resolution_total{status="ambiguous"}` counter rising.
- Campaign 360 shows touchpoints with `campaign_resolution_status = 'ambiguous'`.

## Root Cause

Two or more campaigns in the registry share a `utm_campaign_alias` with the same normalized value and the resolver cannot deterministically pick one (`composite_alias` or `utm_campaign_alias` step returns multiple candidates).

## Resolution Steps

1. **Identify the conflicting aliases**

   ```sql
   SELECT a.alias_id, a.campaign_id, c.name, a.alias_value_normalized, a.alias_type
   FROM campaign_aliases a
   JOIN campaigns c USING (campaign_id)
   WHERE a.tenant_id = '<tenant_id>'
     AND a.alias_type IN ('utm_campaign_alias', 'composite_alias')
     AND a.alias_value_normalized = '<normalized_utm_campaign>'
     AND a.valid_until IS NULL
   ORDER BY a.created_at;
   ```

2. **Determine the correct owner**

   Check date ranges (`c.start_at`, `c.end_at`) and external refs (`campaign_external_refs`) to identify which campaign the traffic belongs to.

3. **Expire the stale alias**

   ```sql
   UPDATE campaign_aliases
   SET valid_until = NOW()
   WHERE alias_id = '<stale_alias_id>' AND tenant_id = '<tenant_id>';
   ```

4. **Resolve open Mapping Reviews**

   Via the Mapping Review UI or API:
   ```
   POST /v1/mapping-review/<review_id>/resolve
   { "campaign_id": "<canonical_uuid>", "note": "Expired duplicate alias, resolved to correct campaign" }
   ```

5. **Trigger reprocessing** (optional, for affected touchpoints)

   Via Kyber operator UI or:
   ```
   POST /v1/kyber/measurement/campaign/tenant/<tenant_id>/reprocess
   { "limit": 5000, "dry_run": false }
   ```

6. **Verify**

   - Mapping Review queue clears for the affected evidence hash.
   - `campaign_resolution_total{status="ambiguous"}` stops climbing.
   - Campaign 360 shows the reprocessed touchpoints attributed correctly.

## Prevention

- Add `platform + external_account_id` to alias scoping so the same `utm_campaign` value used by different platform accounts doesn't collide.
- Configure tracking templates to include `utm_id` for deterministic priority-3 resolution.
