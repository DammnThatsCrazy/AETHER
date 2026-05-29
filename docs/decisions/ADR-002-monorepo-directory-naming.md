---
title: "ADR-002: Monorepo Directory Naming Convention"
status: Accepted — Migration Pending
date: "2026-05-29"
---

# ADR-002: Monorepo Directory Naming Convention

**Status:** Accepted — Migration Pending  
**Date:** 2026-05-29

## Context

Eight top-level directories use human-readable names with spaces and special
characters:

```
AWS Deployment/
Agent Layer/
Backend Architecture/
Data Ingestion Layer/
Data Lake Architecture/
GDPR & SOC2/
ML Models/
Smart Contracts/
```

These names predate the current tooling conventions. They require shell quoting
in every script, CI YAML, Makefile, and Python `Path()` call. Unquoted
references are a recurring source of CI failures (e.g., the `Check env vars
documented` step in `repo-health.yml` used `"$BACKEND_DIR/..."` without quotes
around the variable expansion in some historic versions).

The `apps/`, `packages/`, `scripts/`, `tests/`, `docs/`, `security/`,
`deploy/`, `lambda/`, and `cicd/` directories use the correct, shell-safe
kebab-case convention.

## Decision

**Current state (Accepted):** Directories with spaces are kept as-is. All CI
scripts and Makefiles must quote references using `"${VAR}"` syntax. The
`BACKEND_DIR`, `ML_DIR`, and `AGENT_DIR` env vars in CI are defined with
quotes and used with `"${BACKEND_DIR}"` everywhere.

**Target state (Migration Pending):** In v9.0.0, rename all space-containing
directories to kebab-case equivalents:

| Current | Target |
|---------|--------|
| `AWS Deployment/` | `infra/` |
| `Agent Layer/` | `agent/` |
| `Backend Architecture/aether-backend/` | `backend/` |
| `Data Ingestion Layer/` | `ingestion/` |
| `Data Lake Architecture/` | `datalake/` |
| `GDPR & SOC2/` | `compliance/` |
| `ML Models/aether-ml/` | `ml/` |
| `Smart Contracts/` | `contracts/` |

The migration must be atomic: a single PR updates all directory names,
all import references, all CI YAML env vars, all Makefile paths, all
`pyproject.toml` test paths, and all `docs/` source_files references
in one commit. A migration script should be written and reviewed before
execution.

## Consequences

**Current state:** Low migration risk but constant quoting friction and
periodic CI bugs from missed quotes.

**Target state:** Eliminates all quoting issues. Reduces `BACKEND_DIR` env var
indirection in CI — paths can be used inline. Breaking change for any external
tooling that has hardcoded the old paths.
