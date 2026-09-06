---
title: Connector Lake Policy
slug: architecture/connector-lake-policy
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: platform@aether
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/base.py
  - Backend Architecture/aether-backend/shared/integration_contracts/catalog.py
last_synced_commit: "8b1ca3dc"
estimated_read_minutes: 5
toc_depth: 3
---

# Connector Lake Policy

> Every connector class carries a declared default lake-write policy, graph-write
> policy, and model-training eligibility. These defaults are declared on the
> `ConnectorDescriptor` at registration time and enforced at descriptor/registration
> time — not at ingestion time. Elevating a policy requires a governance grant, not
> a connector-configuration change.

The authoritative enum definitions and the full class/role/policy reference live
in `CONNECTOR_TAXONOMY.md` (mirroring
`Backend Architecture/aether-backend/services/integrations/connectors/base.py`).
This document is the policy-interaction view: which default policy each class
carries, the dual-role rule, and how an elevation is governed. `DUAL_ROLE`
replaces the older conceptual `IDENTITY_BRIDGE`/`AGENT_TOOL` rows — those were
never `base.py` members; such surfaces are capabilities of a declared class, and
their policy is set on that class's descriptor, not on a phantom class.

## 1. Default write policy by connector class

The per-connector record is the source of truth (a `ConnectorDescriptor`), and
the shared default posture for tenant connectors is `TENANT_ONLY` lake /
`TENANT_GRAPH_ONLY` graph / `NEVER` training. Class docstrings encode the
intended defaults below.

| ConnectorClass | LakeWritePolicy (default) | GraphWritePolicy (default) | ModelTrainingEligibility (default) |
|---|---|---|---|
| `OLYMPUS_PROVIDER` | `OLYMPUS_BASELINE_ELIGIBLE` (provenance required; cleared = `OLYMPUS_BASELINE_ALLOWED`) | `OLYMPUS_GRAPH_ALLOWED` (lineage required) | `OLYMPUS_ALLOWED` for baseline models only |
| `TENANT_BYOD_DATA` | `TENANT_ONLY` | `TENANT_GRAPH_ONLY` | `NEVER` (tenant grants elevate) |
| `BYOK_GATEWAY` | `NEVER` (credential routing; no persistence) | `NONE` | `NEVER` |
| `ACTION_NOTIFIER` | `NEVER` (outbound-only; no inbound data) | `NONE` | `NEVER` |
| `DUAL_ROLE` | Most restrictive of its modeled capabilities (see §3) | Most restrictive of its modeled capabilities | Most restrictive of its modeled capabilities |

**Rule:** `ACTION_NOTIFIER` and `BYOK_GATEWAY` connectors carry `NEVER` lake
write. Any connector that both writes data and delivers notifications/actions
must model each as a separate capability (`ConnectorCapability`) or be split
into distinct registrations — never relax `NEVER` on an outbound/credential path.

**Rule:** data that has not cleared provenance/license review lands
`QUARANTINE_ONLY` (lake and graph) until review passes, rather than entering a
shared layer un-vetted.

## 2. What each policy means in practice

- `TENANT_ONLY` lake writes land in the tenant's private partition. Shared
  layers (cross-tenant analytics, Olympus-baseline pipelines, model training)
  cannot read this partition without an explicit tenant grant.
- `OLYMPUS_BASELINE_ELIGIBLE` permits Olympus-baseline writes only with
  provenance attached; `OLYMPUS_BASELINE_ALLOWED` is the post-review cleared
  state. `OLYMPUS_GRAPH_ALLOWED` writes edges with lineage.
- `QUARANTINE_ONLY` (lake and graph) means the data/edges are staged but not
  consumable until provenance/license review clears.
- Training eligibility is independent of lake policy: `NEVER`,
  `TENANT_ONLY` (tenant-scoped models), `AGGREGATE_ONLY` (aggregate, never raw),
  `OLYMPUS_ALLOWED` (baseline models), or `COMPLIANCE_REVIEW_REQUIRED`
  (conditional on review). Tenant BYOD data is `NEVER` until the tenant grants
  training rights.

## 3. Dual-role connectors

`DUAL_ROLE` connectors (e.g. Jira — ingest plus action) declare each capability
separately as a `ConnectorCapability` so lake/graph/training policy, grants, and
health stay isolated per capability.

**Most restrictive wins.** A connector whose capabilities span an
ingest-capable class and an action/credential-only class carries `NEVER` lake /
`NONE` graph on the action capability and the tenant/baseline policy only on the
ingest capability. This is intentional friction: a dual-role connector that
cannot be cleanly partitioned indicates an architectural boundary violation, and
the fix is two registrations/capabilities, not a relaxed policy.

## 4. Elevation is governed, not self-service

There is no self-service path for policy elevation. To elevate a connector's
declared lake/graph/training policy:

1. File a data-rights amendment referencing the provider/family identity and the
   desired policy change.
2. Compliance issues an amended grant covering the new use (see
   `DATA_RIGHTS_LEDGER.md` for the grant model).
3. The connector's descriptor policy fields are updated and an audit event is
   emitted.
4. Granting training rights additionally requires ML-governance sign-off.

Attempting to work around the policy by reclassifying a connector (changing its
class to dodge a `NEVER`) is a policy-enforcement alert.

## 5. Related docs

- `CONNECTOR_TAXONOMY.md` — full enum reference for the six-layer corpus model
  and the derived four-group customer catalog mirror.
- `DATA_RIGHTS_LEDGER.md` — grant model that governs policy elevations.
- `BYOK_PROVIDER_GATEWAY.md` — BYOK class and its `NEVER` default.
- `AETHER_END_USER_LIFECYCLE.md` — how the catalog mirrors into customer-facing
  experience grouping with an honest (dormant-by-default) posture.
