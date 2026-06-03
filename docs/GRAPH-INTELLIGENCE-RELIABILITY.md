---
title: Graph Intelligence Reliability
slug: data/graph-intelligence-reliability
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

# Graph Intelligence Reliability

The reliability of the intelligence graph is measured across the full pipeline,
from raw event ingestion through identity resolution, graph mutation, Profile 360,
recommendation generation, decision/action lifecycle, dispatch, and outcome
feedback.

Each stage contributes a normalized quality dimension to the
[Intelligence Quality Score](DATA-QUALITY.md). Degradation in any stage produces
a [Drift Event](DRIFT-DETECTION.md) with a recommended action.

## Dimensions

- Event quality — see [Schema Drift](SCHEMA-DRIFT.md)
- Identity resolution — see [Identity Resolution Quality](IDENTITY-RESOLUTION-QUALITY.md)
- Graph mutation — see [Graph Quality](GRAPH-QUALITY.md)
- Profile 360 freshness and coverage
- Recommendation quality — see [Recommendation Quality](RECOMMENDATION-QUALITY.md)
- Outcome feedback — see [Outcome Feedback Quality](OUTCOME-FEEDBACK-QUALITY.md)
- Playbook performance — see [Playbook Drift](PLAYBOOK-DRIFT.md)
- Tenant isolation — see [Tenant Data Contamination](TENANT-DATA-CONTAMINATION.md)

## Operational coupling

Graph intelligence reliability complements the SRE
[Reliability Operations](RELIABILITY-OPERATIONS.md) layer: reliability tracks
service/pipeline/queue health and incidents, while intelligence reliability
tracks the *quality* of the data flowing through those pipelines. No external SLA
or certification is claimed.
