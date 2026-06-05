---
title: Drift Detection
slug: data/drift-detection
section: data
visibility: I
audience: [ai, architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_DATA_QUALITY_ENABLED
  - KYBER_INTELLIGENCE_QUALITY_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Drift Detection

`DriftEvent` records degradation signals across the intelligence pipeline. Drift
is a first-class, graph-native signal that operators can acknowledge and resolve.

## Drift types

`event_volume_drift`, `schema_drift`, `identity_resolution_drift`,
`graph_mutation_drift`, `profile_freshness_drift`, `recommendation_quality_drift`,
`outcome_feedback_drift`, `playbook_performance_drift`, `tenant_data_contamination`,
`scoring_model_drift`.

## Fields

`drift_event_id`, `tenant_id?`, `drift_type`, `severity`
(`low`/`medium`/`high`/`critical`), `source`, optional affected resource /
recommendation family / playbook / entity-count, `confidence_impact?`, `reason`,
`supporting_metrics`, `recommended_action`, `status`
(`open`/`acknowledged`/`resolved`/`expired`), `detected_at`, `resolved_at?`.

## Lifecycle

Operators acknowledge and resolve drift via
`POST /v1/admin/kyber/intelligence-quality/drift-events/{id}/acknowledge` and
`.../resolve`. Resolution is a sensitive governance action and is written to the
Security audit ledger. Mutations require the operator + `admin` gate.

## Escalation

High/critical `tenant_data_contamination` drift escalates into Security &
Governance — see [Tenant Data Contamination](TENANT-DATA-CONTAMINATION.md). All
drift metadata is secret-sanitized before persistence.

See [Data Quality](DATA-QUALITY.md).
