---
title: External Billing Integration
slug: operations/external-billing-integration
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_EXTERNAL_BILLING_ENABLED
  - AETHER_STRIPE_BILLING_ENABLED
  - KYBER_BILLING_PROVIDER_SYNC_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# External Billing Integration

Provider-safe external billing readiness layered on top of the existing internal
billing/revops layer. The internal layer is unaffected when external billing is
off — which is the default.

## Feature flags & config

| Flag / env | Default | Effect |
| --- | --- | --- |
| `AETHER_EXTERNAL_BILLING_ENABLED` | `false` | Master switch for the provider interface |
| `AETHER_STRIPE_BILLING_ENABLED` | `false` | Activates the Stripe provider |
| `KYBER_BILLING_PROVIDER_SYNC_ENABLED` | `false` | Exposes provider-sync status in RevOps |
| `BILLING_PROVIDER_MODE` | `internal_only` | `internal_only` / `stripe` / `manual_invoice` / `enterprise_contract` |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | — | Required only when Stripe is enabled |
| `STRIPE_PRODUCT_MAPPING_JSON`, `STRIPE_PRICE_MAPPING_JSON` | — | Optional product/price maps |

None of these env vars are required for local dev unless provider sync is enabled.

## Provider interface

`BillingProvider` (`services/billing/providers/`) defines `create_customer`,
`sync_customer`, `create_subscription`, `update_subscription`,
`cancel_subscription`, `create_invoice_preview`, `export_invoice`,
`sync_payment_status`, `record_usage`, `create_usage_record`, `map_product`,
`map_price`, and `handle_webhook`.

- `InternalOnlyProvider` is the default — no external processor; payment status is
  reported as `externally_managed`.
- `StripeBillingProvider` is an **import-safe stub**: it never imports the Stripe
  SDK at module load, performs no network calls in local/test, and activates only
  behind `AETHER_STRIPE_BILLING_ENABLED` with a configured secret. External
  mutating operations raise `ProviderDisabledError` until wired in deployment.

## Webhooks

Webhook handling validates the Stripe HMAC signature, is idempotent per event id,
maps known events to a payment status, and **never logs secrets**. Disabled
providers do not process webhooks.

## RevOps & tenant visibility

Operators see provider sync status, mode, invoice-export status, payment status,
mapping status, unmapped usage dimensions, and failed syncs at
`GET /v1/admin/kyber/revops/provider-status` and `.../product-mappings`. Tenants
see only current plan, usage, and (when a customer-facing provider is enabled)
payment status at `GET /v1/billing/payment-status`. Revenue leakage, internal
overage strategy, and provider debug details are never shown to tenants.

See [Billing & Revenue Operations](BILLING-REVENUE-OPS.md) and
[Stripe Billing](STRIPE-BILLING.md).
