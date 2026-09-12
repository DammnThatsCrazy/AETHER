---
title: "System Overview"
slug: architecture/current/system-overview
section: architecture
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# System Overview

Aether is a contract-governed intelligence infrastructure platform.

## System Flow

```txt
SDKs / Providers / Connectors
→ canonical observation envelopes
→ /v1/batch ingestion
→ Bronze/Silver normalization
→ identity, campaign, journey, communication, agent, and value resolution
→ graph outbox
→ tenant-scoped graph projections
→ lenses and 360s
→ product, operator, developer, and intelligence surfaces
```

## Services

- **Ingestion** — Accepts `/v1/batch` payloads, validates contracts, persists to durable store
- **Identity** — Resolves and stitches entity identities across sources
- **Graph** — Manages tenant-scoped graph projections
- **Connectors** — Manages provider integrations
- **Tenant Runtime** — Activation, health, plan limits, entitlements
- **API** — REST and GraphQL surfaces
- **Noesis** — Analytical intelligence surface (productized graph view)

## Current State

The system is in pre-production private alpha. Core ingestion, identity resolution, graph projection, and Profile360 are functional. Connector runtime, tenant activation spine, and production operations are converging.
