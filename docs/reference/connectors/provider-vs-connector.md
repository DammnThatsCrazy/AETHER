---
title: "Provider vs Connector"
slug: connectors/provider-vs-connector
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Provider vs Connector

## Provider

A provider is an external system that owns source data.

Examples: Shopify, Stripe, Mailchimp, HubSpot, Google Analytics, Salesforce.

Aether does not own, modify, or control provider data at rest.

## Connector

A connector is an Aether-managed integration that:

- Authenticates with the provider
- Registers and verifies webhooks when supported
- Manages sync lifecycle and cursor state
- Validates provider payloads
- Normalizes payloads into canonical Aether contracts
- Supplies source evidence to an authorized downstream projector when that capability has one

## SDK vs Connector

SDKs capture first-party observations from apps and sites that the tenant controls through the SDK ingestion gateway. UPR connectors acquire third-party provider data through their own credential, account, raw-store, and webhook paths, then publish consent-admitted events through the existing Bronze/outbox seam. Legacy connectors and measurement or communications systems retain their owning paths while migration proceeds.

The UPR provider consumer guard currently defers provider events from SDK-oriented Silver normalization, analytics recording, and real-time identity resolution. This repository does not yet have a commerce provider projector that turns these events into graph mutations. Any graph write must come from an authorized domain projector through the graph mutation gateway; an SDK or provider connector does not write graph state directly.

## See Also

- [Connector Subsystem Registry](./subsystem-registry.md)
- [Provider Manifests](./provider-manifests.md)
- [Provider Normalization](./provider-normalization.md)
