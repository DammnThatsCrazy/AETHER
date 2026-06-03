---
title: Payment Operations
slug: operations/payment-operations
section: operations
visibility: I
audience: [ops, exec]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Payment Operations

Operational (non-code) tasks to run billing in production. Aether **does not
store bank account credentials directly** — those live with the payment
provider through their secure flows.

## Operational checklist

- [ ] **Stripe account**: business profile, statement descriptor, support
      contact.
- [ ] **Payout bank account**: added in Stripe (not in Aether).
- [ ] **Tax settings**: Stripe Tax / tax IDs as applicable.
- [ ] **Invoice branding**: logo, footer, terms.
- [ ] **Payment methods**: cards / ACH / wire as needed.
- [ ] **Dunning**: retry schedule + failed-payment emails.
- [ ] **Customer portal**: enabled; `STRIPE_PORTAL_RETURN_URL` set.
- [ ] **Accounting export**: reconcile Stripe payouts to your ledger.

## Mapping to Aether

Internal usage/invoice previews ([OODA & Outcome Usage Dimensions](OODA-USAGE-DIMENSIONS.md))
map to provider products/prices via the mapping config. Tenant-facing surfaces
show plan, usage, invoice-preview status (if approved/customer-facing), and
payment status (if a provider is enabled) — never revenue leakage or internal
overage strategy.

See [Stripe Readiness](STRIPE-READINESS.md) and [Billing Provider Interface](BILLING-PROVIDER-INTERFACE.md).
