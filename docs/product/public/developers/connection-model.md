---
title: Connection Model
slug: developers/connection-model
section: developer
visibility: P
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.12.0"
estimated_read_minutes: 5
toc_depth: 3
canonical_owner: sdk@aether
---
# Connection Model
Every Aether integration should answer four questions:
1. What system or actor produced the evidence?
2. How did the evidence enter Aether?
3. What consent, tenant, freshness, and provenance context travels with it?
4. Which relationship or perspective can the evidence support?
## Connection paths
An observation may arrive through an SDK, connector, signed webhook, import,
event API, or controlled agent/service path. These are transport and capture
choices. They are not interchangeable with identity truth or relationship truth.
## Relationship path
After ingestion, the platform can preserve or resolve links among people,
accounts, organizations, agents, devices, campaigns, communications, journeys,
episodes, and outcomes. The available evidence determines whether a link is
observed, resolved, inferred, unavailable, or requires review.
## Implementation principle
Build integrations to preserve evidence and context. Do not flatten every
source into a generic event that loses the relationship it was meant to explain.
