---
title: Squarespace Website Readiness
slug: operations/squarespace-website-readiness
section: operations
visibility: I
audience: [ops, exec, buyer]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Squarespace Website Readiness

Guidance for running the marketing site on Squarespace alongside the
env-driven product apps. **No Squarespace API integration is built** — there is
no Squarespace abstraction in the repo; this is an operational checklist only.

## Checklist

- [ ] Host the marketing site on Squarespace at the apex/`www` domain.
- [ ] Link "Launch app" / "Login" CTAs to `https://app.[domain]`.
- [ ] Link "Book a demo" to the Demo App (`https://demo.[domain]`) or a booking
      flow.
- [ ] Link pricing/checkout to Stripe customer-portal / payment links when
      external billing is enabled (`STRIPE_PORTAL_RETURN_URL`); otherwise to a
      contact/sales flow. Billing stays flag-gated — see
      [External Billing Integration](EXTERNAL-BILLING-INTEGRATION.md).
- [ ] Keep DNS for product subdomains in your DNS provider, not Squarespace, if
      Squarespace only owns the apex — see
      [Domain & DNS Readiness](DOMAIN-DNS-READINESS.md).
- [ ] Add analytics (GA4/PostHog) on the marketing site independently of the
      product apps.

## Out of scope

Automated content sync, Squarespace Commerce integration, and Squarespace
Developer APIs are not implemented and not planned in this pass.

See [App Routing & Domains](APP-ROUTING-DOMAINS.md).
