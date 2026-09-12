---
title: Journeys
slug: product-journeys
section: concepts
visibility: P
audience: [buyer]
status: experimental
since_version: "0.1.0"
---

# Journeys

Journeys track entity progression across touchpoints, devices, and
time. Journey touchpoints are not attribution credits — they record
that an interaction occurred.

## Journey Lifecycle

```
started → checkpoint → paused → resumed → completed
                                        → abandoned
```

## Cross-Device Stitching

Journeys span devices through identity resolution. When an entity
is identified on a new device, the journey resumes with stitched
context.

## See Also

- `docs/product/lenses/journeys.md` — Journeys lens
- `docs/product/360s/journey-360.md` — Journey 360 surface
