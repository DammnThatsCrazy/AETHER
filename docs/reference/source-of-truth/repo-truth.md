---
title: Repo truth
slug: source-of-truth/repo-truth
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Repo Truth

This document defines the canonical organization of the Aether repository.

## Root Rule

The root directory contains canonical entry points, repository configuration,
and explicitly registered support/evidence roots. It does not contain
parallel architecture or runtime implementation trees.

Architecture, design, SDK, connector, release, and operational documents belong under `docs/`.
Validation and generation code belongs under `scripts/`; runtime configuration
under `config/`; tests under `tests/`; deployment under `infra/`; and
generated evidence under `.artifacts/`, `docs/reference/reports/`, or `release-evidence/` as
declared by the ownership registries. These are intentional support roots,
not alternate service homes.

## Canonical Directories

| Directory | Purpose |
|---|---|
| `apps/` | User-facing applications and marketing surfaces |
| `services/` | Backend runtime services |
| `packages/` | Shared packages, SDKs, clients, UI, contracts package |
| `services/api/connectors/integrations/connectors/` | Provider connector runtime owned by the backend service |
| `packages/contracts/` | Canonical event, graph, identity, journey, campaign, communication, value, and agent contracts |
| `docs/` | Human-readable documentation |
| `scripts/` | Repository validation, generation, release, docs, and contract scripts |
| `tests/` | Cross-package and system tests |
| `apps/` | Product applications: the web apps (Aether, Kyber, demo, marketing, status, docs, site, shared UI) and the mobile shells |
| `infra/` | Deployment configurations |
| `config/` | Runtime configuration |

## Canonical service and deployment mapping

The active implementation trees that were previously placed at the repository
root now have one canonical home:

| Concern | Canonical path | Archived duplicate/orphan path |
|---|---|---|
| Python backend, ingestion, lake, graph, and intelligence | `services/api/` | `docs/archive/legacy-architecture/backend/` |
| Journey compilation, persistence, attribution, and routes | `services/api/journeys/measurement/` | `docs/archive/legacy-architecture/backend/services/journey-service/` (test fixture only) |
| ML training and serving | `services/ml/` | — |
| Internal broker-coupled agents | `services/agents/` | — |
| Compliance controls | `services/compliance/` | — |
| AWS deployment and Terraform | `infra/aws/` | `docs/archive/legacy-architecture/aws-deployment/` |
| Smart contracts | `packages/contracts/smart-contracts/` | — |
| Deprecated TypeScript ingestion duplicate | — | `docs/archive/legacy-architecture/data-ingestion-layer/` |
| Deprecated TypeScript lake duplicate | — | `docs/archive/legacy-architecture/data-lake-architecture/` |

These are physical repository paths, not aliases. Workflows, impact-graph
entries, source-linked documentation, ownership registries, and readiness
artifacts must reference the canonical paths above.

## Forbidden Root Items

No architecture folders may exist at the root.

Forbidden examples:

- `Backend Architecture/`
- `Data Ingestion Layer/`
- `Data Lake Architecture/`
- `AWS Deployment/`
- `ML Models/`
- `Smart Contracts/`
- `GDPR & SOC2/`
- `Agent Layer/`

Legacy material belongs in:

`docs/archive/`

## Enforcement

`scripts/validate_root_layout.py` runs in `make repo-doctor` and `make docs-check`.
It fails on any tracked root entry outside its allowlist, on the forbidden
directories above (plus the retired root `contracts/` and `frontend/`), on a
missing required entry point (`README.md`, `VERSION`, `CHANGELOG.md`,
`RELEASES.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `DEVELOPMENT.md`,
`SECURITY.md`, `LICENSE`, `Makefile`), and when `VERSION` differs from
`pyproject.toml`. Adding a root entry means editing that allowlist and this
document in the same change.

## Blueprint Adaptation

The repository truth reset blueprint named paths and tooling that this
repository covers with existing mechanisms. They are intentionally not
duplicated, because `AGENTS.md` makes `verification / disposition` the single
blocking PR authority and specialized workflows supplementary.

| Blueprint item | Where it lives here |
|---|---|
| `docs/source-of-truth/`, `docs/sdks/`, `docs/connectors/`, `docs/security/` | `docs/reference/source-of-truth/`, `docs/reference/sdks/`, `docs/reference/connectors/`, `docs/reference/security/` |
| `docs/releases/`, `docs/generated/` | `docs/operations/releases/`, `docs/_generated/` |
| Root `contracts/` | `packages/contracts/` (policy) and `packages/shared/contracts/` (registries) |
| `ci.yml`, `docs.yml`, `contracts.yml`, `sdk.yml`, `connectors.yml`, `release.yml`, `version-consistency.yml` | `repo-consistency.yml` (terminal authority) plus the existing specialized workflows; individual gates run through `make repo-doctor` |
| `turbo.json`, `pnpm docs:check` and similar scripts | `pnpm-workspace.yaml` and `make` targets (`docs-check`, `repo-doctor`, `verification-disposition`) |
| TypeScript validators under `scripts/**` | Python validators: `validate_root_layout.py`, `check_deprecated_language.py`, `bump_version.py --check`, `validate_sdk_parity.py`, `validate_contracts.py` |

A new blueprint-style workflow or script needs a gap that none of these cover,
not a matching filename.
