---
title: Billing, Usage Metering, Contracts, and Revenue Operations
slug: enterprise/invoice-previews
section: enterprise
visibility: I
audience: [exec, buyer, ops]
status: stable
since_version: "8.9.0"
---

# Billing, Usage Metering, Contracts, and Revenue Operations

Olympus Labs now has an internal, billing-ready revenue operations layer. It tracks tenant contract profiles, package entitlements, tenant-safe usage, billable metering events, value-created events, draft invoice previews, revenue leakage signals, and expansion billing opportunities without requiring immediate payment collection or a new external billing provider.

## Scope

- **Tenant-visible:** current package, billing period, enabled modules, included usage, current usage by dimension, audit export usage, integration usage, recommendation/playbook/outcome usage, invoice preview status, and customer-facing value-created metrics.
- **Kyber/operator-visible:** contract terms, payment terms, internal notes, unpriced overages, package mismatches, disabled-feature usage, revenue leakage, deployment/services pricing risks, and expansion billing recommendations.
- **Not included:** final payment collection, tax calculation, Stripe price mapping for these new dimensions, or automatic tenant exposure of internal Olympus revenue strategy.

## Usage dimensions

The metering substrate supports `event_ingested`, `entity_resolved`, `graph_operation`, `profile_query`, `recommendation_generated`, `decision_recorded`, `action_logged`, `action_dispatched`, `outcome_observed`, `playbook_run`, `audit_export_generated`, `integration_delivery`, `premium_connector_used`, `deployment_mode_active`, `managed_workflow_triggered`, and `value_created`.

## Metering source and controls

`MeteringService` records tenant-scoped events with optional `source_type`/`source_id` idempotency. Metadata is allowed, but keys such as tokens, API keys, credentials, passwords, authorization headers, and private keys are stripped or redacted. `AETHER_USAGE_METERING_ENABLED=false` gracefully makes metering a no-op.

## Entitlements and billing period logic

Each entitlement defines a `feature_key`, whether it is enabled, included quantity, overage allowance, overage price notes, and reset period. Reset periods are modeled as monthly, quarterly, annual, or never; services accept explicit period start/end windows so scheduled jobs can calculate custom contract windows.

## Invoice preview logic

Invoice previews are draft operational artifacts. They load the tenant contract profile, entitlements, and usage events for the selected period; generate line items; separate included and overage usage; attach value-created summaries; and move through `draft`, `review_ready`, `approved`, and `exported` statuses. Amounts remain notes until exact pricing configuration exists.

## Value-created events

Value-created events can originate from outcomes, playbooks, recommendation families, integration actions, or manual adjustments. They capture known amount, currency, confidence, attribution notes, and whether the current contract makes the value event billable.

## Revenue leakage detection

Revenue leakage signals detect unpriced overages, premium module or connector usage without entitlement, high value creation under non-value-based contracts, underpriced deployment modes, managed services usage without services terms, and high audit export volume without audit/enterprise packaging.

## Tenant vs Kyber visibility

Tenant routes under `/v1/billing/*` return customer-safe plan and usage information only. Kyber routes under `/v1/admin/kyber/revops/*` require admin/operator permission and expose internal contract, leakage, invoice review, and expansion billing data.

## Rollout notes and known gaps

This layer is billing-ready and audit-friendly. Production rollout should connect scheduled metering hooks from ingestion, graph, Profile360, recommendations, decisions, actions, outcomes, playbooks, audit exports, integrations, deployment, and managed workflow systems. External payment collection, taxes, exact SKU prices, and ERP export are future integrations.
