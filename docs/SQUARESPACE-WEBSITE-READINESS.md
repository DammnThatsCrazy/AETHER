---
title: Squarespace Website Readiness
slug: operations/squarespace-website-readiness
section: operations
visibility: I
audience: [ops, buyer]
status: beta
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Squarespace Website Readiness

Guidance for keeping Squarespace as the registrar/authoritative DNS provider
and optional apex editorial surface alongside the Amplify-hosted Olympus Labs
and Aether web applications. **No Squarespace API integration is built** —
there is no Squarespace abstraction in the repo; this is an operational DNS and
content checklist only.

## Checklist

- [ ] Keep `olympuslabsml.com` in Squarespace and configure the apex to redirect
      to the Amplify-hosted `https://www.olympuslabsml.com` surface.
- [ ] After the production Amplify association is created, copy the
      `amplify_custom_domain_dns_records` Terraform output into Squarespace DNS
      for `www`, `aether`, `docs`, `app`, and `status`.
- [ ] Do not create a public Kyber DNS record. Kyber is an internal operator
      surface and is not part of the public launch.
- [ ] Link "Launch app" / "Login" CTAs to `https://app.[domain]`.
- [ ] Link "Book a demo" to the Demo App (`https://demo.[domain]`) or a booking
      flow.
- [ ] Link pricing/checkout to Stripe customer-portal / payment links when
      external billing is enabled (`STRIPE_PORTAL_RETURN_URL`); otherwise to a
      contact/sales flow. Billing stays flag-gated — see
      [External Billing Integration](EXTERNAL-BILLING-INTEGRATION.md).
- [ ] Keep the status page visibly unverified until the API health endpoint,
      certificate, CORS, and structured payload have passed staging checks.
- [ ] Add analytics (GA4/PostHog) on the marketing site independently of the
      product apps.

## Out of scope

Automated content sync, Squarespace Commerce integration, and Squarespace
Developer APIs are not implemented and not planned in this pass. An explicit
Route 53 migration remains available through
`squarespace_hosted_zone_enabled`, but it is not the first-release default.

See [App Routing & Domains](APP-ROUTING-DOMAINS.md).
