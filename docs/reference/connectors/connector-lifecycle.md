---
title: "Connector Lifecycle"
slug: connectors/connector-lifecycle
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Connector Lifecycle

## Phases

1. **Registration** — Connector is registered in the connector registry
2. **Authorization** — Provider OAuth or credential setup
3. **Configuration** — Webhook registration, sync settings, field mapping
4. **Initial Sync** — Historical backfill where supported
5. **Incremental Sync** — Ongoing sync via webhooks and/or scheduled pulls
6. **Normalization** — Provider payloads translated to canonical contracts
7. **Projection** — Normalized events projected into the graph pipeline
8. **Monitoring** — Health, freshness, error tracking

## Cursor State

Connectors maintain cursor state for incremental sync. Cursors are persisted per-tenant, per-connector, per-sync-type.

## Retry and Idempotency

Connector sync operations are idempotent. Failed syncs are retried with exponential backoff. Duplicate events are deduplicated by the ingestion pipeline.

## Failure Handling

- Transient failures trigger retry
- Persistent failures surface in tenant health
- Credential expiration triggers re-authorization flow
