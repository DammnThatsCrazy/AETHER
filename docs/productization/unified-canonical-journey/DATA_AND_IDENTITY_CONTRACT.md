---
title: Data and Identity Contract — Unified Canonical Journey
slug: productization/unified-canonical-journey/data-and-identity-contract
section: operations
visibility: I
audience: [architect, ops, exec]
since_version: "8.12.0"
status: stable
source_files:
  - Backend Architecture/aether-backend/services/measurement/contracts.py
  - Backend Architecture/aether-backend/alembic/versions/20260627_canonical_activity.py
  - Backend Architecture/aether-backend/alembic/versions/20260725_ai_referral_attribution.py
last_synced_commit: "4e6fdad"
---

# Data and Identity Contract

## canonical_activity Table

The `canonical_activity` table is the single source of truth for all cross-rail activity facts.
Each activity also carries canonical-envelope attribution: `surface` (the emitting
origin plane — `web`, `server`, `ios`, … — from `context.surface`, added by
`20260733_canonical_activity_surface`) and `sequence_key` (a zero-padded ordering
key derived from `context.sequence.event`, giving deterministic intra-timestamp
ordering; NULL when the emitting SDK sent no sequence).
Every silver projector writes to its silver table; the base projector (`project_and_emit`) then
adapts and upserts into `canonical_activity` via `adapt_from_silver`.

For communication events the dispatcher fans one event out to multiple projectors
(comms lifecycle first) but only the `CommsProjector` emits canonical activity, keyed by a
source-derived canonical key — one real-world event always maps to exactly one activity
regardless of how many Silver projections it produces (ADR-C4,
`docs/comms/ADR_COMMUNICATIONS_INTELLIGENCE.md`).

### Identity Links

Every row carries the identity chain available at write time:
- `profile_id` — resolved Aether profile
- `cluster_id` — identity cluster
- `anonymous_id` — pre-resolution anonymous identity
- `account_id`, `organization_id` — B2B linkage
- `session_id`, `device_id`, `browser_id`, `install_id` — device/session context
- `wallet_id`, `wallet_address` — Web3 identity
- `agent_id` — agentic executor

### Activity Classification

- `activity_family`: web2 | web3 | campaign | commerce | agent | x402 | outcome
- `activity_type`: granular type from taxonomy (e.g., `page_view`, `transfer`, `click`)
- `actor_type`: human | agent | system
- Acquisition evidence: `source_class`, `referral_mediation_type`,
  `ai_provider`, `ai_product`, `journey_role`, `verification_level`,
  `evidence_confidence`, `source_classifier_version`, and
  `source_classification_id`
- Canonical traffic dimensions (classifier v3.0, independent of campaign
  identity): `traffic_origin`, `economic_class`, `channel_family`,
  `entry_method`, `proof_level`, and `evidence_conflicts`. The customer-facing
  fallback is `direct_unknown` ("Direct / Unknown") — never an unsupported
  typed-URL assertion. Source classification is preserved even when campaign
  resolution is `not_applicable` or fails.
- Eligibility/provenance: `attribution_eligible`, normalized referrer domain,
  and optional `verified_referral_link_id`

Classifier revisions are append-only evidence keyed by tenant, touchpoint,
classifier version, and stable input hash. Reclassification does not overwrite
the historical evidence used by an earlier attribution run.

### Idempotency

All writes use `ON CONFLICT DO NOTHING` on `(tenant_id, idempotency_key)`.
The idempotency key is stable across replay: `"{prefix}:{fact_id}:{tenant_id}"`.

### Tenant Isolation

Every query predicate includes `tenant_id`. No query returns rows without a tenant predicate.
The UNIQUE constraint `(tenant_id, idempotency_key)` allows same idempotency key across different tenants.

### Activity Status Lifecycle

```
observed → pending → confirmed → finalized
                  ↘ failed
                  ↘ reverted
                  ↘ reorged → (recompiled)
         → adjusted
         → deleted
         → tombstoned         (consent revocation)
         → consent_restricted (consent state restricted)
```

## journey_steps Table

`journey_steps` is a first-class table with one row per step per journey version.
Steps are ordered by `step_position` (chronological, deterministic).

Journey lineage is keyed by a typed identity (`profile`, `cluster`, or
`anonymous`), so identical raw identifier strings in different identity
namespaces cannot merge. Version activation and step insertion are atomic.
Steps use schema version 2 for acquisition evidence fields. Explicitly
ineligible discovery crawler/scanner/link-preview activity stays in
`canonical_activity` for audit but is excluded from primary steps; each journey
version records `excluded_source_noise_count`.

### Transition Taxonomy

| TransitionType | Meaning |
|----------------|---------|
| `same_session` | Consecutive steps in the same session |
| `new_session` | Session gap (> 30 min by default, configurable per family) |
| `cross_device` | Different device/browser fingerprint |
| `web2_to_web3` | Web2 activity followed by Web3 activity |
| `web3_to_web2` | Web3 activity followed by Web2 activity |
| `wallet_connected` | Wallet connection event |
| `cross_chain` | Different chain_id between consecutive Web3 steps |
| `human_to_agent` | Human actor followed by agent actor |
| `agent_to_human` | Agent followed by human (approval, review) |
| `campaign_to_owned_surface` | Campaign click → owned page/dApp |
| `owned_surface_to_conversion` | Owned surface → conversion event |
| `identity_resolved` | Identity resolution event between steps |
| `identity_merged` | Identity merge between steps |
| `consent_state_changed` | Consent state change between steps |

## Silver Adapter Coverage

| Silver Table | Activity Family | Notes |
|-------------|-----------------|-------|
| `silver_campaign_touchpoint_facts` | campaign / web2 | channel determines family |
| `silver_web3_transaction_facts` | web3 | maps event_type to status |
| `silver_x402_flow_facts` | x402 | settled=True → confirmed |
| `silver_agent_execution_facts` | agent | outcome maps to status |
| `silver_identity_evidence_facts` | web2 | event_kind maps to activity_type |
| `silver_outcome_facts` | outcome | |
| `silver_revenue_facts` | commerce | gross_amount mapped |
| `silver_exposure_facts` | campaign | |
| `silver_account_activity_facts` | web2 | |
| `silver_comms_facts` | web2 | |
| `canonical_conversions` | commerce | type=conversion_{type} |
