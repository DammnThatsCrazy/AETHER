---
title: Billing Provider Interface
slug: operations/billing-provider-interface
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_EXTERNAL_BILLING_ENABLED
  - AETHER_STRIPE_BILLING_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Billing Provider Interface

`services/billing/providers/` defines the provider-safe `BillingProvider`
abstraction over the internal revops layer. The internal layer is unaffected
when external billing is off (the default).

## Providers

| Mode (`BILLING_PROVIDER_MODE`) | Class | Invoice export | Payment status |
| --- | --- | --- | --- |
| `internal_only` (default) | `InternalOnlyProvider` | internal_preview | externally_managed |
| `manual_invoice` | `ManualInvoiceProvider` | manual_artifact | externally_managed |
| `enterprise_contract` | `EnterpriseContractProvider` | approved_preview | externally_managed |
| `stripe` | `StripeBillingProvider` (import-safe stub) | provider_export | unknown until live |

`get_billing_provider()` resolves the mode from `settings.external_billing`.
`provider_health()` reports configured/healthy (Stripe is healthy only when
configured). `provider_status_summary()` powers the Kyber RevOps provider view.

## Interface

`create_customer`, `sync_customer`, `create/update/cancel_subscription`,
`create_invoice_preview`, `export_invoice`, `sync_payment_status`,
`record_usage`, `create_usage_record`, `map_product`, `map_price`,
`handle_webhook`. Manual/enterprise providers export offline artifacts; Stripe
mutations raise `ProviderDisabledError` until live wiring is enabled.

## Guarantees

No secrets in config/responses/logs. Webhooks are HMAC-verified + idempotent.
See [External Billing Integration](EXTERNAL-BILLING-INTEGRATION.md),
[Stripe Readiness](STRIPE-READINESS.md), [Payment Operations](PAYMENT-OPERATIONS.md).
