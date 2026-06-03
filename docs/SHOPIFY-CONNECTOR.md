---
title: Shopify Connector
slug: operations/shopify-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Shopify Connector

Ingests Shopify orders, customers, and checkout events
(`shopify.order`, `shopify.customer`, `shopify.checkout`).

- **Category**: commerce · **Webhook**: yes · **Pull**: yes · **Premium**: no
- **Auth**: Shopify app API secret / webhook HMAC secret (vault-stored).
- **Webhooks**: register Shopify topics to the ingest endpoint; payloads are
  HMAC-verified.
- **Pull**: the Admin API order/customer sync is a credential-gated TODO.

## Enable

`PUT /v1/integrations/connectors/shopify` (`enabled: true`) → `/test` → `/sync`.
Disabled by default. See [Connectors](CONNECTORS.md) and
[Webhook Ingestion](WEBHOOK-INGESTION.md).
