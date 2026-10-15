---
title: "Cursors and Retries"
slug: connectors/cursors-and-retries
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Cursors and Retries

## Cursor State

Each sync maintains a cursor that tracks the last successfully processed position. Cursors are persisted per-tenant, per-connector.

## Retry Behavior

Failed sync operations retry with exponential backoff. Retry state is tracked alongside cursor state.

## Idempotency

All sync operations are designed to be idempotent. Re-processing the same cursor range produces the same result.
