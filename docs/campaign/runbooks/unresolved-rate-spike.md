# Runbook: Campaign Resolution Unresolved Rate Spike

**Alert:** `CampaignResolutionUnresolvedRateHigh`  
**Severity:** Critical (>25%) / Warning (>10%)

## Symptoms

- `campaign_resolution_total{status="unresolved"}` rate spikes
- Mapping Review queue count rising (`campaign_mapping_review_open` gauge)
- Attribution credits missing campaign context

## Triage

1. Identify affected tenant(s) via `campaign_resolution_total{status="unresolved"}` broken down by `tenant_id`.
2. Check Kyber → Campaign Registry Health → Tenant drill-down for open review samples.
3. Examine evidence in the Mapping Review queue for patterns.

## Common causes and fixes

**New platform campaign ID format change**  
The platform changed their campaign ID format; existing aliases don't match. Create new aliases for the new format and trigger reprocessing.

**UTM tracking templates removed**  
Tenant removed UTM params from their ad creative. Evidence arrives without UTM signals and cannot be resolved. Tenant must re-apply tracking templates.

**Connector credential expired (no new campaigns registering)**  
Fix source sync first (see `source-sync-failure.md`), then reprocess unresolved spend.

**Bulk resolve via operator**  
For batch resolution of similar open reviews:
```bash
# Review open items for tenant
curl /v1/kyber/measurement/campaign/tenant/{tenant_id} | jq '.data.open_reviews_sample'

# Trigger bounded reprocess after fixing aliases
curl -X POST /v1/kyber/measurement/campaign/tenant/{tenant_id}/reprocess \
  -d '{"limit": 500, "dry_run": false}'
```

## Recovery verification

```
campaign_resolution_total{status="resolved"} rate recovering
campaign_mapping_review_open count decreasing
campaign_spend_mapping_rate > 0.9
```
