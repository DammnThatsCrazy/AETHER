---
title: Contract Model
slug: product-contract-model
section: concepts
visibility: P
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Contract Model

Contracts govern the shape, validation, and evolution of data
flowing through Aether. Every SDK payload, API response, and
connector integration is governed by a versioned contract.

## Contract Types

| Type | Scope |
|---|---|
| Ingestion contract | SDK → backend (`/v1/batch`) |
| API contract | Backend → consumer (REST responses) |
| Connector contract | Aether ↔ external system |
| Projection contract | Graph → product surface |

## Core Invariant

Contracts are versioned independently of the platform version.
A contract change requires a compatibility assessment before
merge.

## See Also

- `docs/sdks/ingestion-contract.md` — SDK ingestion contract
- `docs/product/graph-model.md` — Graph model
- `docs/product/tenant-model.md` — Tenant model
