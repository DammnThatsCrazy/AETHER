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

## Target State

The connector runtime provides a standardized framework for building,
deploying, and operating Aether-managed integrations to external
provider systems.

## Planned Capabilities

### Connector Lifecycle

Standardized lifecycle management: configure → authenticate → sync →
monitor → deactivate.

### Normalization Framework

Every connector includes a normalizer that translates provider-specific
payloads into canonical Aether observation envelopes.

### Sync Engine

- Cursor-based incremental sync with durable checkpoints.
- Webhook-based real-time sync where providers support it.
- Retry and error handling with exponential backoff.

### Health and Diagnostics

- Connector health metrics surfaced in Kyber.
- Sync job monitoring with failure alerting.
- Credential expiry tracking and renewal prompts.

## Connector Inventory (Target)

| Connector | Provider | Status |
|---|---|---|
| Stripe | Stripe | Planned |
| Shopify | Shopify | Planned |
| HubSpot | HubSpot | Planned |
| Email (SMTP/SES) | Various | Planned |
| Custom | User-defined | Framework only |

## Dependencies

- Provider vs. connector boundary (see `docs/connectors/provider-vs-connector.md`)
- Connector authentication framework
- Graph projection pipeline
