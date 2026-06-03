---
title: Recommendation Quality
slug: data/recommendation-quality
section: data
visibility: I
audience: [ai, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_DATA_QUALITY_ENABLED
  - AETHER_RECOMMENDATIONS_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Recommendation Quality

Tracks recommendation funnel health and quality drift: generated / viewed /
approved / rejected / acted / outcomes counts; success, failure, and neutral
rates; suppression rate; average confidence delta; evidence quality score;
freshness and governance penalty averages; and the low-confidence
recommendation rate.

A sustained rise in the low-confidence rate or a drop in success rate for a
recommendation family produces a `recommendation_quality_drift`
[Drift Event](DRIFT-DETECTION.md) scoped to the affected family.

Tenant report: `GET /v1/data-quality/recommendations`. Operator report:
`GET /v1/admin/kyber/intelligence-quality/recommendations`.

See [Data Quality](DATA-QUALITY.md),
[Recommendation Families](RECOMMENDATION-FAMILIES.md), and
[Decision & Outcome Intelligence](DECISION-OUTCOME-INTELLIGENCE.md).
