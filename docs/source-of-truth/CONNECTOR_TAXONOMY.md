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
last_synced_commit: "pending"
estimated_read_minutes: 6
---

# Connector Taxonomy

> Every integration in Aether is classified by exactly one ConnectorClass and one
> ConnectorRole. These two dimensions, combined with the declared DataFlowDirection,
> determine what the platform is allowed to do with data the connector touches.
> Policy is enforced at connector registration time, not at ingestion time.

## Why a taxonomy?

A flat list of integrations becomes unmanageable. The taxonomy provides:

- A machine-readable classification that drives lake-write and graph-write policy.
- A governance audit anchor: every data grant references a connector's class and role.
- A filtering surface for UI (show only `OLYMPUS_PROVIDER` connectors, etc.).
- A training eligibility gate that prevents accidental model contamination.

---

## ConnectorClass

Describes the architectural role of the connector within the platform.

| Class | Meaning |
|---|---|
| `OLYMPUS_PROVIDER` | Aether-operated data provider (Dune, DeFiLlama, CoinGecko, etc.) |
| `TENANT_BYOD_DATA` | Tenant brings their own data to the lake |
| `BYOK_GATEWAY` | Tenant brings their own API key; Aether routes requests |
| `ACTION_NOTIFIER` | Outbound-only webhook or notification sink |
| `IDENTITY_BRIDGE` | Cross-system identity resolution (ENS, Farcaster, etc.) |
| `AGENT_TOOL` | Capability surface exposed to Aether agents |

---

## ConnectorRole

Describes the data function the connector performs.

| Role | Meaning |
|---|---|
| `HISTORICAL_ONCHAIN` | Historical blockchain data (blocks, txns, traces) |
| `REALTIME_MARKET` | Live price, order book, or funding rate feeds |
| `SOCIAL_SIGNAL` | Off-chain social and governance signals |
| `IDENTITY_RESOLUTION` | Entity linkage and identity graph enrichment |
| `DEX_DEFI` | DEX liquidity, protocol TVL, yield data |
| `PREDICTION_MARKET` | Prediction market odds and resolution data |
| `NOTIFICATION_SINK` | Outbound alert or webhook delivery |
| `AGENT_CAPABILITY` | Tools and actions available to agent layer |

---

## DataFlowDirection

| Direction | Meaning |
|---|---|
| `INBOUND` | Data flows into Aether (read from source) |
| `OUTBOUND` | Data flows out of Aether (write to destination) |
| `BIDIRECTIONAL` | Read and write; requires explicit policy on both paths |

---

## LakeWritePolicy

Controls whether connector-sourced data may be persisted to the Aether data lake.

| Policy | Meaning |
|---|---|
| `NEVER` | Data is never persisted; used in memory only |
| `OLYMPUS_BASELINE_ELIGIBLE` | May be written to the Olympus shared baseline lake |
| `TENANT_ONLY` | May be written only to the tenant's private partition |
| `PENDING_GRANT` | Blocked until an explicit DataRightsGrant is issued |

**Rule:** `ACTION_NOTIFIER` connectors always carry `NEVER`.
**Rule:** `BYOK_GATEWAY` connectors carry `NEVER` unless the tenant also holds a
separate `DataRightsGrant` covering the lake.

---

## GraphWritePolicy

Controls whether connector-sourced data may produce graph edges.

| Policy | Meaning |
|---|---|
| `ALLOWED` | Graph mutations are permitted with standard lineage attachment |
| `TENANT_GRAPH_ONLY` | Edges written only to the tenant's graph partition |
| `BLOCKED` | No graph mutations permitted |

---

## ModelTrainingEligibility

Declares whether connector data may be used to train or fine-tune Aether ML models.

| Value | Meaning |
|---|---|
| `ELIGIBLE` | Data from this connector may be used for training |
| `INELIGIBLE` | Data is explicitly excluded from training pipelines |
| `REQUIRES_GRANT` | Eligibility is conditional on an active DataRightsGrant |

**Default:** All `TENANT_BYOD_DATA` connectors are `INELIGIBLE` unless the tenant
grants training rights explicitly. `OLYMPUS_PROVIDER` connectors are `ELIGIBLE`
for Olympus-baseline models only.

---

## ImplementationStatus

| Status | Meaning |
|---|---|
| `ACTIVE` | Connector is live in production |
| `BETA` | Connector is available but not yet SLA-backed |
| `PLANNED` | Design exists; not yet implemented |
| `DISABLED_COMPLIANCE` | Deliberately disabled pending legal review |
| `DEPRECATED` | Being phased out; do not extend |

---

## PriorityPhase

Groups connectors into build waves.

| Phase | Meaning |
|---|---|
| `P1_FOUNDATION` | Core data backbone; must ship with MVP |
| `P2_ENRICHMENT` | Adds depth to foundation signals |
| `P3_DEPTH` | Specialized or compliance-gated sources |

---

## RiskTier

Reflects platform risk if the connector fails or is throttled.

| Tier | Meaning |
|---|---|
| `CRITICAL` | Outage degrades core product features |
| `HIGH` | Outage reduces signal quality significantly |
| `MEDIUM` | Outage causes minor feature gaps |
| `LOW` | Outage has no user-visible effect |

---

## Policy interaction summary

The combination of ConnectorClass, LakeWritePolicy, and ModelTrainingEligibility
defines what data flows where. No override mechanism exists below the class level;
grant additional rights via DataRightsGrant, not by changing class.

| ConnectorClass | LakeWritePolicy | ModelTrainingEligibility |
|---|---|---|
| `OLYMPUS_PROVIDER` | `OLYMPUS_BASELINE_ELIGIBLE` | `ELIGIBLE` |
| `TENANT_BYOD_DATA` | `TENANT_ONLY` | `INELIGIBLE` (default) |
| `BYOK_GATEWAY` | `NEVER` | `INELIGIBLE` |
| `ACTION_NOTIFIER` | `NEVER` | `INELIGIBLE` |
| `IDENTITY_BRIDGE` | `OLYMPUS_BASELINE_ELIGIBLE` | `REQUIRES_GRANT` |
| `AGENT_TOOL` | `NEVER` | `INELIGIBLE` |
