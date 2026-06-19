---
title: Data Rights Ledger
slug: architecture/data-rights-ledger
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: compliance@aether
source_files:
  - Backend Architecture/aether-backend/services/integrations/data_rights/models.py
  - Backend Architecture/aether-backend/services/integrations/data_rights/service.py
last_synced_commit: "pending"
estimated_read_minutes: 7
---

# Data Rights Ledger

> A DataRightsGrant is the authoritative record of what Aether is allowed to do
> with data from a specific source. No pipeline, model training job, or graph
> mutation may proceed without a valid grant covering the relevant data use.
> The platform is fail-closed: absence of a grant is a deny.

## Why a rights ledger?

Data arrives from many sources: Olympus providers (Dune, DeFiLlama, etc.),
tenant-owned datasets, BYOK-routed provider calls, and identity bridges.
Each source has different contractual, regulatory, and consent constraints.

Without a ledger, data use rights exist only in engineers' heads or in scattered
contract PDFs. The ledger makes rights machine-readable and enforceable.

---

## DataRightsGrant model

Each grant record covers the intersection of one data source and one set of
permitted uses.

| Field | Type | Description |
|---|---|---|
| `grant_id` | UUID | Immutable identifier for this grant |
| `tenant_id` | string or `OLYMPUS` | Scope: tenant-specific or platform-wide |
| `source_slug` | string | Provider slug (e.g., `dune`, `tenant_byod`) |
| `granted_by` | string | Principal who issued the grant (email or service) |
| `granted_at` | timestamp | When the grant was issued |
| `expires_at` | timestamp or null | Null means no expiry; explicit expiry preferred |
| `lake_write_allowed` | boolean | May data be written to the data lake? |
| `olympus_baseline_allowed` | boolean | May data enter the Olympus shared baseline? |
| `graph_write_allowed` | boolean | May data produce graph edges? |
| `model_training_allowed` | boolean | May data be used for model training? |
| `revoked_at` | timestamp or null | If set, grant is revoked as of this timestamp |
| `revocation_reason` | string or null | Human-readable reason for revocation |
| `audit_events` | array | Append-only log of grant lifecycle events |

---

## Fail-closed policy

The platform enforces grants at pipeline entry points. The rules are:

1. **No grant = deny.** If no matching grant exists for `(source_slug, data_use)`,
   the operation is blocked. There is no fallback to a permissive default.
2. **Expired grants = deny.** A grant past its `expires_at` is treated as absent.
3. **Revoked grants = deny immediately.** Revocation takes effect at `revoked_at`,
   retroactively flagging records that entered the lake under the revoked grant.
4. **Partial grants are respected.** A grant with `lake_write_allowed=true` and
   `model_training_allowed=false` permits lake writes but blocks training pipelines.

---

## BYOK is not a data rights grant

A common misconception: tenants who bring their own API keys (BYOK) sometimes
assume this gives them data ownership rights within the Aether platform. It does
not.

BYOK grants the tenant **credential control** — they manage the API key, and
Aether routes requests through it. BYOK does not grant:

- Permission to write data to the Aether lake under the Olympus baseline.
- Permission to use the data for Aether model training.
- Any transfer of the provider's data licensing rights.

If a tenant wants lake or training rights for BYOK-routed data, they must hold
a separate DataRightsGrant that explicitly covers those uses. See
`BYOK_PROVIDER_GATEWAY.md` for the credential model.

---

## Tenant BYOD defaults

When a tenant registers a dataset via the BYOD (Bring Your Own Data) pathway,
the following defaults apply automatically:

| Field | Default | Rationale |
|---|---|---|
| `lake_write_allowed` | `true` | Tenant explicitly submitted this data to the lake |
| `olympus_baseline_allowed` | `false` | Tenant data stays in tenant partition |
| `graph_write_allowed` | `true` | Graph edges within tenant graph only |
| `model_training_allowed` | `false` | Training rights require explicit opt-in |

A tenant may upgrade their BYOD grant to allow `olympus_baseline_allowed=true`
or `model_training_allowed=true` through the self-service grant upgrade flow,
which logs a grant amendment and requires re-attestation of data provenance.

---

## Olympus provider defaults

For data sourced from Olympus providers (e.g., Dune, DeFiLlama, CoinGecko),
the platform-level grant that covers the provider contract establishes:

| Field | Default | Rationale |
|---|---|---|
| `lake_write_allowed` | `true` | Provider data enters Olympus lake |
| `olympus_baseline_allowed` | `true` | Data contributes to shared baseline |
| `graph_write_allowed` | `true` | Graph edges in Olympus graph layer |
| `model_training_allowed` | `false` | Training rights are a separate contract |

Training rights for Olympus provider data require a separate legal review and
a specific grant with `model_training_allowed=true`. Do not assume that a
provider contract covering data access also covers model training.

---

## Grant lifecycle events

Every grant emits the following audit events:

| Event | Trigger |
|---|---|
| `grant.created` | Initial grant issuance |
| `grant.amended` | Any field updated (must log previous value) |
| `grant.expired` | Automatic at `expires_at` |
| `grant.revoked` | Manual revocation with reason |
| `grant.lineage_scrubbed` | Records written under this grant flagged/removed |

These events are written to the immutable audit log and cannot be deleted or
amended. Revocation triggers an async job to flag all lake records whose
`lineage_id` traces back to the revoked grant.

---

## Related docs

- `BYOK_PROVIDER_GATEWAY.md` — Why BYOK is not a data rights grant.
- `CONNECTOR_LAKE_POLICY.md` — Per-connector defaults that flow from grants.
- `ENRICHMENT_LINEAGE.md` — How lineage_id links records back to grants.
- `GRAPH_OF_GRAPHS_DATA_USE.md` — Cross-graph data use rules.
