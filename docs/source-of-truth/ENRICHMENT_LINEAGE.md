---
title: Enrichment Lineage
slug: architecture/enrichment-lineage
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: platform@aether
source_files:
  - Backend Architecture/aether-backend/services/provider_catalog/models.py
  - Backend Architecture/aether-backend/repositories/lake.py
last_synced_commit: "pending"
estimated_read_minutes: 5
---

# Enrichment Lineage

> Every record in the Aether data lake that derives from an external provider
> must carry an `enrichment_lineage` attachment. This lineage record enables
> rights revocation, compliance audit, and model training provenance tracking.
> It is not optional; a lake write without lineage is rejected.

## Why lineage is mandatory

Data rights can be revoked. When a provider's data rights grant is revoked —
because a contract expired, a regulatory obligation changed, or the tenant
withdrew consent — Aether must be able to identify and flag every record in the
lake that traces back to that grant. Without a lineage record on every
enriched artifact, that rollback is impossible.

Lineage also answers the question: "Was this model trained on data we are still
allowed to use?" The answer requires a lineage chain from the model training run
back to the original provider grants.

---

## EnrichmentLineage model

| Field | Type | Description |
|---|---|---|
| `lineage_id` | UUID | Immutable identifier for this lineage record |
| `source_slug` | string | Provider slug (e.g., `dune`, `coingecko`) |
| `grant_id` | UUID | DataRightsGrant that authorized this enrichment |
| `connector_class` | string | ConnectorClass of the source connector |
| `query_ref` | string or null | Provider-specific query ID (e.g., Dune query_id) |
| `execution_id` | string or null | Provider execution reference (for audit) |
| `extracted_at` | timestamp | When the data was extracted from the provider |
| `block_range` | object or null | `{from_block, to_block}` for on-chain extractions |
| `schema_version` | string | Version of the extraction schema used |
| `tenant_id` | string or `OLYMPUS` | Scope of this enrichment |

---

## Where lineage is attached

Lineage records are attached at point of write, not point of consumption.
The following output types require a `lineage_id` on every record:

| Output type | Attachment point |
|---|---|
| Gold lake records | `enrichment_lineage_id` column |
| Profile 360 outputs | `lineage_ids[]` array in the profile blob |
| Graph edges | `lineage_event_ids[]` property on edge |
| Model training records | `source_lineage_ids[]` in the training job manifest |
| Wallet enrichment responses | `lineage_id` in the API response metadata |

---

## Lineage chain for model training

When a model training job runs, it produces a training manifest that lists:

1. Every dataset partition consumed.
2. The `lineage_id` for each enriched record in those partitions.
3. The `grant_id` behind each lineage ID.

The ML governance system validates that all referenced grants are:
- Currently active (not expired or revoked).
- Carrying `model_training_allowed=true`.

A training job that references even one revoked grant is blocked. The manifest
is stored immutably alongside the model artifact.

---

## Revocation propagation

When a DataRightsGrant is revoked, the following happens:

1. An async `lineage_scrub` job is triggered.
2. The job queries the lake for all records where `enrichment_lineage_id`
   traces to the revoked `grant_id`.
3. Each affected record is marked `DATA_RIGHTS_REVOKED` in place.
4. Profile 360 objects that included the affected lineage IDs are invalidated
   and queued for recomputation without the revoked data.
5. Graph edges with the revoked lineage in `lineage_event_ids[]` are flagged;
   downstream graph queries filter flagged edges by default.
6. Model training jobs whose manifests reference the revoked grant are marked
   `LINEAGE_TAINTED` in the model registry.

This process is asynchronous and may take minutes to hours for large datasets.
During propagation, affected records serve a `lineage_status: PENDING_SCRUB`
flag on API responses.

---

## Lineage for tenant BYOD data

Tenant BYOD data also carries lineage, but the `grant_id` references the
tenant's own BYOD registration grant rather than an Olympus provider grant.
This enables the same revocation mechanics if a tenant withdraws a dataset.

---

## Duplicate detection

Lineage IDs are used to enforce idempotent lake writes. If a write is attempted
with a `lineage_id` that already exists in the lake, the write is a no-op and
the existing record is returned. This prevents double-counting in analytics
queries and ensures extraction retries are safe.

---

## Related docs

- `DATA_RIGHTS_LEDGER.md` — Grant model that lineage records reference.
- `DUNE_ACCESS_MODES.md` — How Dune extractions attach lineage.
- `GRAPH_OF_GRAPHS_DATA_USE.md` — Cross-graph edge lineage requirements.
- `SOURCE_TO_MODEL_MATRIX.md` — Model training lineage requirements.
