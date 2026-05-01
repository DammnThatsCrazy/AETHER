# Stripe Billing — Aether P1–P4 Integration

This document describes how Aether integrates Stripe Billing with the
existing P1–P4 plan catalog (`shared/plans/catalog.py`), auth middleware,
Redis-backed rate limiting, monthly quota metering, and overage logic.

It does **not** create parallel systems for plans, pricing, rate limiting,
or quotas — Stripe is a payment + invoicing surface that drives the existing
`tenant_billing_accounts.plan_tier` value, which the existing middleware
already consumes.

---

## Stripe Dashboard setup (still required)

Before turning `STRIPE_BILLING_ENABLED=true` in dev/staging/production:

1. **Create Stripe Products & recurring Prices** for each Aether plan:
   - **P1 Hobbyist** → recurring subscription Price
   - **P2 Professional** → recurring subscription Price
   - **P3 Growth Intelligence** → recurring subscription Price
   - **P4 Protocol Master** → recurring subscription Price

   Pricing amounts (Option A / B / C) live in
   `shared/plans/catalog.py::PLAN_CATALOG`. Aether does **not** ship hard-coded
   Stripe Price IDs; the operator must paste them into env vars below.

2. **Set the Price IDs in env**:
   ```env
   STRIPE_PRICE_P1=price_xxx_p1
   STRIPE_PRICE_P2=price_xxx_p2
   STRIPE_PRICE_P3=price_xxx_p3
   STRIPE_PRICE_P4=price_xxx_p4
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
   - Run Aether with `AETHER_ENV=local`. If Stripe keys/Price IDs are missing,
     the Checkout/Portal endpoints return mocked URLs instead of failing
     (see "Local mocked mode" below).

---

## Required env vars

| Var | Purpose |
| --- | --- |
| `STRIPE_BILLING_ENABLED` | Master toggle (default `false`). |
| `STRIPE_SECRET_KEY` | Stripe API secret. Required in non-local when enabled. |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for webhook signature verification. |
| `STRIPE_PRICE_P1..P4` | Recurring subscription Price IDs for each plan. |
| `STRIPE_OVERAGE_PRICE_ID` | OPTIONAL Price ID for overage line items. |
| `STRIPE_CHECKOUT_SUCCESS_URL` | Redirect URL after successful Checkout. |
| `STRIPE_CHECKOUT_CANCEL_URL` | Redirect URL on cancelled Checkout. |
| `STRIPE_PORTAL_RETURN_URL` | Return URL from the Stripe Billing Portal. |

In **non-local** environments with `STRIPE_BILLING_ENABLED=true`, the secret
key, webhook secret, all four Price IDs, and the checkout/portal URLs are
required — `Settings.__post_init__` raises `RuntimeError` if any are missing.
In **local** mode, they may be unset.

---

## API surface

All routes (except the webhook) require the existing `billing` permission and
go through normal Aether auth, rate-limit, and quota middleware.

| Method | Route | Notes |
| --- | --- | --- |
| `POST` | `/v1/admin/tenants/{tenant_id}/billing/checkout-session` | Creates a subscription Checkout Session. Body: `{ "plan_tier": "P3", "contact_email": "..." }`. Local plan_tier is **not** changed here. |
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
| `customer.subscription.created` | Sync subscription state. Update `plan_tier` only if status is `active`/`trialing` and the price matches a configured `STRIPE_PRICE_P*`. |
| `customer.subscription.updated` | **Authoritative.** Map subscription item Price ID back to PlanTier; on `active`/`trialing` update `plan_tier`, status, current_period_end. On `canceled`/`unpaid`/`incomplete_expired` downgrade to P1. On `past_due` keep current plan. |
| `customer.subscription.deleted` | Mark canceled, downgrade to P1. |
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

## Local mocked mode

When `AETHER_ENV=local` and Stripe configuration is incomplete (missing
`STRIPE_SECRET_KEY` or any `STRIPE_PRICE_P*`), the client returns mocked
URLs so the flows can be exercised without real Stripe:

- Checkout: `cs_mock_<tenant_id>_<plan_tier>` →
  `http://localhost:3000/mock-stripe/checkout?tenant_id=...&plan_tier=...`
- Portal: `http://localhost:3000/mock-stripe/portal?tenant_id=...`

Mocked mode is **never** used outside `AETHER_ENV=local`.

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
