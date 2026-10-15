---
title: Identity and Relationships
slug: developers/identity-and-relationships
section: developer
visibility: P
audience: [dev-senior, architect, security]
status: stable
since_version: "8.12.0"
estimated_read_minutes: 6
toc_depth: 3
canonical_owner: identity@aether
---
# Identity and Relationships
Aether keeps source evidence separate from the relationships it may support.
Identity resolution is tenant-scoped, evidence-backed, and explicit about
confidence and uncertainty.
## Preserve the path
An integration should keep the identifiers, source, timestamps, consent, and
correlation context needed to explain how two records became related. Do not
flatten every source into an anonymous event if that removes the relationship
the event was meant to explain.
## Relationship states
A relationship may be observed, resolved, inferred, unavailable, or waiting for
review. These states must remain distinguishable in APIs, graph projections,
profiles, journeys, and 360 views.
## Developer responsibility
Use the documented identity and relationship contracts, keep tenant scope
explicit, and test missing, conflicting, stale, and revoked evidence. Aether
does not silently turn a source assertion into universal identity truth.
