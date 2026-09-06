---
title: Financial Normalization — Architecture
slug: architecture/financial-normalization
section: architecture
visibility: I
audience: [architect, dev-senior, exec, compliance]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
estimated_read_minutes: 10
toc_depth: 3
---
# Financial Normalization — Architecture

This document is the source of truth for **Universal Financial Normalization**:
the data-driven platform capability through which Aether preserves exact native
financial facts, resolves them to namespace-safe canonical asset identity and
chain deployment, attaches immutable event-time valuations, supports multiple
reporting and display currencies, keeps unknown/unpriced explicit, and expands
through registry data rather than code.

Aether **observes and prices** value; it never custodies, settles, or executes.
That boundary is unchanged. What changes is that financial normalization becomes
a platform capability generalizing today's USD-first value contract
([FINANCIAL_VALUE_SEMANTICS.md](./FINANCIAL_VALUE_SEMANTICS.md)) and today's
stablecoin canonical registry into a universal, data-driven registry plus
event-time valuation engine.

Implementation status (as of the financial-normalization W1–W4a trunk): the
platform layers this architecture describes — the universal asset registry
(`services/assets`), the event-time valuation core with its append-only
persistence and API (`services/valuation`), and the registry → graph reference
projector (`services/assets/graph_projector.py`) — are **implemented** as
flag-gated **default-off** backend surfaces. Gating is explicit: the assets and
valuation routers mount in `main.py` only behind `settings.assets.api_enabled`
/ `settings.valuation.api_enabled` (both default false), writes additionally
require their `ingestion_enabled` flags, and the projector never runs at startup
— the seeder projects only when invoked with graph projection enabled
(`settings.assets.graph_enabled` / `AETHER_ASSETS_GRAPH_ENABLED`, default false).

The Phase-4 **rollup/display seam** is further along and is **additive rather
than flag-gated**: `services/value/rollups.py` `safe_rollup` is now
reporting-asset-keyed with a byte-identical `fiat:USD` default (a reporting
context adds a `reporting_totals` envelope; conversion to a non-USD reporting
asset is never guessed), and `ValuationService.reporting_asset_id_for` resolves
a tenant's reporting asset from `tenant_value_policies`. Per-domain ingestion
adapters and viewer-display convergence remain pending (Phases 4–5).

The **per-domain financial models** are a separate axis from these platform
layers. The migration-status ledger
([FINANCIAL_DOMAIN_MIGRATION_STATUS.md](./FINANCIAL_DOMAIN_MIGRATION_STATUS.md))
records honestly which domains are on the canonical model; those domains remain
LEGACY until the domain-migration waves land them. The phased program is
recorded in [Financial Normalization — Phased Implementation
Program](../plans/FINANCIAL_NORMALIZATION_PHASES.md).

Design vocabulary, used consistently across contracts, registries, migrations,
graph projections, and docs:

- Canonical asset ids: `fiat:USD`, `crypto:ETH`, `stablecoin:USDC`,
  `token:<chain>:<contract>`.
- Deployments: `deploy:<asset_id>@<chain>:<contract>`.
- Symbols (`"USDC"`, `"ETH"`) are **aliases**, never canonical identity.
- Legacy stablecoin ids (`"usdc"`, `"usdc:eip155:8453"`) are preserved via alias
  rows, never rewritten.

## 1. Canonical asset and fiat identity

Every asset has exactly one canonical identity in a namespace:

| Namespace | Canonical id | Examples |
| --- | --- | --- |
| Fiat | `fiat:<ISO-4217>` | `fiat:USD`, `fiat:EUR` |
| Crypto | `crypto:<symbol>` | `crypto:ETH`, `crypto:BTC` |
| Stablecoin | `stablecoin:<symbol>` | `stablecoin:USDC`, `stablecoin:USDT` |
| Token | `token:<chain>:<contract>` | a verified ERC-20/SPL address scoped by chain |

- The **fiat reference set** is the set of `fiat:*` registry rows, seeded from
  the ISO-4217 code list. It is data, not code, and is what a reporting policy
  chooses among.
- Symbols are aliases that **resolve** to a canonical id through the resolver;
  two different assets can never share a canonical id, and a symbol collision is
  resolved by namespace, never by overwrite.
- Canonical id ≠ symbol because a symbol names many assets (`USDC` on many
  chains, `USD` in many deployment systems). Identity must be stable while
  symbols, names, and issuer labels are changeable display properties. Nothing
  downstream keys on a symbol.

## 2. Deployments and chains

An asset exists once; it **deploys** many times.

- A deployment is chain-scoped: `deploy:<asset_id>@<chain>:<contract>`, where
  `chain` is a canonical chain namespace (e.g. `eip155:8453`) and `contract` is
  the verified contract or mint address on that chain.
- `deploy:*` is the unit of on-chain observation: balances, flows, prices, and
  valuations attach to a deployment, not to a bare asset id.
- **Canonical vs bridged:** a canonical deployment is the verified native
  deployment the registry trusts; a bridged/wrapped deployment records its
  origin deployment id and is never presented as canonical. This mirrors the
  stablecoin registry's `deployment_type` / `bridge_origin_deployment_id`
  distinction, generalized to all assets.
- **Chain lifecycle and deprecation** preserve history: a chain row can be
  suspended or deprecated, but its deployments and their historical valuations
  are never deleted or rewritten. Deprecation is additive state, so past
  reporting stays reproducible.

## 3. Legacy identity bridging

Existing records reference symbols and legacy ids. They are bridged, never
rewritten.

- Legacy stablecoin ids today (`"usdc"`, `"usdc:eip155:8453"`) and free-string
  currency/symbol values in older payloads map to canonical ids through **alias
  rows** in the registry (`alias → canonical_asset_id`, optionally scoped to a
  chain).
- Aliases are many-to-one: many legacy spellings can point at one canonical id;
  one legacy string never resolves to two canonical ids.
- Source records keep their original native fields; the resolver adds canonical
  identity as a projection. Normalization is additive so historical data and
  audit trails remain byte-for-byte what was observed.

## 4. Unknown and unresolved assets

Unknown assets are **explicit**, never guessed, never $0.

- When an observed symbol/address cannot be resolved, the record is stored
  **unresolved**: the native fact (amount + observed symbol/address) is kept, a
  canonical id is absent, and the event remains valid with `null` reporting
  valuation.
- An unresolved asset is never assigned a guessed canonical id, a guessed
  symbol, or a synthetic value. Resolution is allowed to arrive later (registry
  seed + alias), after which future records resolve; the earlier unresolved
  record is not retroactively mutated — a supersede link may note the later
  resolution.

## 5. Event-time valuation

Valuation is a snapshot attached to an event at a point in time, not a mutable
property of an asset or balance.

- Each value carries `value_at` (the point the value describes, e.g. the event
  time) alongside `effective_at` (when the snapshot is recorded/applies).
- **Valuation basis** names what the amount represents (market, FX, reported,
  peg) and the method that produced it.
- The **policy chain** is ordered and bounded:
  `provider_reported → venue_exec → primary_market → fx → oracle → fallback →
  unavailable`. An adapter walks the chain in order and stops at the first
  trusted source within its freshness window; if none applies the price status
  is `unavailable` and the reporting amount is `null`.
- Price statuses distinguish the outcome (`priced`, `stale`, `unpriced`,
  `conflicted`) from the method; a source that is unreachable yields
  **unpriced**, never zero.
- **Stablecoins are peg-aware.** A stablecoin is never assumed to equal its
  pegged asset at 1:1. Valuation uses observed peg status and source-backed
  price evidence (generalizing `stablecoin_peg_verified`), so a depegged or
  unverified stablecoin is not priced at par.

## 6. Immutability and corrections

- Valuation snapshots are **append-only**. A wrong or superseded valuation is
  corrected by appending a new snapshot with a **supersede pointer** to the one
  it replaces; the superseded snapshot remains readable and reproducible.
- Reproducibility is exact: every snapshot records the
  `registry_version`, `policy_version`, and `price_observation_ids` that
  produced it, so a snapshot can be re-derived or audited deterministically.
- **Registry versions are deterministic hashes**, not wall-clock timestamps: a
  registry state (asset/deployment/alias rows) hashes to a version string, and
  that version is what valuations cite. Two identical registry states always
  share one version.

## 7. Reporting vs display currencies

Reporting and display are separate axes, governed independently.

- A **tenant reporting policy** selects the tenant's reporting asset(s)
  (`fiat:USD` today, others as seeded). Reporting amounts — totals, rollups,
  statements, ledger output — are produced in the reporting asset.
- **Viewer display** is independent: an interface may display a value in any
  supported currency the viewer chooses, converted from the reporting asset or
  from native where a trustworthy valuation exists. Display conversion never
  changes the stored reporting amount.
- The USD-first invariants survive as the base case of this model: when the
  reporting asset is USD, behavior is identical to today's contract.

## 8. Rollup semantics

Rollups are the only place many values are combined, and they are strict.

- Totals are keyed by **reporting asset**: a rollup total is always expressed in
  one reporting asset, and `by_native_currency` preserves per-currency native
  amounts exactly as today's `safe_rollup` does.
- A **mixed-currency scalar sum is never produced.** Native values in different
  currencies are never added into one number unless each carries a trustworthy
  valuation in the reporting asset.
- Rollups report **coverage**: priced count, unpriced count, stale count,
  excluded count, and a status (`complete` / `partial` / `unavailable`), so a
  total is never silently partial.
- **Unknown ≠ 0.** An unpriced or unresolved value contributes no amount and is
  counted, not zeroed. `null` reporting amount and `"0"` are never conflated.

Implemented (W4a): `safe_rollup` in `services/value/rollups.py` accepts a
reporting context — `reporting_asset_id` plus an optional
`amount_in_reporting_asset` resolver — and returns an additive `reporting_totals`
envelope with priced/unpriced/excluded/stale counts, `coverage_percentage`, and
`rollup_status`. With no reporting context its output is byte-identical to the
USD-first contract; with a non-USD reporting asset the caller supplies the
resolver (e.g. backed by the valuation engine) or records count as
unpriced-for-reporting. `ValuationService.reporting_asset_id_for` resolves the
tenant reporting asset (default `fiat:USD`) for rollup/display entry points.

## 9. Graph projection

Canonical identity and valuation are projected onto the graph as **reference**
vertices and edges on a non-actor reference layer — never as actor/tenant
subject vertices.

- Reference vertices: canonical asset, deployment (per chain/contract), price
  observation/valuation snapshot, and their `registry_version` provenance.
- Reference edges: asset → deployment, deployment → valuation snapshot, alias →
  asset, bridged deployment → origin deployment, snapshot supersede links.
- **Tenant isolation is intact**: tenant-owned records reference these
  vertices by id but the reference layer itself is not tenant-mutable, and
  tenant-scoped traversals never leak across tenants.
- Projectors (registry → graph) are idempotent and versioned; re-running a
  projector against the same registry version reproduces the same graph state.

## 10. Registry lifecycle and expansion

Expansion is **data-driven**: adding an asset is a seed row, not a code change.

- The universal registry (asset, deployment, alias, fiat reference rows) is the
  single registration point. The existing stablecoin registry — x402-seeded and
  verified — is the **seed source** for the first stablecoin rows and the pattern
  the universal registry generalizes.
- Registry rows carry issuer/backing/decimals/asset-status metadata so pricing
  and display derive from data, not per-asset branches.
- Registry writes go through typed repositories and Alembic migrations like any
  canonical data; a seeded or operator-added row is versioned into the next
  deterministic `registry_version`.
- Chain metadata (canonical chain namespace, network, explorer) is registry
  data that deployments reference; nothing hardcodes a chain list in adapters.

## 10A. Registry admin + automated discovery

W5 (C5-ADMIN) adds a registry-admin facade and an automated-discovery
**skeleton** over the universal registry (`services/assets/admin.py`), served by
a global-ADMIN console (`/v1/admin/assets`, `services/assets/admin_routes.py`).

- **This is data-integrity scaffolding, observation-only.** The admin facade is
  a thin, permission-checked review-and-apply layer over the existing registry:
  register / alias / chain / fiat / deployment reference data and reference
  reads. Aether records canonical reference data; it NEVER originates, signs, or
  settles a transfer, and `execution_by_aether` stays False everywhere.
- **The discovery lifecycle is `unresolved → candidate → verified → active`.**
  *unresolved* = references the registry already records via
  `record_unresolved` (`registry_unresolved_asset_refs`); *candidate* = an
  unresolved reference a resolver seam (the stablecoin canonical-identity seam)
  can now plausibly map, surfaced as a *suggestion*; *verified* = a human /
  global-admin confirms the candidate; *active* = the verified mapping is
  applied as an alias/registration through the admin facade. Nothing auto-advances
  and nothing auto-writes: a candidate is never registered until a human applies it.
- **Honest scaffolding.** The pipeline lives entirely on existing tables
  (`registry_assets` / `registry_asset_aliases` / `registry_unresolved_asset_refs`)
  plus typed in-memory repositories under `AETHER_ENV=local` — no new migration.
  It produces suggested mappings for a human to review; it never fabricates
  identity, coerces or zeroes an unknown reference, or deletes the immutable
  unresolved observation.
- **Flag-gated OFF by default.** The console mounts only behind
  `settings.assets.admin_enabled` (`AETHER_ASSETS_ADMIN_ENABLED`, default
  false); every route is global-ADMIN gated, and write/apply routes additionally
  require the `admin_mode` apply capability (`AETHER_ASSETS_ADMIN_MODE`,
  default false).
- **Not lending / underwriting / execution behavior.** None of this adds a
  financial product, a credit decision, or an execution path; it is registry
  hygiene for mapping observed references to canonical identity under human
  review.

## 11. Conventions summary

| Concern | Convention |
| --- | --- |
| Asset identity | `fiat:*` / `crypto:*` / `stablecoin:*` / `token:<chain>:<contract>`; symbols are aliases |
| Deployment | `deploy:<asset_id>@<chain>:<contract>`; canonical vs bridged explicit |
| Legacy ids | Preserved via alias rows; never rewritten |
| Unknown asset | Recorded unresolved; canonical id absent; never guessed |
| Valuation | Immutable snapshot with `value_at`/`effective_at`, basis, policy chain, price observation ids |
| Stablecoin price | Peg-aware; never assumed 1:1 |
| Correctness | Append-only + supersede; reproducibility via registry/policy versions + observation ids |
| Rollups | Reporting-asset-keyed; no mixed-currency scalars; coverage counts; unknown ≠ 0 |
| Graph | Reference layer, non-actor; tenant isolation intact |
| Expansion | Seed registry rows; no per-asset code |
| Amounts | Decimal strings; never floats |

Related material:

- [Financial Value Semantics](./FINANCIAL_VALUE_SEMANTICS.md) — the USD-first
  value contract this architecture extends additively.
- [Financial Normalization — Phased Implementation
  Program](../plans/FINANCIAL_NORMALIZATION_PHASES.md) — gap analysis, phase
  map, and ledger.
- [Financial Domain Migration
  Status](./FINANCIAL_DOMAIN_MIGRATION_STATUS.md) — the per-domain output ledger.
