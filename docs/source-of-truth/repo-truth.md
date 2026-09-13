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

The root directory contains only canonical entry points and repository configuration.

Architecture, design, SDK, connector, release, and operational documents belong under `docs/`.

## Canonical Directories

| Directory | Purpose |
|---|---|
| `apps/` | User-facing applications and marketing surfaces |
| `services/` | Backend runtime services |
| `packages/` | Shared packages, SDKs, clients, UI, contracts package |
| `connectors/` | Provider connector runtime |
| `contracts/` | Canonical event, graph, identity, journey, campaign, communication, value, and agent contracts |
| `docs/` | Human-readable documentation |
| `scripts/` | Repository validation, generation, release, docs, and contract scripts |
| `tests/` | Cross-package and system tests |
| `frontend/` | Frontend applications (Aether, Kyber, Demo, marketing) |
| `deploy/` | Deployment configurations |
| `config/` | Runtime configuration |

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
