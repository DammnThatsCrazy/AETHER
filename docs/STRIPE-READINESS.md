---
title: Stripe Readiness
slug: operations/stripe-readiness
section: operations
visibility: I
audience: [ops, architect, exec]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_STRIPE_BILLING_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Stripe Readiness

Steps to take the Stripe provider from import-safe stub to live. All gated by
`AETHER_STRIPE_BILLING_ENABLED` (off by default); no Stripe keys are required
for local dev.

## Activation checklist

- [ ] Create the Stripe account; complete business + tax settings.
- [ ] Set `AETHER_EXTERNAL_BILLING_ENABLED=true`, `AETHER_STRIPE_BILLING_ENABLED=true`,
      `BILLING_PROVIDER_MODE=stripe`.
- [ ] Provide `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` via the secret
      manager (never in `.env` in prod).
- [ ] Map products/prices: `STRIPE_PRODUCT_MAPPING_JSON`, `STRIPE_PRICE_MAPPING_JSON`
      (per package/plan/usage dimension) — verify via Kyber RevOps
      `product-mappings` (no unmapped dimensions).
- [ ] Configure the Stripe webhook endpoint; signatures are HMAC-verified +
      idempotent (`StripeBillingProvider.handle_webhook`).
- [ ] Wire the live SDK calls (currently `ProviderDisabledError` placeholders) —
      `create_customer`, subscriptions, invoice export, usage records.
- [ ] Verify payment-status sync + tenant-facing payment status.

## Notes

Do not hardcode prices — use approved mapping config. No secrets in logs/UI.
Bank/payout setup is an operational task — see [Payment Operations](PAYMENT-OPERATIONS.md)
and [Billing Provider Interface](BILLING-PROVIDER-INTERFACE.md).
