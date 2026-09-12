---
title: Campaigns
slug: product-campaigns
section: concepts
visibility: P
audience: [buyer]
status: experimental
since_version: "0.1.0"
---

# Campaigns

Campaigns in Aether are intelligence containers that track
performance, touchpoints, and attribution across channels.

## Core Invariant

Source classification is not campaign identity. An observation may
arrive from a source without belonging to any campaign.

## Attribution

Attribution basis is always explicit: `direct`, `temporal`,
`probabilistic`, `benchmark_only`, or `insufficient_evidence`.
Aether does not execute campaigns — it observes and attributes.

## See Also

- `docs/product/360s/campaign-360.md` — Campaign 360 surface
