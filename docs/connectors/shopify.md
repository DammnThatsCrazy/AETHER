---
title: Shopify Connector
slug: shopify-connector
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: "0.1.0"
---

# Shopify Connector

## Overview

The Shopify connector integrates Shopify store data into the Aether
intelligence graph, syncing customer, order, and product interaction
data through Shopify's API and webhooks.

## Data Flow

```
Shopify store → webhook events + API polling
→ Shopify normalizer
→ canonical observation envelopes
→ /v1/batch ingestion
→ graph projection
```

## Supported Events

| Event Category | Shopify Event | Aether Observation |
|---|---|---|
| Orders | order/created, order/updated | purchase, order_update |
| Customers | customer/created, customer/updated | entity_update |
| Products | product/updated | catalog_update |
| Carts | cart/updated | cart_activity |

## Configuration

- Shopify API credentials (API key, secret, access token)
- Webhook subscription management
- Sync cursor for incremental polling

## Status

Planned. Not yet implemented.
