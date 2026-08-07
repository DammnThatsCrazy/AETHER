---
title: Runbook — Missing Conversions (Campaign 360)
slug: runbooks/campaign-360-missing-conversions
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/campaign/exploration.py
  - Backend Architecture/aether-backend/services/measurement/repositories/conversion_repo.py
last_synced_commit: "10052e6"
---

# Runbook — Missing Conversions (Campaign 360)

## Alert condition

The Campaign 360 Overview shows `converted_count: 0` or a value lower than
expected, despite the tenant reporting that purchases occurred. The Conversions
tab returns no rows.

## What it means

Conversions exist in the system but are not being linked to this campaign.
The most common cause is a missing or misconfigured campaign attribution
join — the `canonical_conversions` table records are not associated with the
campaign's active attribution run.

## Diagnosis steps

1. **Verify conversions exist at all** (unfiltered):
   ```bash
   curl "$API_BASE/v1/conversions?limit=10" | jq ".items | length"
   ```
   If 0, the conversion pipeline itself has a problem (not Campaign 360).

2. **Check with `include_unattributed=true`**:
   ```bash
   curl "$API_BASE/v1/campaigns/$CAMPAIGN_ID/conversions?include_unattributed=true&limit=50" \
     | jq ".items | length"
   ```
   If this returns rows but the default does not, the conversions exist but
   have no active attribution credits linking them to the campaign.

3. **Check the active attribution run**:
   ```bash
   curl "$API_BASE/v1/campaigns/$CAMPAIGN_ID/overview" \
     | jq '{run_id: .attribution_run_id, run_freshness: .data_quality.attribution_run_freshness}'
   ```
   If `attribution_run_id` is `null`, no attribution run has completed for this
   campaign. Conversions will not be attributed.

4. **Check attribution run status**:
   ```bash
   curl "$API_BASE/v1/attribution/runs?campaign_id=$CAMPAIGN_ID&limit=5" \
     | jq "[.items[] | {id: .attribution_run_id, status: .status, is_active: .is_active}]"
   ```
   Look for a run in `failed` status.

## Remediation

| Root cause | Fix |
|------------|-----|
| No attribution run completed | Trigger a run: `POST /v1/attribution/runs` with the campaign's conversion IDs |
| Run failed | Check run logs; fix the failure; re-trigger |
| Conversions use wrong tenant/campaign ID | Verify the SDK `campaign_id` field in the conversion events |
| Attribution run completed but `is_active=false` | Re-activate: `PATCH /v1/attribution/runs/{id}` with `{"is_active": true}` |
| Time window mismatch | Check that conversion `occurred_at` timestamps fall within the campaign's active period |

## Escalation

If conversions are confirmed in the system and an attribution run is `complete`
and `is_active=true`, but `converted_count` is still 0, escalate to the
measurement engineering team with:
- Campaign ID
- Attribution run ID
- A sample conversion ID
- The output of `GET /v1/campaigns/{id}/overview`
