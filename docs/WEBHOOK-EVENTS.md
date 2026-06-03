---
title: Webhook Events
slug: api/webhook-events
section: api
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Webhook Events

Two webhook directions exist: **inbound** (providers/systems → Aether, for
ingestion) and **outbound** (Aether → your tools, via action dispatch).

## Inbound (ingestion)

Connectors receive HMAC-signed webhooks and normalize them — see
[Webhook Ingestion](WEBHOOK-INGESTION.md) and [Connectors](CONNECTORS.md).
Signature: HMAC-SHA256 over `"{timestamp}." + body`, headers `X-Aether-Timestamp`
/ `X-Aether-Signature`, ±5-minute tolerance.

## Outbound (action dispatch)

Approved decisions dispatch to integrations (Slack/webhook/CRM/…) with signed
payloads + delivery receipts — see [Action Dispatch](ACTION-DISPATCH.md) and
[Integration Actions](INTEGRATION-ACTIONS.md). Outbound destinations are
SSRF-validated and idempotent.

## Billing webhooks

The Stripe provider validates webhook signatures + idempotency before updating
payment status — see [External Billing Integration](EXTERNAL-BILLING-INTEGRATION.md).

No secrets are logged for any webhook. See [Event Schema Reference](EVENT-SCHEMA-REFERENCE.md).
