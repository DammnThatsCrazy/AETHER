---
title: Runbook — Attribution Run Failed (Campaign 360)
slug: runbooks/campaign-360-attribution-run-failed
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_files: [services/api/journeys/campaign/exploration.py, services/api/journeys/measurement/repositories/attribution_run_repo.py, services/api/journeys/measurement/engine/attribution_engine.py, services/api/journeys/traffic/repair.py]
source_hashes:
  "services/api/journeys/campaign/exploration.py": "sha256:e13313cc1041aa66ea25ded2d3fac22af21bb6ab7c5ce61641184ed3ac364f13"
  "services/api/journeys/measurement/engine/attribution_engine.py": "sha256:f933e4895eeb931f50757a1789081f6a4bc92461bd1de3ece2424b1d918cc0d9"
  "services/api/journeys/measurement/repositories/attribution_run_repo.py": "sha256:5c5a1edbacb8ebe97e641b0a577eab924a1a0ca5b76e75967711bd88e8ae46dd"
  "services/api/journeys/traffic/repair.py": "sha256:309a31315d07945083aa693341cff37b4fe5cefbc71592925c38ad818acfab68"
---

# Runbook — Attribution Run Failed (Campaign 360)

## Alert condition

The Campaign 360 overview shows
`data_quality.attribution_run_freshness: "missing"`, the Attribution tab has no
credit breakdown, and Attribution Studio shows a run in `failed` status for
this campaign. The current explorer reports this field as `fresh` when its
credit summary contains credits and `missing` otherwise; it does not emit
`stale` or `error` for this field.

## What it means

The last attribution run for this campaign did not complete successfully. Revenue
and ROAS figures in Campaign 360 will be based on the last successful run
(possibly days old) or will be zero if no run has ever succeeded.

A run is **not** failed when its `eligible_revenue` is null: run and credit
revenue are in the conversion's normalized currency (USD, `native ×
exchange_rate`), and a foreign-currency conversion with no known FX rate is
attributed with null revenue (credits still carry weights and conversion
counts). Those credits are excluded from revenue totals and reported as
`unconverted_credit_count`; fix the missing rate source, not the run.

## Diagnosis steps

1. **Find the failed run**:
   ```bash
   curl "$API_BASE/v1/attribution/runs?campaign_id=$CAMPAIGN_ID&status=failed&limit=5" \
     | jq "[.items[] | {id: .attribution_run_id, model: .model_type, trigger: .trigger_reason, classifier: .source_classifier_version, prior_run: .prior_attribution_run_id, created_at: .created_at}]"
   ```

2. **Get the run error detail**:
   ```bash
   curl "$API_BASE/v1/attribution/runs/$RUN_ID" \
     | jq '{failure_reason, model_config_snapshot, input_touchpoint_ids, excluded_touchpoint_ids, exclusion_reasons, source_classifier_version, prior_attribution_run_id}'
   ```

3. **Identify the failure mode**:

   | Error message | Root cause |
   |--------------|------------|
   | `invalid_conversion_timestamp` | The conversion's `occurred_at` is missing or cannot be parsed, so the engine cannot anchor the lookback window. |
   | `touchpoint_missing` in `exclusion_reasons` | A journey referenced a touchpoint row that could not be loaded. The touchpoint is excluded; this is not by itself a failed-run reason. |
   | `Attribution run <id> disappeared before completion` | The repository could not complete the run row created by the engine. Inspect repository and database logs for the same run ID. |
   | Any other `failure_reason` | The engine stores the caught exception text, truncated to 500 characters; it does not normalize these into a fixed error-code set. Correlate the text with backend logs. |

   Some request errors happen before a run row is created: a conversion that is
   missing for the tenant, not attribution-eligible, or an explicitly requested
   model configuration that cannot be found. A missing requested model config
   fails before a first run; a recompute without an override reuses the prior
   run's model snapshot.

4. **Check conversion and touchpoint counts**:
   ```bash
   curl "$API_BASE/v1/campaigns/$CAMPAIGN_ID/overview" \
     | jq '{touchpoints: .touchpoint_count, conversions: .converted_count}'
   ```
   The engine runs attribution for one existing, eligible conversion at a time.
   Zero conversions means there is no conversion run to trigger. Zero usable
   touchpoints alone is not a defined failure: the engine passes the available
   (possibly empty) candidate list to the resolver and records exclusions when
   rows are missing or ineligible.

   The engine does not raise the documented `credit_sum_tolerance_exceeded`
   error. If credit weight plus unattributed weight exceeds the internal
   tolerance, it logs a reconciliation error and continues to persist the run.

## Remediation

| Root cause | Fix |
|------------|-----|
| Conversion missing or not eligible | Confirm the conversion ID, tenant, and `attribution_eligible` state before retrying. These errors occur before a run row is created. |
| `invalid_conversion_timestamp` | Correct the conversion's `occurred_at` through the supported ingestion/correction path, then re-trigger. |
| Missing touchpoint rows | Inspect `excluded_touchpoint_ids` and `exclusion_reasons`; repair source data as appropriate. Missing touchpoints are excluded and do not alone fail the run. |
| Explicit model config unavailable | Restore the config or choose a valid model config. Recomputes without an override reuse the prior run's immutable snapshot. |
| Transient dependency/database exception | Resolve the exception shown in `failure_reason` and correlated logs, then re-trigger the conversion. |
| Credit-weight reconciliation log | Inspect measurement logs and model behavior; the current engine logs this condition but does not mark the run failed for it. |
| Old/missing source classifier version | Run tenant-scoped source-classification repair in Kyber, then verify the linked recomputed run and reconciliation |

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

When correcting source evidence, prefer the Kyber source-classification repair
workflow. It records append-only classification revisions, creates recomputed
attribution runs linked through `prior_attribution_run_id`, and preserves the
original run/config snapshot for audit. Do not edit historical credit rows in
place.

## Reconciliation check after re-run

After a successful re-run, verify reconciliation via the overview endpoint:

```bash
curl "$API_BASE/v1/campaigns/$CAMPAIGN_ID/overview" \
  | jq '.data_quality.reconciliation_status'
```

The current explorer reports `"unknown"` when its implemented count clamps do
not change a value and `"inconsistent"` when one does; it does not emit
`"ok"`, `"warn"`, or `"error"` for this check. For `"inconsistent"`, inspect
the raw campaign population summaries in the `CampaignPopulationExplorer` log.

## Escalation

If repeated runs produce credit-weight reconciliation log entries, escalate
to the measurement engineering team with the run IDs and logs for inspection.
