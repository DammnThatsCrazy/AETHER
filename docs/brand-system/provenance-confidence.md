---
title: Provenance, confidence, and freshness
slug: architecture/brand-system/provenance-confidence
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Provenance, confidence, and freshness

These are independent evidence dimensions:

| Dimension | Answers | Renderer |
| --- | --- | --- |
| Provenance | Where did it come from? | `ProvenanceIcon` |
| Confidence | How certain is the assessment? | `ConfidenceIndicator` |
| Freshness | When was it observed? | `FreshnessIcon` plus timestamp |

```tsx
<ProvenanceIcon provenance="provider" />
<ConfidenceIndicator confidence="medium" />
<FreshnessIcon freshness="aging" />
```

- `provider` provenance does not imply high confidence, live status, or recency.
- A confidence signal does not imply severity or authority.
- Pair freshness with an actual timestamp whenever one is available.
- Use text/non-color signals in graph and chart contexts; retain the data source
  and any existing source-of-truth fields.
