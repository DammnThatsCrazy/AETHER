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
under `config/`; tests under `tests/`; deployment under `deploy/`; and
generated evidence under `artifacts/`, `reports/`, or `release-evidence/` as
declared by the ownership registries. These are intentional support roots,
not alternate service homes.

## Canonical Directories

| Directory | Purpose |
|---|---|
| `apps/` | User-facing applications and marketing surfaces |
| `services/` | Backend runtime services |
| `packages/` | Shared packages, SDKs, clients, UI, contracts package |
| `services/backend/services/integrations/connectors/` | Provider connector runtime owned by the backend service |
| `contracts/` | Canonical event, graph, identity, journey, campaign, communication, value, and agent contracts |
| `docs/` | Human-readable documentation |
| `scripts/` | Repository validation, generation, release, docs, and contract scripts |
| `tests/` | Cross-package and system tests |
| `frontend/` | Frontend applications (Aether, Kyber, Demo, marketing) |
| `deploy/` | Deployment configurations |
| `config/` | Runtime configuration |

## Canonical service and deployment mapping

The active implementation trees that were previously placed at the repository
root now have one canonical home:

| Concern | Canonical path | Archived duplicate/orphan path |
|---|---|---|
| Python backend, ingestion, lake, graph, and intelligence | `services/backend/` | `docs/archive/legacy-architecture/backend/` |
| Journey compilation, persistence, attribution, and routes | `services/backend/services/measurement/` | `docs/archive/legacy-architecture/backend/services/journey-service/` (test fixture only) |
| ML training and serving | `services/ml/` | — |
| Internal broker-coupled agents | `services/agents/` | — |
| Compliance controls | `services/compliance/` | — |
| AWS deployment and Terraform | `deploy/aws/` | `docs/archive/legacy-architecture/aws-deployment/` |
| Smart contracts | `contracts/smart-contracts/` | — |
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
