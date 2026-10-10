---
title: "Sync Jobs"
slug: connectors/sync-jobs
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Sync Jobs

## Historical Backfill

Connectors that support historical backfill perform an initial sync of historical data from the provider.

## Incremental Sync

Incremental sync uses cursors to track the last-synced position and fetch only new or updated records.

## Scheduled Sync

Some connectors run on a schedule in addition to webhook-driven sync.
