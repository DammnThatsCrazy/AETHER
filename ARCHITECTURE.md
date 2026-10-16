# Aether Architecture

Aether is a contract-governed intelligence graph and product runtime. It captures observations from SDKs, providers, and connectors; normalizes them through canonical contracts; projects them into a tenant-scoped graph; and surfaces the result through Aether, Kyber, Noesis, SDKs, and APIs.

This file is a gateway. The architecture itself lives under `docs/architecture/`.

## System flow

```text
SDKs / Providers / Connectors
  → canonical observation envelopes
  → /v1/batch ingestion
  → Bronze/Silver normalization
  → identity, campaign, journey, communication, agent, and value resolution
  → graph outbox
  → tenant-scoped graph projections
  → lenses and 360s
  → Aether, Kyber, Noesis, developer APIs, SDKs
```

Current and target state are kept apart on purpose: `current/` describes what exists, `target/` describes intended end state. A target document is not a claim that the capability is implemented.

## Read next

| Question | Read |
|---|---|
| What exists today? | [`docs/architecture/current/system-overview.md`](docs/architecture/current/system-overview.md) |
| What is the intended end state? | [`docs/architecture/target/`](docs/architecture/target/) |
| Why was it built this way? | [`docs/architecture/decisions/`](docs/architecture/decisions/) |
| Architecture reset plan and proof requirements | [`docs/architecture/blueprints/architecture-reset/README.md`](docs/architecture/blueprints/architecture-reset/README.md) |
| Canonical architecture rules | [`docs/reference/source-of-truth/architecture-truth.md`](docs/reference/source-of-truth/architecture-truth.md) |
| Repository layout | [`docs/reference/source-of-truth/repo-truth.md`](docs/reference/source-of-truth/repo-truth.md) |
| Canonical contracts | [`packages/shared/contracts/`](packages/shared/contracts/) |

## Current architecture

- [System overview](docs/architecture/current/system-overview.md)
- [Runtime](docs/architecture/current/runtime-architecture.md)
- [Ingestion](docs/architecture/current/ingestion-architecture.md)
- [Graph](docs/architecture/current/graph-architecture.md)
- [SDKs](docs/architecture/current/sdk-architecture.md)
- [Connectors](docs/architecture/current/connector-architecture.md)
- [Tenant runtime](docs/architecture/current/tenant-runtime.md)
- [Security](docs/architecture/current/security-architecture.md)
