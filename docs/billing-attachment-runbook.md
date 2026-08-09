---
title: Billing Attachment Runbook
slug: operations/billing-attachment-runbook
section: operations
visibility: I
audience: [ops, dev-senior, architect, exec]
status: beta
since_version: "8.12.0"
canonical_owner: platform@aether
related:
  - docs/BILLING-PROVIDER-INTERFACE.md
  - docs/BILLING-REVENUE-OPS.md
  - docs/ACCOUNT-PLANS.md
  - docs/ENTITLEMENTS.md
  - docs/runbooks/RECONCILIATION.md
  - docs/staging-activation-runbook.md
estimated_read_minutes: 12
---

# Billing Attachment Runbook

How **pricing and invoicing attach** to Aether's existing entitlement + metering
substrate **without changing a single domain implementation**. The substrate is
already in place and additive; this runbook is the operator's recipe for turning
that substrate into billable revenue.

The core guarantee: **attachment is configuration and data, not code.** A
capability's execution path does not change when pricing is attached. What
changes is (a) the entitlement/contract rows that describe *what* a tenant may
use, (b) the price/plan mapping rows that say *what it costs*, and (c) the
billing-provider mode that says *who collects and how invoices are exported*.
The enforcement and metering happen at the single shared seam
(`meter_capability_usage`), which every commercial capability already calls or
can call with one line.

## 1. The substrate (what already exists)

| Concern | Module / artifact | Durable table |
| --- | --- | --- |
| Contract profile | `services/billing/revops.py` → `TenantContractProfile`, `TenantContractProfileRepository` | `tenant_contract_profiles` |
| Entitlements | `services/billing/revops.py` → `TenantEntitlement`, `EntitlementService` (`.evaluate`, `.enforce_dimension`) | `tenant_entitlements` |
| Usage meter | `services/billing/revops.py` → `MeteringService`, `UsageMeteringEvent`, `MeteringEventType` | `usage_metering_events` |
| Evidence | `services/metering_evidence/service.py` → `MeteringEvidenceService.record` / `.explain` | `metering_evidence` |
| Metering + entitlement seam | `services/metering_evidence/hooks.py` → `meter_capability_usage`, `MeterOutcome` | (writes both tables above) |
| Dimension families | `services/metering_evidence/families.py` → `CAPABILITY_FAMILIES`, `meter_family_usage` | — |
| Reconcile | `services/metering_evidence/reconciliation.py` → `ReconciliationEngine` | (read-only over the three truths) |
| Usage summary | `services/billing/revops.py` → `UsageSummaryService.calculate` | `billable_usage_summaries` |
| Invoice preview | `services/billing/revops.py` → `InvoicePreviewService.generate` | `invoice_previews` |
| Value created | `services/billing/revops.py` → `ValueCreatedEventService` | `value_created_events` |
| Leakage + expansion | `services/billing/revops.py` → `RevenueLeakageService`, `ExpansionBillingService` | `revenue_leakage_signals` |
| Billing provider seam | `services/billing/providers/base.py` → `BillingProvider` ABC | — |
| Plan catalog | `shared/plans/catalog.py` → `PLAN_CATALOG`; `shared/auth/auth.py` → `PlanTier` (P1–P4) | — |
| Legacy overage cycle | `services/billing/cycle.py`, `services/billing/cron.py`, `shared/billing/overage.py` | `tenant_billing_accounts`, `overage_invoices` |
| Tenant API | `services/billing/routes.py` → `/v1/billing/*`, `/v1/admin/billing/*`, `/v1/admin/kyber/revops/*` | — |

Two table families exist:

- **First-party billing tables** with a real alembic migration
  (`alembic/versions/20260519_b2c3d4e5_billing_tables.py`,
  `20260519_c3d4e5f6_usage_tables.py`): `tenant_billing_accounts`,
  `overage_invoices`, `stripe_webhook_events`, `stripe_invoices`,
  `stripe_overage_invoice_attempts`, `tenant_usage`, `provider_usage`.
- **JSONB-backed revops/evidence tables** that repositories create through
  `BaseRepository` (`repositories/repos.py` → `_ensure_table`) with the shape
  `id TEXT PRIMARY KEY, data JSONB, tenant_id TEXT, created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ`: `tenant_contract_profiles`, `tenant_entitlements`,
  `usage_metering_events`, `billable_usage_summaries`, `invoice_previews`,
  `revenue_leakage_signals`, `value_created_events`, `metering_evidence`. These
  are **pending migrations** — see the integration notes at the end.

## 2. The three usage truths (must stay reconciled)

The commercial invariant the substrate enforces is:

```
tenant entitled, capability executed, usage occurred exactly once, evidence durable
```

Three truths run in parallel and `ReconciliationEngine`
(`services/metering_evidence/reconciliation.py`) compares them:

1. **Quota-engine counters** — `rl:quota` / `rl:overage` (Redis hot path) plus
   the `tenant_usage` snapshot (Postgres), counted per request by middleware.
2. **`usage_metering_events`** — the RevOps meter, per dimension.
3. **`metering_evidence`** — durable, per-usage evidence, dedupe fail-closed for
   double billing (`excluded_reason="duplicate"`).

The reconcile API is `POST /v1/metering/evidence/reconcile` (body-bounded by
`period_start` / `period_end`; returns `RECONCILED` or `RECONCILIATION_CONFLICT`
with typed discrepancies). **Reconcile before you invoice.** A conflict
(`evidence_missing`, `evidence_double_count`, `entitled_no_entitlement`,
`quota_not_incremented`, `overage_unmetered`) means the period is not ready to
price.

## 3. Attachment steps (in order, no domain changes)

### Step 1 — Pick the billing mode (configuration only)

`BILLING_PROVIDER_MODE` selects the provider through
`services/billing/providers/base.py` (`get_billing_provider`):

| Mode | Class | Invoice export | Payment status |
| --- | --- | --- | --- |
| `internal_only` (default) | `InternalOnlyProvider` | `internal_preview` | `externally_managed` |
| `manual_invoice` | `ManualInvoiceProvider` | `manual_artifact` | `externally_managed` |
| `enterprise_contract` | `EnterpriseContractProvider` | `approved_preview` | `externally_managed` |
| `stripe` | `StripeBillingProvider` (import-safe, feature-flagged stub) | `provider_export` | live |

Switching modes is a settings change in the deploy target — no domain code.
`internal_only` is the zero-risk default: everything works, nothing is sent to a
processor. The resolver (`resolve_provider_type`) short-circuits to
`internal_only` whenever `AETHER_EXTERNAL_BILLING_ENABLED` is false; `stripe` is
selected only with that parent flag **plus** `AETHER_STRIPE_BILLING_ENABLED=true`
(or `BILLING_PROVIDER_MODE=stripe`), and the provider still refuses every
external mutation (`ProviderDisabledError`) until it is configured with a real
`STRIPE_SECRET_KEY` (`is_configured()`). Readiness is exposed read-only at
`GET /v1/billing/capability` (`stripe_client.capability_status()`).

### Step 2 — Declare the pricing contract (data, not code)

Price/plan mapping lives in `services/billing/providers/mappings.py` as
`ProductPriceMapping` rows:

```python
ProductPriceMapping(
    package_id="founding",
    plan_tier="P2",
    feature_key=None,
    usage_dimension="graph_operation",
    provider_product_id="prod_XXX",   # Stripe when provider_export is used
    provider_price_id="price_XXX",    # Stripe when provider_export is used
    status="mapped",
)
```

`map_product(package_id)` and `map_price(plan_tier, usage_dimension)` are the
interface `BillingProvider` methods that consume these rows. Under
`internal_only` / `manual_invoice` / `enterprise_contract` the mapping is still
authoritative for *previews* but no processor price is required
(`provider_price_id=None`, `status="unmapped"`).

### Step 3 — Seed the contract + entitlement rows

Attachment is expressed as data:

- `TenantContractProfile` (`tenant_contract_profiles`): one per tenant with
  `billing_model` (`flat_subscription | usage_based | hybrid |
  enterprise_contract | value_based | pilot`), `billing_period`, `plan_tier`,
  `contract_status`, `renewal_date`, `currency`, `payment_terms`.
- `TenantEntitlement` (`tenant_entitlements`): one per `feature_key` with
  `enabled`, `included_quantity`, `overage_allowed`, `overage_unit_price_notes`,
  `reset_period` (`monthly | quarterly | annual | never`).

These rows are the *only* thing that makes a dimension billable. `EntitlementService`
reads them to evaluate and to enforce. A dimension with no enabled entitlement
is not billable — and the reconciliation engine flags usage that occurred
without one (`entitled_no_entitlement`), so you cannot accidentally bill an
un-entitled tenant.

### Step 4 — Verify the metering seam covers the dimension

The domain paths do not change; the metering hook is the one seam. Each
commercial capability family maps to a canonical dimension in
`services/metering_evidence/families.py` (`CAPABILITY_FAMILIES`, e.g.
`ingestion → event_ingested`, `graph → graph_operation`,
`profile360 → profile_query`). Execution paths call
`meter_capability_usage(tenant_id, dimension=…, event_id=…, dedupe_key=…,
source_path=…)` (or the family helper `meter_family_usage`) which, in one call:

1. **Enforces entitlement** fail-closed via `EntitlementService.enforce_dimension`
   (disabled/absent/over-budget without overage → `ENTITLEMENT_DENIED` outcome
   or `EntitlementDeniedError` 403),
2. **Writes durable evidence** (`metering_evidence`) with per-tenant dedupe
   (`excluded_reason="duplicate"` on a repeated `dedupe_key`),
3. **Records the usage meter event** (`usage_metering_events`) idempotent on
   `source_type` + `source_id` + `event_type`.

Metering-store failure is **never silent**: the hook raises `MeteringStoreError`
by default rather than dropping a billable event. If a dimension is not yet
metered at its execution path, add the one-line hook call — that is the only
domain-touching change, and it is additive (a no-op for `billable=False`).

> Do not attach pricing to a dimension whose execution path does not yet call
> the seam: **unmetered = unbillable**, and the reconcile gate
> (`overage_unmetered`) will say so.

### Step 5 — Generate usage summaries + invoice previews

Per billing period (start/end), in order:

1. `UsageSummaryService.calculate(tenant_id, start, end)` →
   `BillableUsageSummary` (`billable_usage_summaries`): usage, included usage,
   and overage **by dimension** plus billable/non-billable event counts.
2. `InvoicePreviewService.generate(tenant_id, start, end)` →
   `InvoicePreview` (`invoice_previews`): line items separating included from
   overage, `subtotal_notes`, `value_created_summary`; status lifecycle
   `draft → review_ready → approved → exported`
   (`InvoicePreviewService.update_status`). Amounts remain **notes** until exact
   pricing is configured — the preview is the honest, auditable artifact even
   before a processor is attached.

Review the preview before any export. Revenue-ops review lives under
`/v1/admin/kyber/revops/*` (Kyber operator gated).

### Step 6 — Export through the billing provider

When a preview is approved, export through the active provider:

- `internal_only` / `manual_invoice` / `enterprise_contract` export offline
  artifacts (`internal_preview`, `manual_artifact`, `approved_preview`) — no
  processor call, payment tracked as `externally_managed`.
- `stripe` (once configured) maps each line via `ProductPriceMapping` and calls
  `export_invoice` (invoice retrieval/creation), `create_subscription`,
  `create_usage_record`, etc. Webhooks arrive at the Stripe webhook receiver;
  `handle_webhook` verifies the Stripe HMAC signature and is idempotent
  (`stripe_webhook_events`), mapping `invoice.paid` → `paid`,
  `invoice.payment_failed` → `failed`, etc.

### Step 7 — Overage invoicing (optional)

The legacy overage cycle (`services/billing/cycle.py::run_overage_cycle`,
triggered by the async `services/billing/cron.py::run_monthly_overage_cron` or
`POST /v1/admin/billing/overage-cycle`) iterates tenants with an active
`tenant_billing_accounts` subscription, computes overage with
`shared/billing/overage.py::OverageCalculator`, and writes invoice items. It is
gated by `STRIPE_OVERAGE_PRICE_ID` and returns a no-op summary when
`overage_invoicing_enabled` is false. Note this cycle prices against the
per-request quota counters (`tenant_usage`), which is the *legacy* overage
path; the revops path in Steps 3–6 is dimension-based and is the one the
reconciliation engine audits. Keep both reconciled or keep the legacy cycle
disabled while the dimension-based flow is the source of truth.

### Step 8 — Reconcile and watch revenue ops

1. Re-run `POST /v1/metering/evidence/reconcile` for the period. Clean →
   `RECONCILED`; any conflict blocks the period from being priced/exported.
2. Watch leakage + expansion: `RevenueLeakageService.detect`
   (`revenue_leakage_signals`) surfaces `overage_not_priced`,
   `premium_module_unpriced`, `connector_unpriced`, `value_created_unmonetized`,
   `deployment_underpriced`, `services_unbilled`, `audit_exports_unpriced`.
   `ExpansionBillingService.opportunities` recommends where to attach pricing
   next.
3. Confirm tenant-facing surfaces (`GET /v1/billing/plans`, `/invoices`) and the
   Kyber RevOps views.

## 4. The no-domain-change guarantee

Changing pricing never requires editing a domain implementation because:

- **Enforcement and metering are one seam** (`meter_capability_usage`) that
  commercial capability paths already share; attaching pricing only changes
  *data* that seam reads.
- **Providers are a configuration-selected seam** (`BILLING_PROVIDER_MODE`),
  import-safe and offline by default; `StripeBillingProvider` never imports the
  SDK at module load and never calls out until `AETHER_STRIPE_BILLING_ENABLED`
  is true with a configured secret.
- **Dedupes are fail-closed for double billing** (per-tenant `dedupe_key` →
  non-billable `duplicate`), so re-attaching pricing or replaying webhooks can
  never invoice twice.
- **Every mutation is auditable**: billing contract changes emit security-audit
  events, billing records are retention-preserved, and `sanitize_metadata`
  strips secret-named keys before anything is persisted, logged, or exported
  (`services/billing/revops.py`, `services/security/contracts.py`).

## 5. Verification checklist

1. `BILLING_PROVIDER_MODE` resolved as intended: `GET /v1/billing/capability`
   matches the mode and `stripe_client.capability_status()` is honest.
2. `TenantContractProfile` + `TenantEntitlement` rows exist for the tenant; the
   entitlement evaluation for the target dimension returns `included` (or
   `overage` when overage is allowed).
3. A real metered event produced both a `usage_metering_events` row and a
   `metering_evidence` row (`GET /v1/metering/evidence/{id}`), and the quota
   counter agrees — reconcile is `RECONCILED`.
4. Invoice preview generated with correct included-vs-overage line items and
   advanced `draft → review_ready → approved`.
5. Export produced the expected artifact (offline artifact, or Stripe
   invoice/usage records) and the payment status advanced via the webhook path.
6. Tenant readiness reflects billing: the §3.13 launch gates
   `usage_metering_verified` and `billing_mode_verified` are `passed` for the
   tenant (`services/tenant_readiness/service.py`,
   `GET /v1/tenant/readiness`).

## Integration-pass notes (owned by the integration pass, not this doc)

- **Pending JSONB-backed tables needing alembic migrations** (repos already
  reference them; `BaseRepository` auto-creates them locally): add DDL for
  `tenant_contract_profiles`, `tenant_entitlements`, `usage_metering_events`,
  `billable_usage_summaries`, `invoice_previews`, `revenue_leakage_signals`,
  `value_created_events`, `metering_evidence`. Standard shape per
  `repositories/repos.py::BaseRepository._ensure_table`: `id TEXT PRIMARY KEY,
  data JSONB NOT NULL DEFAULT '{}', tenant_id TEXT, created_at TIMESTAMPTZ
  DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()` plus
  `idx_<table>_tenant` on `tenant_id`.
- **Family hooks**: for any commercial family in `CAPABILITY_FAMILIES` whose
  execution path does not yet call the seam, wrap it with
  `meter_family_usage` (or `meter_capability_usage`) — this is the only additive
  domain-touching wiring.
- **Stripe live wiring**: enabling real Stripe collection additionally needs
  configured `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET`, price rows in
  `mappings.py`, and `AETHER_STRIPE_BILLING_ENABLED=true` in the deploy target.
