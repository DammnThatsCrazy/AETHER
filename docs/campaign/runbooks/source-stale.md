---
title: "Runbook: Campaign Source Staleness SLO Violation"
slug: campaign/runbooks/source-stale
section: operations
visibility: I
audience: [ops]
---

# Runbook: Campaign Source Staleness SLO Violation

**Trigger:** `CampaignSourceStale` alert fires (source freshness gauge crosses SLO threshold, typically 25 hours without a successful sync).

## Symptoms

- `campaign_source_freshness{platform="<platform>"}` gauge has not updated in 25+ hours.
- `campaign_source_sync_total{status="success"}` has not incremented since the last successful sync.
- Tenant reports spend data is out of date in Campaign 360.

## SLO Definition

| Platform | Expected sync frequency | Stale threshold |
|---|---|---|
| Google Ads | Every 6 hours | 25 hours |
| Meta Ads | Every 6 hours | 25 hours |
| TikTok Ads | Every 6 hours | 25 hours |
| LinkedIn Ads | Every 12 hours | 36 hours |
| X Ads | Every 12 hours | 36 hours |
| Reddit Ads | Every 12 hours | 36 hours |
| Microsoft Ads | Every 12 hours | 36 hours |

## Diagnosis

1. **Check source health**

   ```
   GET /v1/campaign-sources/<source_id>/health
   ```

   Inspect `"last_sync_at"`, `"last_error"`, `"status"`.

2. **Check connector error logs**

   Search for `connector_id = <source_id>` in the connector service logs. Common errors:
   - `RateLimitError` — platform API rate limit hit; will auto-retry with backoff.
   - `AuthError` — credential expired; follow the credential rotation runbook.
   - `PlatformMaintenanceError` — ad platform is in scheduled maintenance; no action needed.
   - `TimeoutError` — network issue; the connector will retry on the next schedule tick.

3. **Check scheduler health**

   If multiple sources are stale simultaneously, the scheduler itself may be down:
   ```bash
   systemctl status aether-connector-scheduler
   # or in k8s:
   kubectl get pods -l app=connector-scheduler -n aether
   ```

## Resolution

**For transient errors (rate limit, timeout, platform maintenance):**

The connector will auto-retry. Monitor `campaign_source_sync_total{status="success"}` for the next hour. If no recovery, trigger a manual sync:
```
POST /v1/campaign-sources/<source_id>/sync
```

**For auth errors:**

Follow the [Connector Credential Rotation runbook](connector-credential-rotation.md).

**For scheduler down:**

```bash
systemctl restart aether-connector-scheduler
# or:
kubectl rollout restart deployment/connector-scheduler -n aether
```

**For persistent platform API errors:**

Check the ad platform's status page. If the platform API is down, document the outage in the incident log and set a reminder to re-sync once the platform recovers.

## Verification

- `campaign_source_freshness` gauge advances past the stale threshold.
- `CampaignSourceStale` alert auto-resolves.
- `campaign_source_sync_total{status="success"}` increments for the affected platform.
- `GET /v1/campaign-sources/<source_id>/health` returns `"status": "healthy"`.
