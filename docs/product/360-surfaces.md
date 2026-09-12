---
title: 360 Surfaces
slug: 360-surfaces
section: concepts
visibility: P
audience: [buyer, dev-senior]
status: experimental
since_version: "0.1.0"
---

# 360 Surfaces

## Overview

360 surfaces are productized read/query views over the intelligence
graph. Each 360 provides a complete view of a specific entity type
or concept.

## Available 360s

| 360 Surface | Entity | Description |
|---|---|---|
| Profile 360 | Person / Organization | Entity attributes, activity, value |
| Campaign 360 | Campaign | Performance, touchpoints, attribution |
| Journey 360 | Journey | Stage progression, handoffs |
| Agent 360 | Agent | Lifecycle, actions, decisions |
| Communication 360 | Communication | Delivery, engagement, consent |
| Value 360 | Value | Revenue, LTV, economic flow |
| Risk 360 | Risk | Risk signals, anomalies |

## Architecture

360 surfaces are query-time projections over graph state. They do
not store data independently — all data comes from the intelligence
graph.

## See Also

- `docs/product/360s/` — detailed 360 surface documentation
- `docs/architecture/target/360-system-blueprint.md` — 360 system design
