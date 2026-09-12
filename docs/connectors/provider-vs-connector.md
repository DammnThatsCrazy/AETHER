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
- Registers webhooks
- Manages sync lifecycle and cursor state
- Validates provider payloads
- Normalizes payloads into canonical Aether contracts
- Projects normalized events into the graph pipeline

## SDK vs Connector

SDKs capture first-party observations from apps and sites that the tenant controls.

Connectors capture third-party data from external provider systems.

Both emit canonical event envelopes to the ingestion pipeline. Neither writes directly to the graph.
