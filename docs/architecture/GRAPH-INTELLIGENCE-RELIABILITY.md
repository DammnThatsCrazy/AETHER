---
title: Graph Intelligence Reliability
slug: data/graph-intelligence-reliability
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: 0.1.0
flags: [AETHER_DATA_QUALITY_ENABLED, KYBER_INTELLIGENCE_QUALITY_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Graph Intelligence Reliability

The reliability of the intelligence graph is measured across the full pipeline,
from raw event ingestion through identity resolution, graph mutation, Profile 360,
recommendation generation, decision/action lifecycle, dispatch, and outcome
feedback.

Each stage contributes a normalized quality dimension to the
[Intelligence Quality Score](../operations/DATA-QUALITY.md). Degradation in any stage produces
a [Drift Event](../operations/DRIFT-DETECTION.md) with a recommended action.

## Dimensions

- Event quality — see [Schema Drift](../operations/SCHEMA-DRIFT.md)
- Identity resolution — see [Identity Resolution Quality](../operations/IDENTITY-RESOLUTION-QUALITY.md)
- Graph mutation — see [Graph Quality](../operations/GRAPH-QUALITY.md)
- Profile 360 freshness and coverage
- Recommendation quality — see [Recommendation Quality](../operations/RECOMMENDATION-QUALITY.md)
- Outcome feedback — see [Outcome Feedback Quality](../operations/OUTCOME-FEEDBACK-QUALITY.md)
- Playbook performance — see [Playbook Drift](../operations/PLAYBOOK-DRIFT.md)
- Tenant isolation — see [Tenant Data Contamination](../operations/TENANT-DATA-CONTAMINATION.md)

## Operational coupling

Graph intelligence reliability complements the SRE
[Reliability Operations](../operations/RELIABILITY-OPERATIONS.md) layer: reliability tracks
service/pipeline/queue health and incidents, while intelligence reliability
tracks the *quality* of the data flowing through those pipelines. No external SLA
or certification is claimed.
