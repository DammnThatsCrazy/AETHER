# Aether Architecture

Aether is a contract-governed intelligence graph and product runtime.

The system captures observations from SDKs, providers, and connectors; normalizes them through canonical contracts; projects them into a tenant-scoped graph; and surfaces the result through Aether, Kyber, Noesis, SDKs, APIs, MCP, and future CLI access surfaces.

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

## Current Architecture

Read:

- `docs/architecture/current/system-overview.md`
- `docs/architecture/current/runtime-architecture.md`
- `docs/architecture/current/ingestion-architecture.md`
- `docs/architecture/current/graph-architecture.md`
- `docs/architecture/current/sdk-architecture.md`
- `docs/architecture/current/connector-architecture.md`
- `docs/architecture/current/tenant-runtime.md`

## Target Architecture

Read:

- `docs/architecture/target/production-readiness.md`
- `docs/architecture/target/staging-readiness.md`
- `docs/architecture/target/design-partner-readiness.md`
- `docs/architecture/target/tenant-activation-readiness-spine.md`
- `docs/architecture/target/contract-governance-spine.md`
- `docs/architecture/target/360-system-blueprint.md`

## Architecture Decisions

Read:

- `docs/architecture/decisions/`

## Detailed Architecture

For the full backend intelligence architecture, see:

- `docs/ARCHITECTURE.md` — Detailed system map with source-linked references
- `docs/source-of-truth/BACKEND_INTELLIGENCE_ARCHITECTURE.md`
