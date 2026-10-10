---
title: Connector Runtime Productization
slug: connector-runtime-productization
section: architecture
visibility: I
audience: [architect]
status: experimental
since_version: "0.1.0"
---

# Connector Runtime Productization

## Current foundation

The repository already has a Universal Provider Runtime (UPR) in
`services/backend/services/provider_runtime/` and plugin contracts in
`services/backend/shared/integration_contracts/`. The runtime registers
provider capabilities, validates manifests, manages connections, persists raw
provider records before normalization, runs pull and webhook adapters, bridges
events into Bronze, and exposes health and offline certification. The legacy
`BaseConnector` system remains reachable through a UPR compatibility wrapper.

Shopify has a native `orders_read` plugin and a legacy connector. Stripe has a
legacy ingestion connector and separate payment-rail and billing integrations;
these are distinct capabilities. WooCommerce, Etsy, Amazon, eBay, Walmart, and
TikTok have native provider modules. Their presence does not establish a
live connection, production certification, or complete commerce coverage.

Other repository paths include communications, measurement, derivatives,
SDK, import, webhook, and outbound action capabilities. They have different
authorities and should be converged according to declared capability, not
forced into a single pull or graph-write behavior.

## Target state

Extend the existing UPR with stream-level contracts, source-revision-aware raw
and canonical evidence, explicit source authority and reconciliation,
tenant-safe graph mutation requests, honest readiness, and durable per-tenant
cutover. Provider modules own external API and webhook details. Domain packs
own canonical vocabulary and policy. Existing identity, credential, ingestion,
rights, graph, projection, and managed-integration authorities retain their
responsibilities.

The [full implementation blueprint](../blueprints/universal-connector-runtime/README.md)
defines the current-to-target map, canonical ID and event contracts, Shopify
reference slice, cross-provider expansion, migration, certification, and
acceptance gates. This branch implements stream and raw-revision foundations,
source-object identity primitives, tenant route records, a durable event
handoff, and an opt-in Shopify GraphQL orders reader. The target state remains
in progress: no tenant cutover, live certification, complete graph writer
fence, or cross-provider convergence follows from those foundations alone.

## Dependencies

- [Universal Provider Runtime](../UNIVERSAL-PROVIDER-RUNTIME.md) and
  [ADR-009](../decisions/ADR-009-universal-provider-runtime.md)
- [Provider migration](../../operations/PROVIDER-MIGRATION.md) and
  [provider certification](../../reference/PROVIDER-CERTIFICATION.md)
- [SDK and universal ingestion alignment](../blueprints/sdk-universal-ingestion-alignment.md)
- [Connector taxonomy](../../reference/source-of-truth/CONNECTOR_TAXONOMY.md)
