# Aether

Aether is a tenant-facing intelligence graph runtime. It brings together observations from applications and external systems, resolves them into a tenant-scoped graph, and presents evidence-backed profiles, journeys, and intelligence to each tenant.

**Status:** private pre-production alpha. The architecture reset is in progress. The target architecture below describes the direction of that work; it does not mean every target capability is implemented or production-ready.

## Product boundaries

- **Aether** is the customer-facing product for tenant data, graph views, and intelligence.
- **Kyber** is the internal operator console for diagnosis, review, recovery, and release operations. It is not a customer product or a separate authority for graph and identity decisions.

## Intake paths and target runtime spine

Current intake includes SDK batches, external feeds, imports, provider sync and webhooks, and legacy connectors. The reset is aligning these paths around shared contracts, tenant policy, retained evidence, backend-owned identity, and governed graph mutations.

The target runtime spine is:

```text
tenant/access
  → source/intake
  → evidence/event log
  → normalization
  → identity/resolution
  → graph
  → intelligence/views
  → explanation
  → action/outcome
```

The architecture reset is in progress, so this target describes the intended shared authorities rather than a claim that every stage is already centralized. The [architecture reset plan](docs/blueprints/architecture-reset/README.md) tracks current authorities, cutovers, and required proof, including consistent replay, correction, evaluation, and recovery. A local fixture or passing focused check does not establish design-partner or production readiness.

## Repository map

| Path | Purpose |
|---|---|
| `apps/aether/`, `apps/kyber/` | Aether customer app and Kyber operator console |
| `services/backend/` | Backend API, ingestion, identity, graph, and intelligence runtime |
| `services/ml/`, `services/agents/`, `services/compliance/` | ML, internal workers, and compliance services |
| `packages/` | Shared packages, clients, SDKs, and contracts |
| `packages/shared/contracts/` | Canonical event, consent, observation, and other shared contracts |
| `docs/` | Architecture, operating guidance, and source-of-truth documentation |
| `scripts/`, `tests/`, `deploy/` | Repository tooling, tests, and deployment configuration |

## Start here

**Understand the system**

- [Current architecture and target direction](ARCHITECTURE.md)
- [Aether root architecture target](docs/architecture/AETHER_ROOT_ARCHITECTURE.md)
- [Architecture reset plan and proof requirements](docs/blueprints/architecture-reset/README.md)
- [Repository truth](docs/source-of-truth/repo-truth.md) and [architecture truth](docs/source-of-truth/architecture-truth.md)

**Work with contracts and intake**

- Canonical contracts: [`packages/shared/contracts/`](packages/shared/contracts/)
- Supported [ingestion paths](docs/DATA-INGESTION-PATHS.md)
- Canonical behavior and ownership: [`docs/source-of-truth/`](docs/source-of-truth/)

**Develop**

- [Local development setup](docs/LOCAL-DEVELOPMENT.md)
- [Contribution guide](CONTRIBUTING.md)

The repository's consistency system is `scripts/repo_doctor.py` and the root `Makefile`. Follow the relevant guidance above when changing code or documentation; a single focused check is not proof of PR merge-readiness.

## License

Proprietary. All rights reserved.
