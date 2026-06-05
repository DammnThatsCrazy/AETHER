---
title: Stripe Connector
slug: operations/stripe-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Stripe Connector (ingestion)

Ingests Stripe payment, invoice, and subscription events as graph signals
(`stripe.invoice.paid`, `stripe.customer.created`, `stripe.charge.succeeded`).

- **Category**: billing · **Webhook**: yes · **Pull**: no · **Premium**: no
- **Auth**: Stripe webhook signing secret (vault-stored).
- This is the **ingestion** connector (graph enrichment) — distinct from the
  external **billing provider** integration (see
  [External Billing Integration](EXTERNAL-BILLING-INTEGRATION.md)).

## Enable

`PUT /v1/integrations/connectors/stripe` (`enabled: true`) → `/test`. Webhook
payloads are HMAC-verified. Disabled by default; live API is a credential-gated
TODO. See [Connectors](CONNECTORS.md).
