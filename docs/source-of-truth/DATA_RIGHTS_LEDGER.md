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
estimated_read_minutes: 9
---

# Data Rights Ledger

> A DataRightsGrant is the authoritative record of what Aether is allowed to do
> with data from a specific source. No pipeline, model training job, or graph
> mutation may proceed without a valid grant covering the relevant data use.
> The platform is fail-closed: absence of a grant is a deny.

This ledger is the source-of-truth narrative for the `DataRightsGrant` authority
and reconciles it with the canonical Rights Authority blueprint
([RIGHTS_AUTHORITY_BLUEPRINT.md](./RIGHTS_AUTHORITY_BLUEPRINT.md)), which governs
the structured extension described below. The field table reflects the **real
Python model** (`services/integrations/data_rights/models.py`), presented as the
legacy boolean surface (today's authoritative field set) alongside the structured
nested view the blueprint adds.

## Why a rights ledger?

Data arrives from many sources: Olympus providers (Dune, DeFiLlama, etc.),
tenant-owned datasets, BYOK-routed provider calls, and identity bridges.
Each source has different contractual, regulatory, and consent constraints.

Without a ledger, data use rights exist only in engineers' heads or in scattered
contract PDFs. The ledger makes rights machine-readable and enforceable.

---

## DataRightsGrant model — legacy boolean surface (authoritative today)

Each grant record covers the intersection of one data source and one set of
permitted uses. Field names below match `models.py`.

| Field | Type | Description |
|---|---|---|
| `data_rights_grant_id` | string | Immutable identifier for this grant (issued as `drg_…`) |
| `tenant_id` | string or `OLYMPUS` | Scope: tenant-specific or platform-wide |
| `contract_id` | string or null | Optional governing contract/MSA reference |
| `source_id` | string | Provider/source slug (e.g., `dune`, `tenant_byod`) |
| `connector_id` | string | The connector instance that routed the source |
| `connector_class` | string | `olympus_provider` / `tenant_byod_data` / `byok_gateway` / … drives defaults |
| `source_manifest_id` | string or null | Optional source-manifest reference |
| `data_category` | string | High-level category of the data |
| `data_sensitivity` | string | Sensitivity classification (default `unclassified`) |
| `raw_data_owner` | string | Principal that owns the contributed raw data |
| `tenant_lake_allowed` | boolean | May data be written to the tenant lake? (default `true`) |
| `tenant_graph_allowed` | boolean | May data produce edges in the tenant graph? (default `true`) |
| `tenant_insights_allowed` | boolean | May data feed tenant-scoped insights/computation? (default `true`) |
| `olympus_baseline_allowed` | boolean | May data enter the Olympus shared baseline? (default `false`) |
| `cross_tenant_aggregate_allowed` | boolean | May data be used in cross-tenant aggregates? (default `false`) |
| `model_training_allowed` | boolean | May data be used for model training? (default `false`) |
| `commercial_reuse_allowed` | boolean | May data be reused commercially? (default `false`) |
| `legal_basis` | enum | `legitimate_interest` / `contract` / `consent` / `legal_obligation` / `vital_interests` / `public_task` / `operator_policy` |
| `consent_basis` | string or null | Consent purpose reference when legal basis is consent |
| `granted_by_user_id` | string | Principal who issued the grant (user/service id) |
| `granted_at` | timestamp | When the grant was issued |
| `expires_at` | timestamp or null | Null means no expiry; explicit expiry preferred |
| `revoked_at` | timestamp or null | If set, grant is revoked as of this timestamp |
| `revocation_reason` | string or null | Human-readable reason for revocation |
| `status` | enum | `active` / `revoked` / `expired` / `pending_review` / `suspended` |
| `audit_event_id` | string | Append-only audit reference for the grant's lifecycle |

> Every boolean defaults to `false` except the tenant-partition uses
> (`tenant_lake_allowed`, `tenant_graph_allowed`, `tenant_insights_allowed`,
> which default `true` so tenant BYOD data is usable in the tenant's own
> partition). All cross-boundary uses (`olympus_baseline`,
> `cross_tenant_aggregate`, `model_training`, `commercial_reuse`) default
> `false` — an explicit grant is required.

---

## Structured rights contracts (blueprint §3 — planned canonical view)

The blueprint upgrades `DataRightsGrant` from source-data booleans into a
**structured rights contract** via nested governed components (no dozens of
unrelated top-level booleans). The nested components are the planned canonical
form; the legacy booleans above remain authoritative and the migration must
**not broaden** any right.

| Nested component | Replaces / organizes today's | Meaning |
|---|---|---|
| `source_use: SourceUseAuthority` | `tenant_lake_allowed`, `tenant_graph_allowed`, `tenant_insights_allowed`, `olympus_baseline_allowed`, `cross_tenant_aggregate_allowed`, `commercial_reuse_allowed` | Where the tenant's contributed data may be used (tenant lake / tenant graph / tenant insights / Olympus baseline / cross-tenant aggregate / commercial reuse). Migrates existing booleans with **no semantic change** (§3.1) |
| `generated_output_rights: GeneratedOutputRights` | (new — Olympus-strengthening) | Who holds proprietary rights in Aether-generated output, the tenant's governed license, what Olympus may retain/analyze/derive, external disclosure limits, and survival of exported/generalized artifacts (§3.2) |
| `learning_authority: LearningAuthority` | `model_training_allowed` | The nine learning classes (inference … contributed model training … Olympus internal intelligence). See Learning classes below (§3.3) |
| `disclosure_authority: DisclosureAuthority` | (cross-tenant boundary logic) | Tenant-internal / Olympus-internal / cross-tenant-identifiable / external-identifiable / generalized boundaries (§3.4) |
| `retention_authority: RetentionAuthority` | (retention cross-check) | Governed retention inputs; effective retention is resolved by deterministic precedence (§3.5, §9) |
| `termination_authority: TerminationAuthority` | (today's hard-delete assumption) | Rights-aware lifecycle treatment per artifact kind on termination — contributed data, derived data, exports, audit records, generalized derivatives, model weights, benchmarks, ontology, security signatures (§3.5) |

Blueprint §3 defaults, in plain terms: a tenant's contributed data is usable in
its own partition; the **Olympus baseline is not** a default; **cross-tenant
aggregation is not** a default; **model training is not** a default. Aether
retains proprietary rights in the Aether-generated computational artifact while
the tenant receives broad governed rights to use the result for its own business.
Tenant ownership of contributed information does **not** automatically create
ownership of every intelligence artifact Aether generates (blueprint §1.2).

The structured contracts are implementing in this session per the blueprint —
treat the nested components above as the planned canonical form until they land
in the model; the legacy surface is what is enforced today.

---

## Intelligence Rights Profiles (blueprint §3.6)

A profile is a **policy preset** over the structured contracts — never a
different code path. It expresses how a tenant's information is treated across
generated-output retention, learning, Olympus internal intelligence, and
contributed training.

| Profile | Olympus generated-output retention | Generalized learning | Olympus internal intelligence | Contributed training |
|---|---:|---:|---:|---:|
| **Sovereign** | Minimal | No | No | No |
| **Private** | Required operations only | No or limited | No | No |
| **Standard** | Yes | Yes | Yes, bounded | No |
| **Collaborative** | Yes | Yes | Yes | Explicitly governed |

The profile enum (`IntelligenceRightsProfile`) is part of the planned canonical
vocabulary (see [RIGHTS_TAXONOMY.md](./RIGHTS_TAXONOMY.md)); the Effective Rights
Resolver composes a tenant's profile with the grant, consent, and policy inputs
to produce each decision.

---

## Learning classes and the migration rule

The single `model_training_allowed` boolean becomes one of **nine learning
authorities** (blueprint §3.3):

`inference`, `tenant_adaptation`, `generalized_learning`, `resolver_calibration`,
`ontology_learning`, `schema_mapping_learning`, `benchmarking`,
`contributed_model_training`, `olympus_internal_intelligence`.

**Migration rule — never broadens.** On migration, `model_training_allowed`
maps **only** to `contributed_model_training`; it never implies any other
learning class. A tenant may allow generalized learning while refusing
raw-data model training. Every other learning authority resolves from policy
defaults / tenant rights profile / agreement / data class / source class /
legal restrictions, and absence stays fail-closed. This migration is the machine
representation of the commercial doctrine (blueprint §1.2): tenant ownership of
contributed information does not confer ownership of, or default training rights
over, Aether-generated intelligence.

---

## Canonical vocabulary

- [RIGHTS_TAXONOMY.md](./RIGHTS_TAXONOMY.md) — the four-class information
  taxonomy (Contributed / Canonicalized / Aether Generated / Generalized) and a
  vocabulary reference for the canonical enums.
- [RIGHTS_AUTHORITY_BLUEPRINT.md](./RIGHTS_AUTHORITY_BLUEPRINT.md) — the frozen,
  in-repo implementation contract for the structured extension, the Effective
  Rights Resolver, the Generalization Gateway, retention/termination resolution,
  and the Olympus internal actor/purpose model.

---

## Effective Rights Resolver (planned composition authority)

`DataRightsService` remains the **fail-closed grant ledger** and gatekeeper at
lake/graph/training/baseline entry points. The blueprint adds an **Effective
Rights Resolver** (`services/rights_authority/`) that composes each grant with
`ConsentPolicyDecision`, the tenant's Intelligence Rights Profile, retention
policy, legal hold, residency, and temporal effective date into a **durable,
immutable, versioned `RightsDecision`** (`rdec_…`) recorded in the
`rights_decisions` store (blueprint §4). Every material authorization — store,
normalize, graph mutation, derived intelligence, export, disclose, train,
generalize, enter the Olympus graph, Olympus-internal query, retain after
termination — produces such a decision.

Status: the resolver's composition wiring and durable `rdec_*` decision records
are the blueprint's M2 canonical-resolver milestone (Phase 2). They are
**declared per the blueprint and implementing; not yet the enforced path** in
this ledger. Until they land, legacy `check_policy`/`can_use_*` grant checks
remain the enforcement surface, and the legacy booleans above remain
authoritative (fail-closed).

---

## Fail-closed policy

The platform enforces grants at pipeline entry points. The rules are:

1. **No grant = deny.** If no matching grant exists for `(source_id, data_use)`,
   the operation is blocked. There is no fallback to a permissive default.
2. **Expired grants = deny.** A grant past its `expires_at` is treated as absent.
3. **Revoked grants = deny immediately.** Revocation takes effect at `revoked_at`,
   retroactively flagging records that entered the lake under the revoked grant.
4. **Partial grants are respected.** A grant with `tenant_lake_allowed=true` and
   `model_training_allowed=false` permits tenant-lake writes but blocks training
   pipelines. The structured contracts keep this rule: e.g. a `LearningAuthority`
   that grants `generalized_learning` while withholding
   `contributed_model_training` permits the former and blocks the latter.

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
`BYOK_PROVIDER_GATEWAY.md` for the credential model. (In `DataRightsService`,
`byok_gateway` connector_class grants force `tenant_lake_allowed=false` and
`tenant_graph_allowed=false`.)

---

## Tenant BYOD defaults

When a tenant registers a dataset via the BYOD (Bring Your Own Data) pathway,
the following defaults apply automatically:

| Field | Default | Rationale |
|---|---|---|
| `tenant_lake_allowed` | `true` | Tenant explicitly submitted this data to the lake |
| `tenant_graph_allowed` | `true` | Graph edges within tenant graph only |
| `tenant_insights_allowed` | `true` | Tenant-scoped insights over its own data |
| `olympus_baseline_allowed` | `false` | Tenant data stays in tenant partition |
| `cross_tenant_aggregate_allowed` | `false` | No cross-tenant aggregation by default |
| `model_training_allowed` | `false` | Training rights require explicit opt-in |
| `commercial_reuse_allowed` | `false` | No commercial reuse by default |

A tenant may upgrade their BYOD grant to allow `olympus_baseline_allowed=true`,
`model_training_allowed=true`, or `cross_tenant_aggregate_allowed=true` through
the self-service grant upgrade flow, which logs a grant amendment and requires
re-attestation of data provenance.

---

## Olympus provider defaults

For data sourced from Olympus providers (e.g., Dune, DeFiLlama, CoinGecko),
the platform-level grant that covers the provider contract establishes:

| Field | Default | Rationale |
|---|---|---|
| `tenant_lake_allowed` | `true` | Provider data enters Olympus lake |
| `tenant_graph_allowed` | `true` | Graph edges in Olympus graph layer |
| `tenant_insights_allowed` | `true` | Insights over the source |
| `olympus_baseline_allowed` | `true` | Data contributes to shared baseline |
| `cross_tenant_aggregate_allowed` | `false` | Aggregation requires an explicit grant |
| `model_training_allowed` | `false` | Training rights are a separate contract |
| `commercial_reuse_allowed` | `false` | Reuse requires an explicit grant |

Training rights for Olympus provider data require a separate legal review and
a specific grant with `model_training_allowed=true`. Do not assume that a
provider contract covering data access also covers model training.
`DataRightsService` enforces the provider overrides at creation: for
`connector_class == "olympus_provider"`, `olympus_baseline_allowed` is set `true`
and `model_training_allowed` cannot be set directly via the API (it requires the
compliance-review flow).

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

- `RIGHTS_AUTHORITY_BLUEPRINT.md` — Canonical implementation contract: structured
  contracts, Intelligence Rights Profiles, Effective Rights Resolver,
  Generalization Gateway, retention/termination resolution.
- `RIGHTS_TAXONOMY.md` — Four-class information taxonomy + canonical vocabulary
  reference.
- `IRRL_NAMING_OVERLAY.md` — Label map for the `rights_irrl` spine over this ledger.
- `BYOK_PROVIDER_GATEWAY.md` — Why BYOK is not a data rights grant.
- `CONNECTOR_LAKE_POLICY.md` — Per-connector defaults that flow from grants.
- `ENRICHMENT_LINEAGE.md` — How lineage_id links records back to grants.
- `GRAPH_OF_GRAPHS_DATA_USE.md` — Cross-graph data use rules.
