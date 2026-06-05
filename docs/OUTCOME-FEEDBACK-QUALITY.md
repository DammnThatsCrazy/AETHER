---
title: Outcome Feedback Quality
slug: data/outcome-feedback-quality
section: data
visibility: I
audience: [ai, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_DATA_QUALITY_ENABLED
  - AETHER_OUTCOME_FEEDBACK_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Outcome Feedback Quality

Measures the health of the outcome-feedback loop that powers confidence updates
and the Outcome Ledger: outcome volume, missing outcome values, outcome delay,
outcome label distribution, duplicate outcomes, value outliers, confidence-delta
anomalies, and outcome/recommendation mismatch attempts.

Mismatch attempts (an outcome claiming to belong to a recommendation it does not)
are rejected and surface as `outcome_feedback_drift`
[Drift Events](DRIFT-DETECTION.md). Rising outcome delay degrades freshness used
by reliability SLOs.

Tenant report: `GET /v1/data-quality/outcomes`. Operator report:
`GET /v1/admin/kyber/intelligence-quality/outcomes`.

See [Outcome Ledger](OUTCOME-LEDGER.md) and [Data Quality](DATA-QUALITY.md).
