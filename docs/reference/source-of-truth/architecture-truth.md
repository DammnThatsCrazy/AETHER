---
title: Architecture truth
slug: source-of-truth/architecture-truth
section: reference
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: 0.1.0
---
# Architecture Truth

Aether is organized around canonical contracts and tenant-scoped graph projections.

## Canonical Flow

```txt
SDKs / Providers / Connectors
→ canonical observation envelopes
→ /v1/batch ingestion
→ Bronze/Silver normalization
→ identity, campaign, journey, communication, agent, and value resolution
→ graph outbox
→ tenant-scoped graph projections
→ lenses and 360s
→ Aether, Kyber, Noesis, APIs, MCP, CLI
```

## Runtime Boundaries

| Layer | Owns |
|---|---|
| SDKs | First-party observation capture |
| Providers | External source systems |
| Connectors | Provider auth, sync, webhooks, cursors, normalizers |
| Ingestion | Batch acceptance, validation, durability |
| Contracts | Canonical schema and compatibility |
| Identity | Entity resolution and relationship stitching |
| Graph | Projection, traversal, query, explanation |
| Lenses | Interpretive graph views |
| 360s | Productized graph surfaces |
| Tenant runtime | Activation, readiness, plan limits, entitlements, health |
