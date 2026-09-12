---
title: Observability
slug: ops-observability
section: operations
visibility: I
audience: [ops, architect]
status: experimental
since_version: "0.1.0"
---

# Observability

## Overview

Aether's observability stack covers logging, metrics, and tracing across
the platform runtime.

## Telemetry Contracts

Telemetry emission points are governed by contracts defined in
`config/telemetry_contracts.json`. The telemetry validation script
ensures that all declared meters are properly instrumented.

## Metrics

### Ingestion Metrics

- `aether.ingestion.batch_size` — events per batch
- `aether.ingestion.latency_ms` — ingestion endpoint latency
- `aether.ingestion.error_rate` — ingestion failure rate

### Graph Metrics

- `aether.graph.projection_lag_ms` — time from ingestion to projection
- `aether.graph.entity_count` — total entities per tenant
- `aether.graph.edge_count` — total edges per tenant

### SDK Health Metrics

- `aether.sdk.heartbeat_age_s` — time since last SDK heartbeat
- `aether.sdk.queue_depth` — pending events in SDK queue

## Logging

Structured JSON logging across all services. Log levels follow standard
severity (DEBUG, INFO, WARN, ERROR).

## Tracing

Distributed tracing with correlation IDs propagated through the full
request lifecycle from SDK to graph projection.

## Current State

Telemetry contracts are defined and validated. Full observability
instrumentation is in progress.
