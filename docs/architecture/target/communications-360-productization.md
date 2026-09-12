---
title: Communications 360 Productization
slug: communications-360-productization
section: architecture
visibility: I
audience: [architect]
status: experimental
since_version: "0.1.0"
---

# Communications 360 Productization

## Target State

Communications 360 is a productized graph view that surfaces all
communication activity for a given entity across channels, campaigns,
and time — providing a unified view of outbound messaging, delivery
state, and engagement.

## Planned Surfaces

- **Entity Communication Timeline**: chronological view of all
  communications sent to an entity.
- **Channel Performance**: delivery rates, engagement rates, and
  opt-out rates per channel.
- **Campaign Communication Summary**: aggregate communication metrics
  per campaign.
- **Consent State**: current consent status per channel and purpose.

## Architecture

```
graph query (entity + communication edges)
→ channel aggregation
→ delivery state resolution
→ consent overlay
→ 360 surface projection
```

## Dependencies

- Communication architecture (current state)
- Graph query surfaces
- Consent-purpose reconciliation
- Connector delivery tracking

## Productization Checklist

- [ ] Communication event schema finalized
- [ ] Channel-level aggregation queries
- [ ] Consent overlay integration
- [ ] Aether UI surface implementation
- [ ] Kyber diagnostics for communication health
