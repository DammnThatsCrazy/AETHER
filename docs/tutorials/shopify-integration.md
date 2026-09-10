---
title: Shopify Integration Guide
slug: tutorials/shopify-integration
section: tutorials
visibility: P
audience: [dev-junior, dev-senior, ops]
status: stable
since_version: "9.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
---

# Shopify Integration Guide

The Shopify connector ingests orders, customers, and checkout events from
your store as graph signals, so revenue and customer activity that happens
outside your app still lands in the same profile and journey graph as your
SDK-tracked events.

## What it captures

- **Orders** (`shopify.order`) — order creation and updates, including line
  items and totals.
- **Customers** (`shopify.customer`) — customer records, useful for
  identity resolution against SDK-tracked anonymous sessions.
- **Checkout** (`shopify.checkout`) — checkout started/updated events, for
  funnel and abandonment analysis.

Both **webhook** delivery (real-time, as Shopify events happen) and **pull**
sync (the Admin API, cursor-paginated with `page_info`) are supported —
Shopify is one of the few connectors with both paths production-ready.

## Enable the connector

1. In **Settings → Integrations → Connectors**, enable Shopify:

   ```
   PUT /v1/integrations/connectors/shopify
   { "enabled": true }
   ```

2. Provide your Shopify app API secret and webhook secret — both are
   stored in Aether's credential vault, never logged, and never returned in
   plaintext by any read endpoint.

3. Test the connection:

   ```
   POST /v1/integrations/connectors/shopify/test
   ```

4. Optionally trigger an initial backfill sync:

   ```
   POST /v1/integrations/connectors/shopify/sync
   ```

## Webhook verification

Shopify signs webhook payloads with Base64-encoded HMAC-SHA256 in the
`X-Shopify-Hmac-Sha256` header. Aether verifies every inbound Shopify
webhook against your stored app secret before it's normalized — an
unverified payload is rejected and never reaches the event pipeline.

## Event mapping

Aether normalizes Shopify's payload shape into the same canonical event
vocabulary your SDKs use, rather than storing raw Shopify JSON as a second,
parallel schema:

| Shopify webhook topic | Canonical Aether signal |
|---|---|
| `orders/create`, `orders/updated` | `order_completed` (or update variant) |
| `checkouts/create`, `checkouts/update` | `checkout_started` |
| `customers/create`, `customers/update` | `identify` / customer profile update |

## Order tracking and attribution

Because Shopify orders land in the same graph as SDK-observed sessions,
[identity resolution](../concepts/profiles.md#identity-resolution) can link
a Shopify order back to the anonymous session and campaign touchpoints that
led to it — giving you revenue attribution without needing Shopify's own
analytics or a separate reconciliation step. The `campaign` and
`attribution` [lenses](../concepts/lenses.md) surface that attribution
weight once the order is in the graph.

## Next steps

- [Stripe integration](stripe-integration.md) — payment-level revenue data
  alongside order-level Shopify data.
- [Sources](../concepts/sources.md) — how connectors relate to SDK sources.
