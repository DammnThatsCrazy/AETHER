---
title: "ADR-004: Backend Architecture — Single FastAPI Monolith with Router Registry"
status: Accepted — Decomposition Planned
date: "2026-05-29"
---

# ADR-004: Backend Architecture — Single FastAPI Monolith with Router Registry

**Status:** Accepted — Decomposition Planned  
**Date:** 2026-05-29

## Context

The Aether backend currently mounts **65 service routers** from a single
`main.py` entry point (`Backend Architecture/aether-backend/main.py`). All
routers share:
- One Python process (one Uvicorn/Gunicorn instance)
- One dependency set (`pyproject.toml [backend]`)
- One PostgreSQL connection pool
- One Redis/DynamoDB cache client
- One Neptune gremlin client

This is a monolith — not a microservice architecture — despite the internal
service boundary organisation under `services/`.

The monolith was chosen for speed of initial development. A single Dockerfile,
single deploy unit, and shared in-process function calls are dramatically
simpler to operate at early stage than a distributed service mesh.

## Decision

**Current state (Accepted):** Maintain the single-process monolith. All 65
routers are mounted in `main.py`. New domains add a router file under
`services/<domain>/` and register it in `main.py`.

**Target state (Decomposition Planned, v9.x):** Migrate toward a plugin
registry pattern where `main.py` discovers and mounts routers from a data
structure rather than 65 explicit `include_router()` calls. This eliminates
merge conflicts on `main.py` when two PRs both add new domains.

Long-term (v10.x): Evaluate extracting high-throughput or high-isolation
domains (ingestion, ML serving, commerce) into separate Fargate tasks with
their own Dockerfiles, while retaining a shared core for identity, analytics,
and admin.

## Exit Criteria for Current Architecture

Decompose when any of the following are true:
- Two concurrent PRs conflict on `main.py` more than once per sprint.
- A single domain requires a dependency incompatible with the shared set.
- Deployment of one domain requires redeploying all 65 — and that causes
  measurable downtime.
- Team grows beyond 4 active backend contributors.

## Consequences

**Current (monolith):**
- (+) Single deploy unit, single Dockerfile, simple local dev.
- (+) In-process calls between domains — no network latency or serialisation.
- (-) `main.py` is a merge conflict magnet (27 commits in history).
- (-) All domains scale together — can't scale ML serving independently.
- (-) One crashing domain can bring down all 65.

**Target (plugin registry):**
- (+) No merge conflicts on `main.py` for new domain additions.
- (+) Machine-readable router manifest enables contract validation.
- (-) Discovery magic makes import tracing harder.
