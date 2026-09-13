---
title: "ADR-002: Monorepo Directory Naming Convention"
slug: decisions/adr-002-monorepo-directory-naming
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
toc_depth: 2
---

# ADR-002: Monorepo Directory Naming Convention

**Status:** Accepted — Migration Complete | **Date:** 2026-09-13

## Context

The pre-1.0 repository used eight top-level directories with human-readable
names containing spaces and special characters. That layout caused repeated
quoting bugs in CI and local tooling:

```
AWS Deployment/aether-aws/
Agent Layer/
Backend Architecture/aether-backend/
Data Ingestion Layer/
Data Lake Architecture/
GDPR & SOC2/aether-compliance/
ML Models/aether-ml/
Smart Contracts/
```

PR #627 documented the migration but did not move the implementation tree. The
follow-up remediation completed that move: active code is now under `services/`,
`deploy/`, and `contracts/`; only historical material remains under
`docs/archive/legacy-architecture/`. The names below are historical labels,
not live paths.

The `apps/`, `packages/`, `scripts/`, `tests/`, `docs/`, `security/`,
`deploy/`, `lambda/`, and `cicd/` directories use the correct, shell-safe
kebab-case convention. These support and evidence roots remain intentionally
separate from deployable services; the active service boundaries are documented
in [`repo-migration.md`](../source-of-truth/repo-migration.md).

## Decision

**Current state (Accepted):** Active implementation directories use shell-safe
paths. `BACKEND_DIR`, `ML_DIR`, `AGENT_DIR`, and `TF_DIR` point to
`services/backend`, `services/ml`, `services/agents`, and `deploy/aws/terraform`.
CI still quotes variable expansions at command boundaries.

**Completed migration map:**

| Historical root-era path | Canonical or archive path |
|---------|--------|
| `AWS Deployment/aether-aws/` | `deploy/aws/` |
| `Agent Layer/` | `services/agents/` |
| `Backend Architecture/aether-backend/` | `services/backend/` |
| `Data Ingestion Layer/` | `docs/archive/legacy-architecture/data-ingestion-layer/` |
| `Data Lake Architecture/` | `docs/archive/legacy-architecture/data-lake-architecture/` |
| `GDPR & SOC2/aether-compliance/` | `services/compliance/` |
| `ML Models/aether-ml/` | `services/ml/` |
| `Smart Contracts/` | `contracts/smart-contracts/` |

The migration was atomic across the root tree, import references, CI YAML,
Makefile paths, test paths, source-linked docs, registries, and readiness
artifacts. The ownership and impact-graph gates now prevent a root-era path
from returning without an explicit review.

## Consequences

**Current state:** Active paths are shell-safe; archived paths are intentionally
kept under `docs/` and are not runtime inputs.

**Result:** The root tree now matches the repository-truth blueprint. External
tooling that hardcoded the old paths must migrate to the canonical map above.
