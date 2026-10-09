---
title: "Connector Graph Projection"
slug: connectors/graph-projection
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Connector Graph Projection

Graph projection is the target destination for accepted connector facts, but the current UPR provider bridge does not project commerce events into the tenant graph. Provider events are written to Bronze/outbox, while provider-origin events are deferred from SDK-oriented Silver and identity consumers. Legacy connector and measurement paths may have separate projectors; their behavior should not be inferred from this UPR flow.

## Flow

1. Provider normalizer emits a canonical event with source lineage
2. UPR applies existing consent and data-scrubbing gates
3. Bronze and outbox persist the admitted event durably
4. A provider-aware authority and projector (not yet implemented for commerce here) resolves accepted facts and identity
5. The projector submits a governed mutation through `GraphMutationGateway.apply`
6. Projections update only after that authorized mutation succeeds

## Rule

Provider adapters do not write directly to the graph. An authorized domain projector must use the graph mutation gateway. Bronze/outbox acceptance alone is not proof of graph projection, source authority, or tenant readiness.
