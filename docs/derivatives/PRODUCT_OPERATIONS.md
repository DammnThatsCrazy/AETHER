---
title: Derivatives Product Operations
slug: derivatives/product-operations
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "8.11.0"
---

# Derivatives Product Operations

PR4 exposes Derivatives Intelligence through tenant-facing Aether APIs and Kyber operator APIs while keeping Aether observational.

## Tenant product surfaces

Tenant routes under `/v1/derivatives/*` provide overview, accounts, positions, position detail, behavior/Profile360 payloads, realtime topic catalogs, alert rule catalogs, usage metering, and evidence export. Backend permission checks are mandatory; frontend navigation is not the entitlement boundary.

## Kyber operations

Kyber routes under `/v1/admin/kyber/derivatives/*` expose connector fleet health, data-quality state, reconciliation variances, graph quality, intelligence quality, and bounded operator actions. Operator actions are tenant-scoped, audited, idempotent, and cannot submit trades, transfer collateral, withdraw funds, or mutate venue accounts.

## Realtime and alerts

Realtime topics are durable-source-backed catalog entries for position changes, liquidations, funding settlement, stale connectors, reconciliation variances, and mapping reviews. Alert rules require evidence links and route back to relevant account, position, graph, or reconciliation detail.

## Packaging and usage

PR4 meters connected venues, connected accounts, ingested records, active positions, retention, realtime subscriptions, backfills, graph queries, Noesis queries, exports, and custom connector usage. Usage values are fixed-precision decimal strings.
