# Runbook: Campaign Source Sync Failure

**Alert:** `CampaignSourceSyncFailed`  
**Severity:** Warning

## Symptoms

- `campaign_source_sync_total{status="error"}` rate > 0 for 15+ minutes
- Spend data freshness SLO violation (`CampaignSourceStale`)
- Tenant reports missing spend data in Campaign 360

## Triage

1. Check Kyber → Measurement → Campaign Registry Health for the affected tenant.
2. Identify which platform is failing (`campaign_source_sync_total{platform=<X>}`).
3. Check connector logs: `grep "sync_error" | grep "platform=<X>"`.

## Common causes and fixes

**Expired OAuth token**  
Tenant must re-authorize the connector in Campaign Intelligence → Campaign Sources → Reconnect.

**Platform API rate limit**  
Connector automatically retries with exponential backoff. Monitor for self-resolution within 2 hours. If persistent, reduce sync frequency.

**Platform API outage**  
Check the platform's status page. No action required until outage resolves.

**Connector credential scope reduced**  
Tenant must revoke and re-grant the connector with full campaign read scope.

## Recovery verification

After fix, confirm:
```
campaign_source_sync_total{status="success"} rate > 0
campaign_source_freshness_seconds < 93600
```
