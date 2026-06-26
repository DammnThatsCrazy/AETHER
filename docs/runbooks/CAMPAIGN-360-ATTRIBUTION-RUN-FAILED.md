---
title: Runbook — Attribution Run Failed (Campaign 360)
slug: runbooks/campaign-360-attribution-run-failed
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/campaign/exploration.py
  - Backend Architecture/aether-backend/services/measurement/repositories/attribution_run_repo.py
last_synced_commit: 998b345
---

# Runbook — Attribution Run Failed (Campaign 360)

## Alert condition

The Campaign 360 overview shows `data_quality.attribution_run_freshness: "stale"`
or `"error"`. The Attribution tab in Campaign 360 shows no credit breakdown.
The Attribution Studio page shows a run in `failed` status for this campaign.

## What it means

The last attribution run for this campaign did not complete successfully. Revenue
and ROAS figures in Campaign 360 will be based on the last successful run
(possibly days old) or will be zero if no run has ever succeeded.

## Diagnosis steps

1. **Find the failed run**:
   ```bash
   curl "$API_BASE/v1/attribution/runs?campaign_id=$CAMPAIGN_ID&status=failed&limit=5" \
     | jq "[.items[] | {id: .attribution_run_id, model: .model_type, created_at: .created_at}]"
   ```

2. **Get the run error detail**:
   ```bash
   curl "$API_BASE/v1/attribution/runs/$RUN_ID" | jq .error_detail
   ```

3. **Identify the failure mode**:

   | Error message | Root cause |
   |--------------|------------|
   | `credit_sum_tolerance_exceeded` | Total credit weights deviate > 0.1% from 1.0 per conversion. Data integrity issue. |
   | `no_eligible_conversions` | No conversions in the attribution window for this campaign. |
   | `touchpoint_join_failed` | Touchpoints for the campaign are missing or have null `occurred_at`. |
   | `model_config_not_found` | The attribution model config referenced by the run no longer exists. |
   | `timeout` | The attribution engine exceeded its processing budget (> 300s for the campaign's conversion set). |
   | `database_error` | Transient PostgreSQL error. |

4. **Check conversion and touchpoint counts**:
   ```bash
   curl "$API_BASE/v1/campaigns/$CAMPAIGN_ID/overview" \
     | jq '{touchpoints: .touchpoint_count, conversions: .converted_count}'
   ```
   A campaign with 0 touchpoints or 0 conversions will always fail attribution.

## Remediation

| Root cause | Fix |
|------------|-----|
| Transient database error | Re-trigger: `POST /v1/attribution/runs` |
| `no_eligible_conversions` | Verify conversions are being ingested; if intentional, no action needed |
| `credit_sum_tolerance_exceeded` | Inspect model config; report to measurement engineering |
| `timeout` | Reduce the date range and run a targeted backfill in smaller windows |
| Model config deleted | Restore the config or use a different model |
| `touchpoint_join_failed` | Fix the touchpoint records (null `occurred_at`); re-ingest; re-trigger |

## Triggering a manual re-run

```bash
curl -X POST "$API_BASE/v1/attribution/runs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversion_id": "$CONVERSION_ID"}'
```

For bulk re-runs across a date window:
```bash
curl -X POST "$API_BASE/v1/attribution/backfills" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}'
```

## Reconciliation check after re-run

After a successful re-run, verify reconciliation via the overview endpoint:

```bash
curl "$API_BASE/v1/campaigns/$CAMPAIGN_ID/overview" \
  | jq '.data_quality.reconciliation_status'
```

Expected: `"ok"`. If `"warn"` or `"error"`, check the reconciliation invariants
in the `CampaignPopulationExplorer` service log.

## Escalation

If three consecutive re-runs fail with `credit_sum_tolerance_exceeded`, escalate
to the measurement engineering team — this indicates a data integrity issue in
the `attribution_credits` table that requires manual inspection.
