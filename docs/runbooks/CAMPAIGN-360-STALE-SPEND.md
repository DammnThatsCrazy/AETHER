---
title: Runbook — Stale Spend Warning (Campaign 360)
slug: runbooks/campaign-360-stale-spend
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/campaign/exploration.py
  - Backend Architecture/aether-backend/services/campaign/routes.py
last_synced_commit: "99da74c0"
---

# Runbook — Stale Spend Warning (Campaign 360)

## Alert condition

The Campaign 360 overview shows `data_quality.connector_freshness: "warn"` or
`"error"`. The frontend displays a yellow or red badge on the Overview tab.

## What it means

The spend connector for this campaign has not produced a new record within the
expected freshness window. This means the spend, impressions, and clicks
displayed in Campaign 360 may be stale by hours or days.

## Diagnosis steps

1. **Check the connector log** for the affected tenant:
   ```bash
   # In the Kyber operator Quality tab, check "Connector freshness" row.
   # Or via API:
   curl -H "Authorization: Bearer $TOKEN" \
     "$API_BASE/v1/campaigns/$CAMPAIGN_ID/overview" | jq .data_quality
   ```

2. **Identify the connector source**:
   ```bash
   curl "$API_BASE/v1/spend?campaign_id=$CAMPAIGN_ID&limit=1" | jq .items[0].imported_at
   ```
   Note the `imported_at` timestamp of the most recent spend record.

3. **Check the spend import job**:
   Look for failed jobs in the background task queue:
   ```bash
   # In the Aether ops dashboard → Background jobs → Filter: spend_import
   # Or query the job store directly:
   curl "$API_BASE/v1/ops/jobs?type=spend_import&status=failed" | jq .
   ```

4. **Check connector credentials**:
   If the import job shows `auth_error`, the platform API credentials for the
   ad platform (Google Ads, Meta, etc.) have expired or been revoked.

## Remediation

| Root cause | Fix |
|------------|-----|
| Connector credential expired | Re-authorize in tenant settings → Integrations |
| Import job crashed | Trigger a manual backfill via `POST /v1/spend/imports` |
| No spend in window (campaign paused) | Expected behavior — verify with tenant |
| Platform API rate-limited | Wait for rate limit reset; job will auto-retry |

## Escalation

If freshness does not recover within 2 hours of connector reauthorization,
escalate to the data infrastructure team with the connector type, tenant ID,
and the most recent import job ID.
