---
title: "Runtime Architecture"
slug: architecture/current/runtime-architecture
section: architecture
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Runtime Architecture

## Backend

Python/FastAPI backend handling ingestion, identity resolution, graph mutations, orchestration, and API surfaces.

## Surfaces (Frontend)

All frontend surfaces are productized graph views — governed projections
of the tenant-scoped intelligence graph rendered for a specific purpose.

- **Aether Console** — Tenant-facing surface (Profile360, Campaign360, Journey360)
- **Kyber Operator Console** — Operational graph view for real-time decisioning
- **Demo App** — Synthetic data demonstration surface

## Data Plane

- PostgreSQL — Primary relational store
- ClickHouse — Analytics and time-series
- Graph store — Entity relationships and projections

## Current State

Runtime architecture is functional for pre-production use. Production hardening, observability, and scale testing are ongoing.
