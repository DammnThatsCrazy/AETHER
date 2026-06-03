---
title: Outcome Pricing Dimensions
slug: operations/outcome-pricing-dimensions
section: operations
visibility: I
audience: [exec, architect, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Outcome Pricing Dimensions

Aether's pricing can attach value to *outcomes and intelligence*, not only raw
volume. This page maps the OODA/outcome usage dimensions onto entitlements and
billing structure. **No exact prices are assigned here** — pricing values live
in approved pricing config (`shared/plans/`), and placeholders are used until
that config is approved.

## Entitlement mapping

Each dimension can be configured per tenant as a `TenantEntitlement`
(`services/billing/revops.py`): `feature_key` = the dimension, with
`included_quantity`, `overage_allowed`, and `overage_unit_price_notes`. The
`EntitlementService` splits usage into included vs. overage; `UsageSummaryService`
and `InvoicePreviewService` build invoice previews from the split.

## Outcome / value dimensions

Outcome-oriented dimensions support value-based billing models
(`billing_model = value_based`):

- `outcome_observed`, `confidence_updated` — learning-loop signals.
- `value_created` — monetary value evidence (`ValueCreatedEvent`: retained
  revenue, expansion revenue, avoided loss, operational savings, etc.).

Value-created events are **never** shown with internal revenue-leakage or
overage strategy on tenant-facing surfaces.

## Premium dimensions

`premium_connector_used`, `deployment_mode_active`, and
`managed_workflow_triggered` are flagged premium (`PREMIUM_DIMENSIONS`) and
priced above standard dimensions in approved config.

## Placeholders, not prices

Until approved pricing config exists, overage prices are expressed as notes
(`overage_unit_price_notes`) rather than hard amounts. See
[Pricing Architecture](PRICING-ARCHITECTURE.md),
[OODA & Outcome Usage Dimensions](OODA-USAGE-DIMENSIONS.md), and
[Rate Limits & Bursts](RATE-LIMITS-AND-BURSTS.md).
