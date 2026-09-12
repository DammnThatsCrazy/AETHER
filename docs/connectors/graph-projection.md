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

Normalized connector events are projected into the tenant-scoped graph through the same pipeline as SDK observations.

## Flow

1. Connector normalizer emits canonical event
2. Event enters the ingestion pipeline
3. Identity resolution stitches entities
4. Graph projection writes nodes and edges
5. Explainability metadata is attached

## Rule

Connectors do not write directly to the graph. All graph mutations flow through the governed projection pipeline.
