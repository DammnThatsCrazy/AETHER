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
last_synced_commit: "pending"
estimated_read_minutes: 5
---

# Connector Lake Policy

> Every connector class carries an immutable default lake write policy and graph
> write policy. These defaults are set at the class level and cannot be overridden
> by connector configuration alone. Changing a policy requires a DataRightsGrant
> amendment and a compliance review.

## Why immutable class-level defaults?

Individual connectors are numerous and frequently added. If each connector
required a bespoke policy decision, enforcement gaps would appear during rapid
integration work. Class-level defaults ensure that a new `ACTION_NOTIFIER`
connector is never accidentally permitted to write to the lake, even if the
engineer who built it did not think to check.

The connector class is set at registration time and cannot be changed without
migration through a formal connector deprecation cycle.

---

## Lake write policy by connector class

| ConnectorClass | LakeWritePolicy | Notes |
|---|---|---|
| `OLYMPUS_PROVIDER` | `OLYMPUS_BASELINE_ELIGIBLE` | Subject to provider-level DataRightsGrant |
| `TENANT_BYOD_DATA` | `TENANT_ONLY` | Data stays in tenant's lake partition |
| `BYOK_GATEWAY` | `NEVER` | Credential routing only; no persistence |
| `ACTION_NOTIFIER` | `NEVER` | Outbound-only; no inbound data |
| `IDENTITY_BRIDGE` | `OLYMPUS_BASELINE_ELIGIBLE` | Identity signals enter shared baseline |
| `AGENT_TOOL` | `NEVER` | Tool outputs are ephemeral context |

**Rule:** `ACTION_NOTIFIER` connectors must carry `NEVER`. The class is
outbound-only by definition. Any connector that writes data AND delivers
notifications must use a different class.

**Rule:** `BYOK_GATEWAY` connectors carry `NEVER` unless the tenant also holds
a separate DataRightsGrant with `lake_write_allowed=true`. That grant must be
reviewed and approved before the policy can be elevated.

---

## Graph write policy by connector class

| ConnectorClass | GraphWritePolicy | Notes |
|---|---|---|
| `OLYMPUS_PROVIDER` | `ALLOWED` | Edges enter Olympus graph with lineage |
| `TENANT_BYOD_DATA` | `TENANT_GRAPH_ONLY` | Edges isolated to tenant graph partition |
| `BYOK_GATEWAY` | `BLOCKED` | No graph mutations from BYOK paths |
| `ACTION_NOTIFIER` | `BLOCKED` | Outbound only; no graph side effects |
| `IDENTITY_BRIDGE` | `ALLOWED` | Identity edges enter shared graph |
| `AGENT_TOOL` | `BLOCKED` | Tool calls do not mutate the graph directly |

---

## Dual-role connectors

Some connectors serve more than one architectural role (e.g., a provider that
also delivers webhook notifications). When a connector would require two classes,
the following rule applies:

**Most restrictive policy wins.** If a connector handles both
`OLYMPUS_PROVIDER` (eligible for lake) and `ACTION_NOTIFIER` (never lake), the
lake write policy is `NEVER` until a deliberate architecture decision separates
the two functions into distinct connector registrations.

This is intentional friction. Dual-role connectors indicate an architectural
boundary violation. The correct fix is to register two connectors — one for
inbound provider data, one for outbound notifications — not to relax the policy.

---

## OLYMPUS_BASELINE_ELIGIBLE in practice

A connector with `LakeWritePolicy = OLYMPUS_BASELINE_ELIGIBLE` can write to the
Olympus shared lake partition, but only if:

1. A valid `DataRightsGrant` exists with `olympus_baseline_allowed=true` for the
   source slug.
2. The data has an `enrichment_lineage` record attached.
3. The write is idempotent (duplicate records are detected via lineage ID).

If any of these conditions is not met, the write is blocked and an
`enrichment.lake_write_blocked` audit event is emitted.

---

## TENANT_ONLY in practice

A connector with `LakeWritePolicy = TENANT_ONLY` writes to a partitioned
namespace within the lake:

```
s3://aether-{env}/{tenant_id}/byod/{source_slug}/{date}/
```

Olympus-baseline pipelines (model training, cross-tenant analytics, protocol
health) cannot read from this partition. The partition is visible only to:

- The tenant's own analytics queries.
- Aether support engineers with an explicit break-glass access record.
- Compliance exports scoped to the tenant.

---

## Policy change process

To elevate a connector's lake or graph write policy:

1. File a data rights amendment request referencing the connector slug and
   the desired policy change.
2. Compliance team issues an amended DataRightsGrant covering the new use.
3. The connector's policy record is updated and an audit event is emitted.
4. If `model_training_allowed` is being granted, a second sign-off from
   the ML governance lead is required.

There is no self-service path for policy elevation. Engineers who attempt to
work around the policy by reclassifying a connector will trigger a policy
enforcement alert.

---

## Related docs

- `CONNECTOR_TAXONOMY.md` — Full enum reference for all connector classes.
- `DATA_RIGHTS_LEDGER.md` — Grant model that governs policy elevations.
- `BYOK_PROVIDER_GATEWAY.md` — BYOK class and its NEVER default explained.
