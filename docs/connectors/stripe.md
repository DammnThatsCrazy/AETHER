---
title: Stripe Connector
slug: stripe-connector
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: "0.1.0"
---

# Stripe Connector

## Overview

The Stripe connector integrates payment and subscription data from
Stripe into the Aether intelligence graph.

## Data Flow

```
Stripe account → webhook events + API polling
→ Stripe normalizer
→ canonical observation envelopes
→ /v1/batch ingestion
→ graph projection (value edges)
```

## Supported Events

| Event Category | Stripe Event | Aether Observation |
|---|---|---|
| Payments | payment_intent.succeeded | payment_completed |
| Subscriptions | customer.subscription.created | subscription_start |
| Refunds | charge.refunded | refund_processed |
| Disputes | charge.dispute.created | dispute_opened |

## Value Attribution

Stripe payment data flows through the canonical value architecture,
ensuring that monetary amounts are correctly attributed with explicit
basis and FX handling.

## Status

Planned. Not yet implemented.
