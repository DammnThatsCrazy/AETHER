---
title: Connector Taxonomy
slug: architecture/connector-taxonomy
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: platform@aether
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/base.py
  - Backend Architecture/aether-backend/shared/integration_contracts/catalog.py
  - Backend Architecture/aether-backend/shared/integration_contracts/experience.py
last_synced_commit: "8b1ca3dc"
estimated_read_minutes: 6
toc_depth: 3
---

# Connector Taxonomy

> Every connector in Aether is classified along the six-layer corpus model:
> one `ConnectorClass`, one `ConnectorRole`, a declared `DataFlowDirection`,
> and the policy enums (`LakeWritePolicy`, `GraphWritePolicy`,
> `ModelTrainingEligibility`) that determine what the platform may do with the
> data the connector touches, plus `ImplementationStatus`, `PriorityPhase`, and
> `RiskTier`. Policy is enforced at connector registration/descriptor time, not
> at ingestion time.

This document is the taxonomy **as the code declares it**. The authoritative
definitions live in
`Backend Architecture/aether-backend/services/integrations/connectors/base.py`
(the enums below) and the customer catalog derives its four-group
provider/category mirror from
`shared/integration_contracts/catalog.py` (see §8). The TypeScript twin in
`packages/shared/connector-taxonomy.ts` carries a verbatim copy of the six-layer
enums plus the generated catalog mirror and is **generated** — never hand-edited.

## 1. Why a taxonomy?

- A machine-readable classification that drives lake-write and graph-write policy.
- A governance audit anchor: every data grant references a connector's class,
  role, and declared policies.
- A filtering surface for UI and docs (show tenant-visible BYOD connectors,
  hide `QUARANTINE_ONLY`/compliance-gated surfaces, etc.).
- A training-eligibility gate that prevents accidental model contamination.

## 2. ConnectorClass

Describes the corpus layer the connector belongs to.

| Class | Meaning |
|---|---|
| `OLYMPUS_PROVIDER` | Layer 1 — Olympus-owned external APIs (Dune, DeFi Llama, price/chain data, …) |
| `TENANT_BYOD_DATA` | Layer 2 — tenant-supplied CRM/commerce/analytics/communications connectors |
| `BYOK_GATEWAY` | Layer 4 — tenant-owned credential gateway (credential control only) |
| `ACTION_NOTIFIER` | Layer 5 — outbound action connectors (Slack, Jira actions, …) |
| `DUAL_ROLE` | Connector with both ingest and action capabilities (modeled as separate `ConnectorCapability`s) |

Note: legacy docs referenced `IDENTITY_BRIDGE` and `AGENT_TOOL` classes. Those
never existed in `base.py` and have been removed from this spec; cross-system
identity resolution and agent tool surfaces are modeled as capabilities of a
declared class/role, not as their own classes.

## 3. ConnectorRole

| Role | Meaning |
|---|---|
| `DATA_INGESTION` | Pulls/normalizes inbound source data |
| `ACTION_DELIVERY` | Delivers outbound actions |
| `CREDENTIAL_GATEWAY` | Owns a tenant credential; routes requests |
| `ENRICHMENT_PROVIDER` | Adds enrichment from an external corpus |
| `WEBHOOK_RECEIVER` | Receives verified inbound webhooks |
| `SYNC_SOURCE` | Pull-model sync source with cursor/backfill |
| `REALTIME_STREAM` | Live stream consumer |
| `BATCH_BACKFILL` | Historical batch backfill |
| `QUERY_EXECUTION` | Executes queries against a provider |
| `WAREHOUSE_DATASHARE` | Shares a warehouse dataset |
| `DUAL_ROLE` | Capability modeled separately on a dual-role connector |

## 4. DataFlowDirection

| Direction | Meaning |
|---|---|
| `INBOUND` | Data flows into Aether (read from source) |
| `OUTBOUND` | Data flows out of Aether (write to destination) |
| `BIDIRECTIONAL` | Read and write; requires explicit policy on both paths |
| `NONE` | No data flow (pure control/credential surface) |

## 5. ConnectorDescriptor defaults

Every connector carries a `ConnectorDescriptor` with taxonomy fields defaulting
to the tenant-BYOD posture; subclasses override per connector. The defaults
encode the honest baseline:

| Field | Default |
|---|---|
| `connector_class` | `TENANT_BYOD_DATA` |
| `connector_role` | `DATA_INGESTION` |
| `data_flow_direction` | `INBOUND` |
| `lake_write_policy` | `TENANT_ONLY` |
| `graph_write_policy` | `TENANT_GRAPH_ONLY` |
| `model_training_eligibility` | `NEVER` |
| `implementation_status` | `CREDENTIAL_GATED` |
| `priority_phase` | `NOT_SCHEDULED` |
| `risk_tier` | `LOW` |

Dual-role connectors (e.g. Jira) declare each capability separately
(`ConnectorCapability`) so policies, grants, and health states stay isolated.

## 6. Policy enums

### LakeWritePolicy

Controls which lake layers this connector's data may write to.

| Policy | Meaning |
|---|---|
| `NEVER` | Action-notifier connectors — no lake writes permitted |
| `TENANT_ONLY` | Tenant BYOD data writes to tenant-scoped lake only |
| `OLYMPUS_BASELINE_ELIGIBLE` | Olympus provider data eligible for baseline lake (provenance required) |
| `OLYMPUS_BASELINE_ALLOWED` | Olympus provider data cleared for baseline after review |
| `QUARANTINE_ONLY` | Data lands in quarantine until provenance/license review passes |

### GraphWritePolicy

Controls which graph layers this connector's data may write edges/vertices to.

| Policy | Meaning |
|---|---|
| `NONE` | No graph mutations permitted |
| `TENANT_GRAPH_ONLY` | Edges written only to the tenant's graph partition |
| `TENANT_GRAPH_AND_AGGREGATE_ELIGIBLE` | Tenant edges + aggregate-eligible (no raw tenant leakage) |
| `OLYMPUS_GRAPH_ALLOWED` | Olympus graph mutations permitted with lineage |
| `QUARANTINE_ONLY` | Graph writes blocked pending provenance/license review |

### ModelTrainingEligibility

| Policy | Meaning |
|---|---|
| `NEVER` | Data excluded from training pipelines |
| `TENANT_ONLY` | Usable for tenant-scoped models only |
| `AGGREGATE_ONLY` | Usable in aggregate, never raw |
| `OLYMPUS_ALLOWED` | Usable for Olympus-baseline models |
| `COMPLIANCE_REVIEW_REQUIRED` | Conditional on an active compliance/legal review |

## 7. Implementation state, priority, risk

### ImplementationStatus

Honest implementation readiness. Do not claim a connector is live if it is only
mocked or credential-gated.

| Status | Meaning |
|---|---|
| `SCAFFOLDED` | Design/scaffold only; no live surface |
| `PRODUCTION_SHAPED` | Production-shaped code path, not yet live-backed |
| `CREDENTIAL_GATED` | Implemented behind a real credential (default honest state) |
| `PROVIDER_LIVE` | Live against the real provider |
| `WAREHOUSE_DATASHARE_READY` | Warehouse datashare cleared |
| `STAGING_VALIDATION_REQUIRED` | Needs staging validation before live |
| `DISABLED_COMPLIANCE_REVIEW` | Deliberately disabled pending legal review |
| `DEPRECATED` | Being phased out; do not extend |

### PriorityPhase

| Phase | Meaning |
|---|---|
| `PHASE_1_FOUNDATION` | Core data backbone; ships with the foundation |
| `PHASE_2_ENRICHMENT` | Adds depth to foundation signals |
| `PHASE_3_DEPTH` | Specialized or compliance-gated sources |
| `NOT_SCHEDULED` | No committed build phase |

### RiskTier

| Tier | Meaning |
|---|---|
| `LOW` | Outage has no user-visible effect |
| `MEDIUM` | Outage causes minor feature gaps |
| `HIGH` | Outage reduces signal quality significantly |
| `RESTRICTED` | Compliance/legal-restricted; additional gating |

## 8. Customer catalog (four-group mirror)

The **customer** provider taxonomy is a derived four-group union over the
authoritative backend manifests (`shared/integration_contracts/catalog.py`),
grouped by product id: `connectors` (ingestion.connector, 21), `ad_platforms`
(ads.metrics, 7), `payment_rails` (payment_rails.observe, 5), and
`deferred_credit_bureaus` (credit.report, 3) — 36 `family.product.capability`
identities in `ALL_MANIFESTS`. The `deferred_credit_bureaus` group is
scaffolded and not shown on customer surfaces.

| Group (`product.capability`) | Count | Families |
|---|---|---|
| `connectors` (`ingestion.connector`) | 21 | slack, webhook, shopify, stripe, hubspot, salesforce, klaviyo, segment, posthog, ga4, jira, linear, zendesk, intercom, dune, sendgrid, customerio, mailchimp, postmark, iterable, braze |
| `ad_platforms` (`ads.metrics`) | 7 | google_ads, meta_ads, tiktok_ads, linkedin_ads, x_ads, reddit_ads, microsoft_ads |
| `payment_rails` (`payment_rails.observe`) | 5 | privy, stripe, coinbase, moonpay, bridge |
| `deferred_credit_bureaus` (`credit.report`) | 3 | experian, equifax, transunion |

The mirror (group order, family arrays + counts, group/category tables,
`CATALOG_ENTRIES`, readiness states present, experience-category ordering) is
generated into `packages/shared/connector-taxonomy.ts` by
`scripts/generate_connector_taxonomy.py`. Tenant FE, activation, and marketing
consume identical ids from that generated module; parity contract tests in
`tests/contracts/` assert generator cleanliness and count/family parity against
the backend union. Experience grouping (which bucket a family renders under on
customer surfaces) follows `shared/integration_contracts/experience.py` — see
`AETHER_END_USER_LIFECYCLE.md` §6.
