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

The repository contains a legacy `StripeConnector` under
`services/api/connectors/integrations/connectors/adapters.py`. It accepts
Stripe webhook events and verifies signatures through the legacy webhook
integration path. It is not a native UPR provider plugin and does not currently
poll Stripe for orders, transactions, or subscriptions.

## Data Flow

```
Stripe webhook → legacy connector parser
→ legacy normalized event and connector persistence path
```

## Supported Events

| Event Category | Stripe Event | Aether Observation |
|---|---|---|
The legacy parser wraps the Stripe event type as `stripe.<type>` and retains
limited object metadata. It does not implement the richer per-event mapping
shown in older drafts, settlement reconciliation, or canonical payment
authority.

## Value Attribution

The parser is not evidence that payment data has been reconciled into the
canonical Value architecture. Payment truth, settlement, refunds, payouts,
fees, and FX treatment must use the existing payment and ledger authorities.

## Status

Implemented as a legacy webhook-only connector (`supports_webhook=True`,
`supports_pull=False`). Native UPR migration, provider-backed tests, downstream
payment reconciliation, and graph projection remain incomplete. A registered
legacy connector is not a live-certification or production-readiness claim.
