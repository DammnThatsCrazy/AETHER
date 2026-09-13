---
title: Stripe Billing — Alpha–Omega Integration
slug: concepts/stripe-billing
section: concepts
visibility: P
audience: [dev-senior, ops, buyer]
status: stable
since_version: "0.1.0"
source_files:
  - Backend Architecture/aether-backend/shared/billing/stripe_client.py
  - Backend Architecture/aether-backend/services/billing/routes.py
  - Backend Architecture/aether-backend/shared/plans/catalog.py
canonical_owner: billing@aether
estimated_read_minutes: 6
toc_depth: 3
source_hashes:
  "Backend Architecture/aether-backend/services/billing/routes.py": "sha256:c5da14570c9272a06f1e9b3f296ac7892d33916d94d31c4fcfd3421bb1956429"
  "Backend Architecture/aether-backend/shared/billing/stripe_client.py": "sha256:2f1f6f6fa308966e61557addd32a15ef2bfac6f09a679e235c88db4a240e1a8a"
  "Backend Architecture/aether-backend/shared/plans/catalog.py": "sha256:fb48b227d7df2f2924088bea3eac0f3b83a036becff0f36418b5e82dcc1522f8"
---
# Stripe Billing — Aether Alpha–Omega Integration

This document describes how Aether integrates Stripe Billing with the
7-tier plan catalog (`shared/plans/catalog.py`): Alpha–Delta (self-serve)
and Epsilon/Omicron/Omega (contract). Auth middleware, Redis-backed rate
limiting, monthly quota metering, and overage logic all consume the plan
tier from `tenant_billing_accounts.plan_tier`.

It does **not** create parallel systems for plans, pricing, rate limiting,
or quotas — Stripe is a payment + invoicing surface that drives the existing
`tenant_billing_accounts.plan_tier` value, which the existing middleware
already consumes.

---

## Stripe Dashboard setup (still required)

Before turning `STRIPE_BILLING_ENABLED=true` in dev/staging/production:

1. **Create Stripe Products & recurring Prices** for each self-serve plan:
   - **Alpha** (Free) → recurring subscription Price
   - **Beta** ($299/mo) → recurring subscription Price
   - **Gamma** ($599/mo) → recurring subscription Price
   - **Delta** ($1,999/mo) → recurring subscription Price

   Contract tiers (Epsilon, Omicron, Omega) are provisioned through the
   admin operator path and do not require self-serve Stripe Prices.

   Pricing lives in `shared/plans/catalog.py::PLAN_CATALOG`. Aether does
   **not** ship hard-coded Stripe Price IDs; the operator must paste them
   into env vars below.

2. **Set the Price IDs in env**:
   ```env
   STRIPE_PRICE_ALPHA=price_xxx_alpha
   STRIPE_PRICE_BETA=price_xxx_beta
   STRIPE_PRICE_GAMMA=price_xxx_gamma
   STRIPE_PRICE_DELTA=price_xxx_delta
   # Contract tiers (optional — only if billing contract tiers through Stripe):
   # STRIPE_PRICE_EPSILON=price_xxx_epsilon
   # STRIPE_PRICE_OMICRON=price_xxx_omicron
   # STRIPE_PRICE_OMEGA=price_xxx_omega
   ```

3. **(Optional) Overage Price** — only if you want to charge Aether overage
   usage through Stripe invoices:
   ```env
   STRIPE_OVERAGE_PRICE_ID=price_xxx_overage
   ```
   When unset, Stripe overage invoicing is disabled and Aether continues to
   use its existing internal overage calculation (`shared/billing/overage.py`)
   for the `/v1/admin/tenants/{id}/billing` projection.

4. **Configure the webhook endpoint** in the Stripe Dashboard:
   - URL: `POST https://<your-host>/v1/admin/billing/stripe/webhook`
   - Subscribed events:
     - `checkout.session.completed`
     - `customer.subscription.created`
     - `customer.subscription.updated`
     - `customer.subscription.deleted`
     - `invoice.created`
     - `invoice.finalized`
     - `invoice.paid`
     - `invoice.payment_succeeded`
     - `invoice.payment_failed`
   - Copy the signing secret into `STRIPE_WEBHOOK_SECRET`.

5. **Local testing**:
   - Use Stripe **test mode** keys.
   - Forward events with the Stripe CLI:
     `stripe listen --forward-to localhost:8000/v1/admin/billing/stripe/webhook`
   - Run Aether with `AETHER_ENV=local`. If Stripe keys or Price IDs are missing,
     `GET /v1/billing/capability` reports `not_configured` and Checkout/Portal
     fail explicitly; the runtime never manufactures provider URLs.
     (see "Local mocked mode" below).

---

## Required env vars

| Var | Purpose |
| --- | --- |
| `STRIPE_BILLING_ENABLED` | Master toggle (default `false`). |
| `STRIPE_SECRET_KEY` | Stripe API secret. Required in non-local when enabled. |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for webhook signature verification. |
| `STRIPE_PRICE_ALPHA..DELTA` | Recurring subscription Price IDs for self-serve plans. |
| `STRIPE_PRICE_EPSILON/OMICRON/OMEGA` | (Optional) Price IDs for contract tiers. |
| `STRIPE_OVERAGE_PRICE_ID` | OPTIONAL Price ID for overage line items. |
| `STRIPE_CHECKOUT_SUCCESS_URL` | Redirect URL after successful Checkout. |
| `STRIPE_CHECKOUT_CANCEL_URL` | Redirect URL on cancelled Checkout. |
| `STRIPE_PORTAL_RETURN_URL` | Return URL from the Stripe Billing Portal. |

In **non-local** environments with `STRIPE_BILLING_ENABLED=true`, the secret
key, webhook secret, the four self-serve Price IDs (Alpha–Delta), and the
checkout/portal URLs are required — `Settings.__post_init__` raises
`RuntimeError` if any are missing. Contract tier Price IDs are optional.
In **local** mode, they may be unset.

---

## API surface

All routes (except the webhook) require the existing `billing` permission and
go through normal Aether auth, rate-limit, and quota middleware.

| Method | Route | Notes |
| --- | --- | --- |
| `GET` | `/v1/billing/capability` | Secret-free provider readiness: `not_configured`, `degraded`, or `available`. |
| `GET` | `/v1/billing/plans` | Customer-safe plan catalog; Stripe Price IDs are never exposed. |
| `POST` | `/v1/billing/checkout` | Tenant-scoped Checkout. Body: `{ "plan_tier": "beta" }`; only self-serve tiers (alpha–delta) accepted. |
| `POST` | `/v1/billing/portal` | Tenant-scoped portal creation for an existing billing customer. |
| `GET` | `/v1/billing/invoices` | Locally persisted invoices normalized to provider-independent customer fields. |
| `POST` | `/v1/admin/tenants/{tenant_id}/billing/checkout-session` | Creates a subscription Checkout Session. Body: `{ "plan_tier": "gamma", "contact_email": "..." }`. Local plan_tier is **not** changed here. |
| `POST` | `/v1/admin/tenants/{tenant_id}/billing/portal-session` | Stripe Billing Portal session for an existing customer. |
| `GET`  | `/v1/admin/tenants/{tenant_id}/billing/invoices` | Locally synced Stripe invoices for the tenant. |
| `GET`  | `/v1/admin/tenants/{tenant_id}/billing/invoices/{invoice_id}` | One locally synced invoice (tenant-scoped). |
| `POST` | `/v1/admin/tenants/{tenant_id}/billing/overage-invoice` | Creates a Stripe overage invoice. Disabled when `STRIPE_OVERAGE_PRICE_ID` is unset. Idempotent on `(tenant_id, billing_period)`. |
| `POST` | `/v1/admin/billing/stripe/webhook` | Stripe webhook ingress. Public from Aether auth (added to `PUBLIC_PATHS`); protected by `Stripe-Signature` verification. |

---

## Webhook → plan_tier flow

Plan changes are **only** applied after the authoritative subscription update
event (`customer.subscription.updated`). Specifically:

| Event | Action |
| --- | --- |
| `checkout.session.completed` | Persist `stripe_customer_id` + `stripe_subscription_id`. **Plan_tier is NOT changed.** |
| `customer.subscription.created` | Sync subscription state. Update `plan_tier` only if status is `active`/`trialing` and the price matches a configured `STRIPE_PRICE_*`. |
| `customer.subscription.updated` | **Authoritative.** Map subscription item Price ID back to PlanTier; on `active`/`trialing` update `plan_tier`, status, current_period_end. On `canceled`/`unpaid`/`incomplete_expired` downgrade to alpha. On `past_due` keep current plan. |
| `customer.subscription.deleted` | Mark canceled, downgrade to alpha. |
| `invoice.paid` / `invoice.payment_succeeded` | Upsert into `stripe_invoices` (status=paid). |
| `invoice.payment_failed` | Upsert invoice. **Does not** trigger downgrade by itself. |
| `invoice.finalized` / `invoice.created` | Upsert invoice metadata. |

After updating `plan_tier`, the webhook handler refreshes any cached API-key
entries for the tenant so that `BurstRateLimiter`, `QuotaEngine`, and
`FeatureGate` immediately see the new plan. `APIKeyValidator.validate_async`
also overlays the `tenant_billing_accounts.plan_tier` on each authentication
as a backstop for stale cache entries.

Webhook idempotency: every `event_id` is recorded in `stripe_webhook_events`
on first receipt; duplicate deliveries return 200 with `duplicate: true`.

---

## Unconfigured provider behavior

There is no runtime mocked billing mode. Incomplete Stripe configuration is an
explicit capability state, and provider operations fail with a dependency
error rather than fabricated success. Automated tests inject a test-only
provider fixture when they need to exercise successful Checkout or Portal
behavior without a live Stripe account.

---

## Storage

Schema is created idempotently by
`shared/billing/migrations.py::ensure_billing_tables` at backend startup:

- `tenant_billing_accounts` — primary tenant↔Stripe mapping + `plan_tier`.
- `stripe_webhook_events` — webhook event idempotency log.
- `stripe_invoices` — locally synced invoice records.
- `stripe_overage_invoice_attempts` — idempotent record of Stripe overage
  invoicing attempts, keyed by `(tenant_id, billing_period)`.

Existing `overage_invoices` (internal Aether projection) is preserved.

---

## Overage charging

- `STRIPE_OVERAGE_PRICE_ID` **unset** → existing Aether overage calculation
  remains the source of truth. The internal projection at
  `/v1/admin/tenants/{id}/billing` is unchanged. The Stripe overage endpoint
  returns a clear `400` error.
- `STRIPE_OVERAGE_PRICE_ID` **set** → operators can call
  `POST /v1/admin/tenants/{id}/billing/overage-invoice` to push the Aether
  overage amount into a Stripe invoice item + invoice. The endpoint is
  idempotent on `(tenant_id, billing_period)` to prevent double-charging.

The Stripe path **uses the Aether overage calculation** to determine the
amount; pricing is not duplicated.
