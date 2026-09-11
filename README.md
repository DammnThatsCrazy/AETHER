# Aether

Aether is the intelligence graph and runtime layer for understanding humans, agents, journeys, value flows, campaigns, communications, and system activity across applications, providers, and autonomous workflows.

## Current Status

Aether is currently a pre-production private alpha.

The repository is being aligned around the first canonical pre-production baseline:

`0.1.0-alpha.0`

> **Source of truth** for SDK behavior lives in [`docs/source-of-truth/`](docs/source-of-truth/).
> Canonical SDK contracts live in [`packages/shared/`](packages/shared/).
> Anything outside those locations that contradicts them is wrong.

## What Aether Does

Aether captures observations from SDKs, providers, and connectors; normalizes them into canonical contracts; projects them into a tenant-scoped intelligence graph; and surfaces that graph through product, operator, developer, and intelligence interfaces.

Core surfaces include:

- Aether Console
- Kyber Operator Console
- Noesis intelligence surfaces
- Developer portal
- SDKs
- Provider and connector workflows
- API, MCP, and future CLI access surfaces

## Repository Map

| Area | Path |
|---|---|
| Applications | `apps/`, `frontend/` |
| Backend services | `Backend Architecture/aether-backend/` |
| Shared packages and SDKs | `packages/` |
| Provider connectors | `connectors/`, `docs/CONNECTORS.md` |
| Canonical contracts | `contracts/`, `packages/shared/contracts/` |
| Documentation | `docs/` |
| Scripts and validators | `scripts/` |
| Tests | `tests/` |
| Deployment | `deploy/` |
| ML Models | `ML Models/aether-ml/` |
| Agent Layer | `Agent Layer/` |

## Core Architecture

```txt
SDKs / Providers / Connectors
→ canonical observation envelopes
→ /v1/batch ingestion
→ Bronze/Silver normalization
→ identity, campaign, journey, communication, agent, and value resolution
→ graph outbox
→ tenant-scoped graph projections
→ lenses and 360s
→ Aether, Kyber, Noesis, developer APIs, MCP, and CLI surfaces
```

Start here:

- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`docs/START_HERE.md`](docs/START_HERE.md)
- [`docs/source-of-truth/repo-truth.md`](docs/source-of-truth/repo-truth.md)
- [`docs/source-of-truth/architecture-truth.md`](docs/source-of-truth/architecture-truth.md)

## Quick Links

- [`docs/source-of-truth/SDK_SCOPE.md`](docs/source-of-truth/SDK_SCOPE.md) — what the SDK is and is not
- [`docs/source-of-truth/EVENT_REGISTRY.md`](docs/source-of-truth/EVENT_REGISTRY.md) — every event the SDK emits
- [`docs/source-of-truth/CONSENT_MODEL.md`](docs/source-of-truth/CONSENT_MODEL.md) — canonical consent purposes
- [`docs/source-of-truth/INGESTION_CONTRACT.md`](docs/source-of-truth/INGESTION_CONTRACT.md) — `POST /v1/batch`
- [`docs/source-of-truth/ENTITY_MODEL.md`](docs/source-of-truth/ENTITY_MODEL.md) — entities shared across Web2 + Web3
- [`docs/source-of-truth/PLATFORM_PARITY.md`](docs/source-of-truth/PLATFORM_PARITY.md) — tiers A/B/C
- [`docs/architecture/BACKEND_INTELLIGENCE_ARCHITECTURE.md`](docs/architecture/BACKEND_INTELLIGENCE_ARCHITECTURE.md) — backend intelligence architecture

## SDKs

The Aether SDKs are thin observation clients.

They collect local observations from the host app or site, attach canonical metadata, batch events, retry safely, and emit to `/v1/batch`.

They do not own provider sync, global identity resolution, attribution, financial normalization, or graph writes.

| Platform | Package | Entry |
|---|---|---|
| **Web** | `@aether/web` | `packages/web/src/index.ts` |
| **iOS** | `AetherSDK` (Swift SPM) | `packages/ios/Sources/AetherSDK/Aether.swift` |
| **Android** | `io.aether:sdk-android` (Kotlin) | `packages/android/src/main/java/com/aether/sdk/Aether.kt` |
| **React Native** | `@aether/react-native` | `packages/react-native/src/index.tsx` |
| **Shared contracts** | `packages/shared/` | Canonical TypeScript contracts |

SDK docs:

- [`docs/sdks/overview.md`](docs/sdks/overview.md)
- [`docs/sdks/parity-matrix.md`](docs/sdks/parity-matrix.md)
- [`docs/source-of-truth/sdk-truth.md`](docs/source-of-truth/sdk-truth.md)

## Provider and Connector Runtime

Providers are external systems.

Connectors are Aether-managed integrations that handle provider authorization, webhook ingestion, sync lifecycle, cursor state, normalization, and graph projection.

Connector docs:

- [`docs/connectors/overview.md`](docs/connectors/overview.md)
- [`docs/connectors/provider-vs-connector.md`](docs/connectors/provider-vs-connector.md)
- [`docs/connectors/connector-lifecycle.md`](docs/connectors/connector-lifecycle.md)
- [`docs/source-of-truth/connector-truth.md`](docs/source-of-truth/connector-truth.md)

## Apps and Productization

Three frontends (all run locally in `local-mocked` mode with no backend):
**Aether** (tenant, `frontend/aether`, :5175), **Kyber** (operator, `frontend/kyber`, :5174),
and the **Demo App** (`frontend/demo`, :5177).

- Local dev and deployment: [`docs/LOCAL-DEVELOPMENT.md`](docs/LOCAL-DEVELOPMENT.md), [`docs/PRODUCTION-DEPLOYMENT.md`](docs/PRODUCTION-DEPLOYMENT.md), [`docs/ENVIRONMENT-VARIABLES.md`](docs/ENVIRONMENT-VARIABLES.md)
- Connectors and ingestion: [`docs/CONNECTORS.md`](docs/CONNECTORS.md), [`docs/DATA-INGESTION-PATHS.md`](docs/DATA-INGESTION-PATHS.md)
- Demo: [`docs/DEMO-APP.md`](docs/DEMO-APP.md)
- API: [`docs/API-REFERENCE.md`](docs/API-REFERENCE.md)
- SDKs: [`docs/SDKS.md`](docs/SDKS.md)
- Readiness: [`docs/PRODUCTIZATION-CHECKLIST.md`](docs/PRODUCTIZATION-CHECKLIST.md), [`docs/SECURITY-READINESS.md`](docs/SECURITY-READINESS.md), [`docs/PREPRODUCTION-READINESS.md`](docs/PREPRODUCTION-READINESS.md)

## Releases

Aether has not reached public production release.

Pre-production versions use SemVer pre-release identifiers:

- `alpha`
- `beta`
- `rc`

See:

- [`VERSION`](VERSION)
- [`CHANGELOG.md`](CHANGELOG.md)
- [`RELEASES.md`](RELEASES.md)
- [`docs/releases/release-policy.md`](docs/releases/release-policy.md)
- [`docs/releases/retrospective-milestones.md`](docs/releases/retrospective-milestones.md)

## Development

```bash
make ci-check              # canonical PR completion gate
npm run test:all           # alias for make ci-check
npm run security:audit     # secret scan + dependency audit
```

See:

- [`DEVELOPMENT.md`](DEVELOPMENT.md)
- [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [`docs/LOCAL-DEVELOPMENT.md`](docs/LOCAL-DEVELOPMENT.md)

> Repository consistency is owned by `scripts/repo_doctor.py` + the root `Makefile`.
> `pyproject.toml` is the canonical platform version source;
> [`docs/source-of-truth/`](docs/source-of-truth/) owns canonical behavior;
> [`packages/shared/contracts/`](packages/shared/contracts/) owns canonical
> SDK / event / consent contracts. Generated docs must be regenerated
> (`make docs-fix`) and committed; source-linked docs must be reviewed before
> stamping. No PR is merge-ready unless `make ci-check` passes.

## Security

See:

- [`SECURITY.md`](SECURITY.md)
- [`docs/security/privacy.md`](docs/security/privacy.md)
- [`docs/security/tenant-isolation.md`](docs/security/tenant-isolation.md)

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | System design, hybrid architecture, data flow |
| [Backend API](docs/BACKEND-API.md) | All API endpoints with request/response examples |
| [Intelligence Graph](docs/INTELLIGENCE-GRAPH.md) | Graph layers, edge types, scoring |
| [Identity Resolution](docs/IDENTITY-RESOLUTION.md) | Cross-device matching algorithms |
| [ML Training Guide](docs/ML-TRAINING-GUIDE.md) | Model training, artifacts, ingestion readiness |
| [Production Readiness](docs/PRODUCTION-READINESS.md) | Infrastructure status, deployment prerequisites |
| [Operations Runbook](docs/OPERATIONS-RUNBOOK.md) | Failure modes, recovery, operational procedures |
| [Connectors](docs/CONNECTORS.md) | Inbound connector framework |
| [Changelog](docs/CHANGELOG.md) | Version history |
| [Contributing](CONTRIBUTING.md) | Development setup, standards, PR process |

## License

Proprietary. All rights reserved.
