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

## Frontend

- Aether Console — Tenant-facing application
- Kyber Operator Console — Operator-facing application
- Demo App — Synthetic data demonstration

## Data Plane

- PostgreSQL — Primary relational store
- ClickHouse — Analytics and time-series
- Graph store — Entity relationships and projections

## Current State

Runtime architecture is functional for pre-production use. Production hardening, observability, and scale testing are ongoing.
