---
title: Stripe Integration Guide
slug: tutorials/stripe-integration
section: developer
visibility: P
audience: [dev-junior, dev-senior, ops]
status: stable
since_version: 9.1.0
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
---

# Stripe Integration Guide

The Stripe connector ingests payment, invoice, and subscription events from
your Stripe account as graph signals, so revenue events that happen at the
payment layer — not just at checkout in your app — flow into the same
profile and journey graph as everything else.

This is the **ingestion** connector (graph enrichment). If you're looking
for how Aether charges *your* tenant via Stripe, see the billing
documentation instead — that's a separate integration.

## What it captures

- **Invoices** (`stripe.invoice.paid`) — successful invoice payments.
- **Customers** (`stripe.customer.created`) — new Stripe customer records.
- **Charges** (`stripe.charge.succeeded`) — successful one-off charges.

The Stripe connector is webhook-only (no polling/pull path) — Stripe's own
webhook system is the source of truth for payment events, so Aether
subscribes to it rather than re-deriving state via the API.

## Enable the connector

1. In **Settings → Integrations → Connectors**, enable Stripe:

   ```
   PUT /v1/integrations/connectors/stripe
   { "enabled": true }
   ```

2. Add your Stripe webhook signing secret — stored in the credential vault,
   never logged.

3. In the Stripe Dashboard, point a webhook endpoint at Aether's connector
   URL and subscribe to at least `invoice.paid`, `customer.created`, and
   `charge.succeeded`.

4. Test the connection:

   ```
   POST /v1/integrations/connectors/stripe/test
   ```

## Webhook verification

Stripe signs webhooks with its standard `t=…,v1=…` `Stripe-Signature`
header format. Aether verifies every inbound Stripe webhook against your
stored signing secret before normalizing it — an unverified payload never
reaches the event pipeline.

## Payment event tracking

Aether normalizes Stripe's payload shape into the same canonical event
vocabulary your SDKs use:

| Stripe webhook event | Canonical Aether signal |
|---|---|
| `invoice.paid` | `payment_completed` |
| `charge.succeeded` | `payment_completed` |
| `charge.failed` | `payment_failed` |
| `customer.created` | `identify` / customer profile update |

## Revenue attribution

Once a Stripe payment lands in the graph, it participates in the same
identity resolution and attribution machinery as any other signal — a
payment can be linked back to the session, campaign, and journey that led
to it via the `economic`, `payment`, `campaign`, and `attribution`
[lenses](../concepts/lenses.md), giving you revenue attribution at the
payment layer without a separate reconciliation pipeline.

## Next steps

- [Shopify integration](shopify-integration.md) — order-level e-commerce
  data alongside payment-level Stripe data.
- [Webhooks](../api/webhooks.md) — the general webhook signing and
  verification model this connector's inbound side follows.
