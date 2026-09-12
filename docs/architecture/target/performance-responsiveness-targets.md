---
title: Performance and Responsiveness Targets
slug: performance-responsiveness-targets
section: architecture
visibility: I
audience: [architect, ops]
status: experimental
since_version: "0.1.0"
---

# Performance and Responsiveness Targets

## Target State

Defined performance budgets and responsiveness targets for all Aether
runtime surfaces, ensuring predictable behavior under production load.

## Ingestion Targets

| Metric | Target | Measurement |
|---|---|---|
| `/v1/batch` p99 latency | < 200ms | API gateway to acknowledgment |
| Batch throughput | 10k events/sec/tenant | Sustained ingestion rate |
| Bronze normalization lag | < 5s | Ingestion to Bronze store |
| Silver projection lag | < 30s | Bronze to Silver projection |

## Query Targets

| Metric | Target | Measurement |
|---|---|---|
| Entity lookup p99 | < 100ms | API to response |
| 360 surface render p99 | < 500ms | Query to full projection |
| Graph traversal p99 | < 1s | For depth ≤ 3 |

## Frontend Targets

| Metric | Target | Measurement |
|---|---|---|
| Initial page load | < 2s | Time to interactive |
| Navigation transition | < 300ms | Route change to render |
| Data refresh | < 1s | Stale data to fresh render |

## Connector Targets

| Metric | Target | Measurement |
|---|---|---|
| Webhook processing p99 | < 500ms | Receipt to acknowledgment |
| Sync job throughput | 1k records/sec | Per connector instance |

## Current State

Performance targets are defined but not yet systematically measured.
Instrumentation is planned as part of the observability buildout.
