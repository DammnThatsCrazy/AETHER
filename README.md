# Aether

**Aether is an intelligence graph runtime and the operator control plane that keeps it honest.**

It captures observations from applications and external systems, keeps them as replayable evidence, resolves them into a tenant-scoped graph of people, accounts, organizations, agents, campaigns, communications and value, and presents evidence-backed profiles, journeys and intelligence to each tenant. Every conclusion carries its sources, evidence trail and confidence, and every stage can be replayed, corrected and audited.

Aether is built by **Olympus Labs**.

> **Status: private pre-production alpha** (`VERSION`). The architecture reset is in progress. Target architecture in this repository describes direction, not a claim that every capability is implemented or production-ready. A passing local fixture or focused check does not establish design-partner or production readiness. Readiness claims are made only by the scorecard (`scripts/production_status.py`) and the release gates.

---

## Contents

1. [What Aether is](#what-aether-is)
2. [Products and surfaces](#products-and-surfaces)
3. [How data moves: the runtime spine](#how-data-moves-the-runtime-spine)
4. [The control plane](#the-control-plane)
5. [Architecture layers and where they live](#architecture-layers-and-where-they-live)
6. [Repository map](#repository-map)
7. [The root, explained](#the-root-explained)
8. [Branches, environments and delivery](#branches-environments-and-delivery)
9. [Getting started](#getting-started)
10. [Working in this repository](#working-in-this-repository)
11. [Where to read next](#where-to-read-next)
12. [Security, versions and licence](#security-versions-and-licence)

---

## What Aether is

Aether answers one question for a tenant: **what is actually happening across our applications, customers, agents and money, and how do we know?**

- **Evidence first.** Observations enter as raw evidence in an immutable, replayable event log. Nothing downstream rewrites history; it re-derives from evidence.
- **One authority per kind of truth.** Intake, evidence, normalization, identity resolution, graph writes, intelligence and explanation each have a single owning path. Duplicate or parallel authorities are retired, not tolerated.
- **Backend-owned identity.** Identity resolution is decided by the backend with confidence scoring, merge / no-merge / review-needed decisions and a decision log. Clients never assert canonical identity.
- **Tenant isolation everywhere.** Every read, write, graph vertex and callback is tenant-scoped.
- **Explainable by construction.** Source trails, evidence trails, confidence trails and rationale for identity, journeys, attribution, lenses, recommendations and actions are first-class outputs.
- **Contract-governed.** Canonical contracts in [`packages/shared/contracts/`](packages/shared/contracts/) are the source for generated types, backend registries, SDKs and docs.

Core concepts: **Profile** (human, account, organization), **Agent**, **Journey** and **Episode**, **Campaign**, **Communication**, **Signal**, **Syndicate**, **Value**, **Risk**, **Lens** (a view that interprets graph state for a use case) and **360** (a complete view around one entity or domain). Definitions: [`product-truth.md`](docs/reference/source-of-truth/product-truth.md).

## Products and surfaces

| Surface | What it is | Where it lives |
|---|---|---|
| **Aether** | The customer-facing product: tenant data, graph views, journeys, value and intelligence. | [`apps/aether-web/`](apps/aether-web/), [`apps/aether-mobile/`](apps/aether-mobile/) |
| **Kyber** | The internal operator console: diagnosis, review, recovery and release operations. Not a customer product, and not a separate authority for graph or identity decisions. | [`apps/kyber-web/`](apps/kyber-web/), [`apps/kyber-mobile/`](apps/kyber-mobile/) |
| **Noesis** | Intelligence surfaces inside the product. | `services/api/` and the Aether app |
| **SDKs** | Client libraries that send observations (web, server, Python, iOS, Android, React Native). | [`packages/sdk/`](packages/sdk/) |
| **Access Kit** | Node CLI, local MCP stdio bridge and hosted MCP HTTP service for bounded customer operations. | [`packages/access-kit/`](packages/access-kit/) |
| **Public sites** | Olympus Labs and Aether marketing, documentation and status pages. | [`apps/public-site/`](apps/public-site/), [`apps/marketing-aether/`](apps/marketing-aether/), [`apps/marketing-olympus/`](apps/marketing-olympus/), [`apps/docs/`](apps/docs/), [`apps/status/`](apps/status/) |
| **Demo** | Demo tenant experience and data. | [`apps/demo/`](apps/demo/) |

**Customer app surfaces (target):** Snapshot, Graph, Profiles, Journeys, Signals, Lenses, Value, Connectors, Settings, plus specialized 360 views. The shipped navigation today reaches Home, Graph, Profiles, Agents, Campaigns, Geography, Value, Connectors and Settings; surfaces without a backing read model are shown as not ready rather than faked. See [`docs/product/360-surfaces.md`](docs/product/360-surfaces.md).

## How data moves: the runtime spine

```text
tenant → source → evidence → normalization → resolution → graph → intelligence → explanation → action → outcome
```

| # | Stage | What happens |
|---|---|---|
| 1 | Tenant | A tenant, its users, roles, plan entitlements and feature availability are established. |
| 2 | Source | SDKs, connectors, webhooks, imports and partner data are connected, each with a source trust level. |
| 3 | Evidence | Raw evidence is captured in an envelope with source metadata, actor hints, timestamps and lineage. |
| 4 | Event log | Evidence lands in an immutable, replayable event log; failed and quarantined events are kept. |
| 5 | Normalization | Event typing, source classification, field, location, timezone and currency normalization, with explicit missing / empty / zero semantics and schema versioning. |
| 6 | Resolution | Human, account, organization, agent and session identities are resolved; merges, no-merges and review decisions are logged and correctable. |
| 7 | Graph | Profiles, agents, accounts, organizations, campaigns, communications, journeys, touchpoints, conversions, value records and relationships are written through governed graph mutations; snapshots and diffs are kept. |
| 8 | Intelligence | Lenses, signals, syndicates, behavior patterns, attribution and value analysis, recommendations, actions and outcomes are derived. |
| 9 | Explanation | Source, evidence, confidence and rationale trails are attached to what is shown. |
| 10 | Action and outcome | Recommendations and actions are surfaced; outcomes are measured; the system learns, corrects, replays and improves. |

## The control plane

The control plane is what makes the runtime operable and trustworthy:

```text
failure → replay → schema governance → tenant isolation → authority → observability → readiness → cost → security
```

- **Failure handling:** retries, dead-letter queues, quarantined events, partial graph states, degradation states, action eligibility.
- **Replay and backfill:** consistent replay and correction paths, with cost visibility.
- **Schema and contract governance:** canonical contracts, compatibility tiers, parity validators.
- **Operator workflows (Kyber):** tenant activation, source / connector / SDK-heartbeat health, failed-event queue, identity review, graph diagnostics, feature flags, readiness dashboard, billing and access status, cost tracking, incident runbooks.
- **Evaluation:** golden datasets, fixture tenants, expected graph outputs, false-merge tests, lens quality and attribution sanity tests.
- **Cost controls:** tenant usage, event volume, connector sync, graph query, replay and lens execution cost.
- **Security and runbooks:** threat model, poisoning defense, operator audit logs, incident handling, rollback paths and recovery playbooks.

## Architecture layers and where they live

| Layer | Responsibility | Primary location |
|---|---|---|
| 1. Tenant and access | Tenants, workspaces, users, roles, permissions, billing and pilot state, entitlements, isolation | `services/api/tenancy/`, `services/api/billing/` |
| 2. Source and intake | SDKs, connectors, webhooks, imports, partner and commerce sources, adapters, trust levels | `packages/sdk/`, `services/api/connectors/`, `services/api/ingestion/` |
| 3. Evidence and event log | Raw evidence, immutable log, envelopes, lineage, replayable storage, quarantine | `services/api/ingestion/`, `services/api/replay/`, `packages/shared/contracts/` |
| 4. Normalization | Typing, classification, field / location / timezone / currency normalization, schema versioning | `services/api/ingestion/`, `packages/shared/` |
| 5. Resolution | Identity, account, agent and session resolution; merge decisions, confidence, correction | `services/api/identity/` |
| 6. Graph | Entities, relationships, mutation rules, snapshots, diffs, geography, infrastructure | `services/api/graph/` |
| 7. Intelligence | Lenses, signals, behavior, attribution, value, recommendations, actions, outcomes | `services/api/intelligence/`, `services/api/journeys/`, `services/api/value/`, `services/api/actions/` |
| 8. Explainability | Source, evidence, confidence and rationale trails | `services/api/intelligence/`, `services/api/shared/` |
| 9. Product surface | Aether customer app and specialized 360 views | `apps/aether-web/`, `apps/aether-mobile/`, `packages/ui/` |
| 10. Operator control plane | Kyber console, diagnostics, replay, readiness, cost, runbooks | `apps/kyber-web/`, `services/api/governance/`, `services/api/workers/` |
| 11. Delivery and governance | Contracts, CI tiers, deployment profiles, observability, threat model, lifecycle policy, release scorecards | `config/`, `scripts/`, `infra/`, `.github/`, `docs/` |

The authoritative statement of current versus target architecture is in [`docs/architecture/`](docs/architecture/) (`current/`, `target/`, `decisions/`) and the [architecture reset plan](docs/architecture/blueprints/architecture-reset/README.md). When this table and those documents disagree, the documents win.

## Repository map

```text
aether/
├── apps/                      Deployable front ends
│   ├── aether-web/            Aether customer app
│   ├── aether-mobile/         Aether companion app (Expo)
│   ├── kyber-web/             Kyber operator console
│   ├── kyber-mobile/          Kyber operator companion app (Expo, separately gated)
│   ├── public-site/           Unified Olympus Labs + Aether public site
│   ├── marketing-aether/      Aether marketing site
│   ├── marketing-olympus/     Olympus Labs corporate site
│   ├── docs/                  Documentation site (public, customer, internal tiers)
│   ├── status/                Public service status page
│   └── demo/                  Demo experience
│
├── packages/                  Shared code, clients and contracts
│   ├── shared/                Canonical contracts (packages/shared/contracts/) and shared types
│   ├── contracts/             Contract policy, delivery contracts, smart contracts
│   ├── sdk/                   web, server, python, ios, android, react-native, mobile-core
│   ├── access-kit/            Agent / CLI / MCP access package
│   ├── ui/                    Brand, core, marketing and mobile UI primitives
│   └── config/                Shared TypeScript configuration
│
├── services/                  Backend runtimes
│   ├── api/                   FastAPI backend, organized by domain:
│   │   ├── tenancy/  billing/        tenant + access
│   │   ├── connectors/  ingestion/   source + intake, evidence, normalization
│   │   ├── identity/                 resolution
│   │   ├── graph/                    graph
│   │   ├── intelligence/  journeys/  value/  actions/    intelligence, outcomes
│   │   ├── governance/               consent, diagnostics, operator surfaces
│   │   ├── replay/  workers/         replay, projections, background work
│   │   └── shared/  middleware/  repositories/  alembic/ cross-cutting + migrations
│   ├── ml/                    ML models, training, serving
│   ├── agents/                Internal agent workers and controller
│   └── compliance/            GDPR / SOC 2 services
│
├── infra/                     Deployment and runtime configuration
│   ├── aws/  terraform/       AWS and ClickHouse infrastructure
│   ├── local/                 Local docker-compose stack
│   ├── kafka/  clickhouse/    Streaming and analytics definitions
│   ├── observability/         Prometheus, Grafana, Loki, Alertmanager
│   ├── cicd/  lambda/        Pipeline stages and Lambda handlers
│   ├── model-runtime/         Model runtime stack
│   ├── integration/           Durable integration stack
│   └── legacy-staging/        Retained staging bootstrap material
│
├── tests/                     Cross-cutting test suites
│   ├── unit/  integration/  e2e/  contracts/  sdk/  security/
│   ├── graph/  identity/  ingestion/  journeys/  lenses/  value/  campaigns/  connectors/
│   └── fixtures/  mocks/  load/  chaos/  readiness/  prod_equivalent/
│
├── docs/                      Documentation
│   ├── architecture/          Current, target and decided architecture; blueprints
│   ├── product/               Product, 360 surfaces, packaging, brand system
│   ├── operations/            Runbooks, deployment, release policy, local development
│   ├── reference/             API, contracts, connectors, SDKs and source-of-truth docs
│   ├── engineering/           Engineering notes, including CI v2
│   ├── archive/               Retired material (legacy names live only here)
│   └── _generated/            Generated artifacts (never edited by hand)
│
├── config/                    Machine-readable policy: deployment profiles, CI, readiness, IAM contracts
├── scripts/                   Repository tooling: validators, generators, release and staging tools
└── .github/                   Workflows (ci.yml is the single PR authority) and templates
```

Backend domain packages are top-level import names under `services/api/` (for example `identity`, `graph`, `value`).

## The root, explained

Every tracked root entry is allowlisted by [`scripts/validate_root_layout.py`](scripts/validate_root_layout.py); adding one is a deliberate change.

| Group | Entries | Purpose |
|---|---|---|
| **Code and content** | `apps/` `packages/` `services/` `infra/` `tests/` `docs/` | The product, split by what it is. |
| **Policy and tooling** | `config/` `scripts/` `.github/` | How the repository is governed, validated and delivered. |
| **Read first** | `README.md` `ARCHITECTURE.md` `DEVELOPMENT.md` `CONTRIBUTING.md` `RELEASES.md` `CHANGELOG.md` `SECURITY.md` `LICENSE` | Orientation, rules and history. `ARCHITECTURE.md`, `DEVELOPMENT.md` and `RELEASES.md` are short gateways into `docs/`. |
| **Agent contracts** | `AGENTS.md` `CLAUDE.md` `.codex/` `.claude/` | How automated agents must work here (verification cadence, forbidden behavior). |
| **Version and build** | `VERSION` `pyproject.toml` `Makefile` | `pyproject.toml` owns the platform version; `VERSION` mirrors it; `make` is the command surface. |
| **JavaScript workspace** | `package.json` `pnpm-workspace.yaml` `pnpm-lock.yaml` `package-lock.json` `.npmrc` `tsconfig.json` `eslint.config.mjs` `vitest.config.fps.ts` `amplify.yml` | Workspace, dependency and build configuration for the web apps and packages. `pnpm-workspace.yaml` defines the workspace and its build allowlist (`allowBuilds`). Two lockfiles are intentional: `pnpm-lock.yaml` for the workspace, and `package-lock.json`, which the app Dockerfiles, delivery lockfile fingerprinting and `repo_doctor`'s `npm ci` use. |
| **Hygiene** | `.gitignore` `.dockerignore` `.pre-commit-config.yaml` `.devcontainer/` | Ignore rules, hooks and a dev container. |
| **Checked-in evidence** | `.artifacts/` | Generated readiness and frontend data-truth reports written and read by repository tooling. |

## Branches, environments and delivery

Aether uses three persistent branches, each a gate. **Nothing moves to the next gate until someone says so.**

| Branch | Purpose |
|---|---|
| `development` | Integration branch. All development lands here first through pull requests; a standing development web app deploys from it. |
| `staging` | Validation. Receives promotions from `development` and builds the commit-bound release. |
| `main` | Production line. Receives promotions from `staging` only. |

- Promoting `development` to `staging` never promotes `staging` to `main`; each is its own explicit step.
- A push to `staging` builds and publishes an immutable release; deploying to the staging runtime additionally requires `STAGING_RUNTIME_ENABLED`. Production is deployed only by an explicit dispatch of an approved build.
- Terraform is plan-only in CI; applies are explicit, environment-gated and reviewed.
- Keep a pull request in **draft** while work accumulates. Marking it **ready for review** starts the single blocking authority, **`ci / verdict`** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), which reruns on every new head. Specialized workflows add supplementary evidence but are not independent merge blockers.

## Getting started

Prerequisites: Python 3.10+, Node.js with npm (pnpm for the workspace), and Docker with Compose and Make for the container stack.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev,backend,agent]"
npm ci
source .venv/bin/activate

cp config/environments/.env.local.example .env
cp apps/aether-web/.env.example apps/aether-web/.env.local
cp apps/kyber-web/.env.example apps/kyber-web/.env.local
```

Keep `AETHER_ENV=local`. Then run the backend either host-run with in-memory repositories (`make serve-backend`, port 8000) or as the container stack (`make dev`). Full instructions, including the web apps, are in [`docs/operations/local-development.md`](docs/operations/local-development.md).

| Command | Purpose |
|---|---|
| `make bootstrap` | Isolated `.venv` with all extras |
| `make serve-backend` | API server on port 8000 |
| `make dev` / `make dev-down` | Minimal local stack (Postgres + backend) / stop it |
| `make test` | Python test subsystems |
| `make lint` / `make typecheck` | Ruff / mypy |
| `make repo-doctor` | Full consistency check, no mutations |
| `make repo-doctor-fix` | Regenerate generated docs, then validate |
| `make docs-check` | Docs gate |
| `make docs-generate-changed` | Refresh `source_hashes` for docs you have reviewed |
| `make verification-disposition BASE=origin/development EXECUTE=1` | Local rehearsal of the normal PR authority |

## Working in this repository

1. **Branch from `development`**, keep the pull request in draft while you work, and target `development`.
2. **Check what your change owns.** Source changes can require derived surfaces; see [`repo_consistency_ownership.json`](docs/reference/source-of-truth/repo_consistency_ownership.json).
3. **Update authored docs when behavior changes.** Behavior, contracts, SDKs, connectors, graph projections, 360 surfaces, release state and deployment changes must update the matching page under [`docs/reference/source-of-truth/`](docs/reference/source-of-truth/).
4. **Never hand-edit generated docs** (`docs/_generated/`, `docs/REPO-INDEX.md`, `docs/AUTOMATION.md`). Fix the source or generator, then `make repo-doctor-fix`.
5. **Review before restamping.** If `make docs-check` reports stale source-linked docs, read each against its `source_files`, update content, then run `make docs-generate-changed`. Never restamp everything to silence a check.
6. **Do not weaken validators to pass CI**, and do not treat a single focused check as proof of merge-readiness.
7. **Mark ready for review once**, when the work is integrated, documented and regenerated.

Rules in full: [`CONTRIBUTING.md`](CONTRIBUTING.md), [`AGENTS.md`](AGENTS.md), [`DEVELOPMENT.md`](DEVELOPMENT.md).

## Where to read next

| If you want to… | Read |
|---|---|
| Orient quickly | [`docs/START_HERE.md`](docs/START_HERE.md) |
| Understand the architecture | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`docs/architecture/`](docs/architecture/), [root architecture target](docs/architecture/AETHER_ROOT_ARCHITECTURE.md) |
| See the reset plan and its proof requirements | [`docs/architecture/blueprints/architecture-reset/README.md`](docs/architecture/blueprints/architecture-reset/README.md) |
| Know what is canonical | [`docs/reference/source-of-truth/`](docs/reference/source-of-truth/): product, architecture, repo, graph, SDK, connector, release and naming truth |
| Work with contracts and intake | [`packages/shared/contracts/`](packages/shared/contracts/), [ingestion paths](docs/reference/DATA-INGESTION-PATHS.md) |
| Call the API | [`docs/reference/BACKEND-API.md`](docs/reference/BACKEND-API.md) |
| Run or deploy | [`docs/operations/`](docs/operations/): local development, deployment, runbooks, release policy |
| See how CI works | [`docs/operations/CICD.md`](docs/operations/CICD.md), [`docs/engineering/ci-v2/`](docs/engineering/ci-v2/) |

## Security, versions and licence

- **Security:** report vulnerabilities responsibly as described in [`SECURITY.md`](SECURITY.md); it also links the privacy, tenant-isolation, credential-handling and retention documents.
- **Versions:** `pyproject.toml` owns the platform version; check alignment with `python scripts/bump_version.py --check`. Release classes and policy: [`RELEASES.md`](RELEASES.md), [`CHANGELOG.md`](CHANGELOG.md).
- **Licence:** proprietary. All rights reserved.
