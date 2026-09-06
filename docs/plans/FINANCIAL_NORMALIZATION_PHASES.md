---
title: Financial Normalization — Phased Implementation Program
slug: plans/financial-normalization-phases
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
---
# Financial Normalization — Phased Implementation Program

This is the implementation program for **Universal Financial Normalization**: the
data-driven platform capability described in
[docs/source-of-truth/FINANCIAL_NORMALIZATION.md](../source-of-truth/FINANCIAL_NORMALIZATION.md).
That document is the architecture source of truth; this document records the gap
between the repository and that architecture, orders the work into phases, and
is the ledger for what has shipped.

The program makes financial normalization a data-driven platform capability:
preserve exact native facts, resolve to namespace-safe canonical asset identity
and chain deployment, attach immutable event-time valuations, support multiple
reporting and display currencies, keep unknown/unpriced explicit, and drive
expansion through registry data rather than code. It reuses and generalizes
`AetherValue`, the stablecoin registry pattern, typed repositories, Alembic, and
the graph. No phase has shipped yet — implementation begins with this program.

Completion of the whole program is gated by the repository's canonical gate
(`make ci-check`), not by this document. The domain-by-domain migration ledger
lives in
[docs/source-of-truth/FINANCIAL_DOMAIN_MIGRATION_STATUS.md](../source-of-truth/FINANCIAL_DOMAIN_MIGRATION_STATUS.md).

## 1. Gap analysis

The repository already has a USD-first value contract, a value/valuation service
layer, a stablecoin canonical registry, and a graph. The gaps against the target
architecture are the single-currency assumption, symbol-as-identity, hardcoded
support sets, a stablecoin-only registry, raw number payloads on some surfaces,
and the absence of first-class asset graph vertices.

| Area | Repository state before this program | Gap to the target architecture |
| --- | --- | --- |
| Value contract | A single USD-first `USDValuation` (`usd_value`) is the only reporting valuation; USD is the implicit reporting asset | **Single-currency value contract** — the contract must become reporting-asset-agnostic while preserving every USD-first invariant (null reporting amount is never 0; no mixed-currency scalar sums; native preserved) |
| Currency identity | `NativeValue.currency` is a bare string (`"USD"`, `"ETH"`, `"USDC"`) — no namespace, no canonical identity, symbol conflated with identity | **Symbol-string currency** — replace free-string currency/symbol with namespace-safe canonical ids (`fiat:USD`, `crypto:ETH`, `stablecoin:USDC`, `token:<chain>:<contract>`); symbols become aliases, never canonical identity |
| Symbol support sets | Supported asset/fiat sets are hardcoded — the stablecoin registry is seeded from an in-code x402 `_ASSET_CONTRACT` set; fiat handling lives in price-source code | **Hardcoded symbol support sets** — adding an asset must be a registry seed row, not a code change; resolution, pricing, and display expand from registry data |
| Canonical registry | The stablecoin registry is today's only canonical asset + deployment registry (x402-seeded, stablecoin-only; `canonical_asset_id` is `symbol.lower()`) | **Stablecoin-only canonical registry** — generalize the registry pattern to a universal asset + deployment registry covering fiat, crypto, stablecoin, and token assets across chains, reusing the stablecoin registry as the seed source |
| Amount payloads | `amount` is a decimal string in the canonical value contract, but several financial surfaces still carry raw `amount: number` payloads | **amount:number payloads** — every surface must land on decimal-string canonical value envelopes (native preserved) with typed repositories |
| Float persistence risk | Rollups historically summed raw `float(amount)` across currencies, producing mixed-currency scalars (Profile360 financials was a release blocker) and risking float persistence | **Float persistence risk** — no float persistence; safe-rollup semantics generalize so totals are reporting-asset-keyed and a mixed-currency scalar is never produced |
| Asset graph | No first-class graph vertices/edges for canonical asset identity, deployment, or valuation relationships | **No first-class asset graph vertices** — project canonical assets, deployments, and valuations as reference vertices/edges on a non-actor reference layer |

## 2. Phase map

Phases are ordered so contracts, registry, and valuation land before any domain
migrates onto the engine. Every phase below is **NOT YET SHIPPED**; the ledger in
section 4 is updated as each phase lands.

| Phase | What ships | Entry criteria | Exit criteria | Status |
| --- | --- | --- | --- | --- |
| **1** — Universal contracts + kickoff docs | Namespace-safe canonical identity/deployment ids and symbol-as-alias restated in the shared value contract and its `services/value` mirror; event-time valuation and reporting-asset-agnostic invariants added additively; this plan, the architecture source of truth, and the migration-status ledger | Architecture doc reviewed; program scope approved | Value contract expresses canonical ids and reporting-asset-agnostic invariants without weakening existing USD-first rules; docs consistent | NOT YET SHIPPED |
| **2** — Registries + resolver + migration A | Universal asset + deployment registry tables and typed repos generalizing the stablecoin registry pattern; migration A (canonical asset, deployment, alias tables); resolver maps legacy ids and symbol strings to canonical ids; alias rows preserve legacy stablecoin ids (`"usdc"`, `"usdc:eip155:8453"`) — never rewritten | Phase 1 landed; registry schema agreed with the stablecoin seed source | Assets and deployments resolve to canonical ids; legacy ids resolve through alias rows unchanged; registry versions are deterministic hashes, not wall-clock | IN PROGRESS — registry trunk landed (migration A, typed repos, seeds, resolver, facade, `/v1/assets` routes flag-gated) |
| **3** — Event-time valuation (migration B) + graph reference surface + projectors | Append-only event-time valuation snapshots (`value_at` at `effective_at`, valuation basis, policy chain, price observation ids) via migration B; graph reference vertices/edges for canonical assets, deployments, and valuations on a non-actor reference layer; projectors from registry into the graph | Phase 2 landed | Valuation snapshots are immutable and reproducible from `registry_version`/`policy_version`/`price_observation_ids`; stablecoin valuation is peg-aware (never a $1 assumption); reference graph surface live with tenant isolation intact | IN PROGRESS — graph reference surface landed; valuation engine core landed; W3 landed migration B persistence + `/v1/valuation` routes + the registry→graph reference projector (all flag-gated default OFF); valuation-snapshot vertex/edge projection and domain convergence pending |
| **4** — Ingestion adapters + safe-rollup generalization + tenant policies + frontend display | Ingestion adapters attach canonical identity and event-time valuations at write time; generalized safe rollup is reporting-asset-keyed with coverage/priced counts and unknown ≠ 0; tenant reporting policies independent of viewer display; frontend displays canonical reporting asset with native drilldown | Phase 3 landed | Adapters emit canonical records end-to-end; a tenant reporting currency can differ from a viewer display currency; display contract generalized through the shared value components | IN PROGRESS — W4a landed the shared rollup/display seam (reporting-asset-keyed `safe_rollup`, byte-identical `fiat:USD` default; `ValuationService.reporting_asset_id_for` tenant policy resolver; TS `RollupResult` additive fields); W4b landed per-domain Phase-4 hardening + additive read seams across six domains (card-linked, agent-cost, stablecoin canonical-identity read seam, profile360 on the reporting seam, commerce metering, x402 decimal money — all Decimal money, wire/spec surface unchanged); full per-domain convergence is Phase 5 |
| **5** — Domain migration convergence | Migrate financial domains onto the normalized engine in convergence order: commerce → e-commerce → unified financial profile → payment rails → wallet → x402 → card-linked → stablecoin convergence → derivatives → campaign/attribution/LTV → agent cost | Phase 4 landed; the engine is stable | Each converged domain's records resolve to canonical ids, carry event-time valuations, and gain reference graph edges; migration-status ledger rows move LEGACY → PARTIAL → CANONICAL as each lands | NOT YET SHIPPED |
| **6** — CI validator + tests + admin/discovery + release | CI validator enforcing canonical-id hygiene, alias preservation, no mixed-currency sums, unknown ≠ 0, peg-aware stablecoin handling; migration and property tests; admin/discovery surfaces for registry and valuations | Phase 5 domains landed; validator scope agreed | Validator green across the repo; `make release-gate` green for the normalized financial surfaces; docs synced | IN PROGRESS — C5-VALIDATOR gate landed (repo-doctor #44, `scripts/validate_universal_financial_assets.py`); C5-ADMIN operator console + automated-discovery skeleton landed (flag-gated OFF); final `make ci-check` pending |

### Implementation priority

Contracts and registry data come first; value semantics come before the graph;
domain convergence comes last.

- **Phase 1 first** because every later phase consumes the canonical identity,
  deployment, and event-time valuation vocabulary. Locking the vocabulary before
  registry tables or domain migrations avoids rewriting either.
- **Registry (Phase 2) before valuation (Phase 3)** because a valuation must
  reference a canonical asset and deployment; event-time valuation tables attach
  to resolvable ids, never to symbols.
- **Valuation (Phase 3) before ingestion (Phase 4)** so adapters attach
  valuations to records on write rather than back-filling.
- **Domain convergence (Phase 5) is deliberately last.** It consumes a stable
  engine: contracts, registry, resolver, valuations, graph surface, rollup
  semantics, and display must all be settled and CI-guarded (Phase 6 land the
  guard for them) before a domain's historical records are reinterpreted through
  the canonical model. Migrating domains earlier would couple each domain to a
  moving engine and multiply rework.

## 4. Ledger

| Date | Phase | Result |
| --- | --- | --- |
| 2026-09-02 | kickoff | Program docs authored (this plan, architecture source of truth, migration-status ledger); implementation starting |
| 2026-09-02 | Phase 2/3 (registry trunk + graph surface + valuation engine core) | W2 lanes landed; registries/resolver/routes + graph reference surface + valuation engine core committed; valuation persistence + domain convergence pending |
| 2026-09-02 | Phase 3 (valuation persistence + projector + reporting display) | W3 lanes landed (code c6e99f54): migration B (`valuation_price_observations` / `valuation_snapshots` / `tenant_value_policies`), `/v1/valuation` routes, append-only snapshot persistence with the supersede carve-out, the registry→graph reference projector (storage-spelling-neutral idempotency; `node_created`/`node_versioned`), and frontend reporting-value display — all flag-gated default OFF; review findings HIGH-1/MEDIUM-4/F1/F3/F6 resolved, F2/F5/MEDIUM-3 accepted (see migration-status Notes); domain convergence pending |
| 2026-09-02 | Phase 4 (rollup/display shared seam) | W4a lane landed (code 84069154): reporting-asset-keyed `safe_rollup` (additive, byte-identical `fiat:USD` default; `reporting_totals` envelope + opt-in `value_lineage`; never-guessed non-USD conversion; ownership-gated reporting view), `ValuationService.reporting_asset_id_for` tenant policy resolver, TS `RollupResult` additive fields; 133 targeted tests green; per-domain convergence pending |
| 2026-09-02 | Phase 4 (profile360 on the reporting seam) | W4b lane landed (code dbf2a140): profile360 `financials` threads `reporting_asset_id` / `amount_in_reporting_asset` into `safe_rollup` (inflow/outflow/settled), so unknown/unpriced values are never 0 and totals can be reporting-asset-keyed; behavior unchanged by default; profile360 normalization tests added |
| 2026-09-02 | Phase 4 (card-linked decimal money) | W4b lane landed (code 537a35fb): card-linked `_sum_usd`, clusters `_volume`, models `amount_bucket`, and profile-summary flow filters accumulate in `Decimal` instead of float, so money never rounds through binary floats; behavior unchanged by default; decimal-money tests added (12) |
| 2026-09-02 | Phase 4 (agent-cost money audit) | W4b lane landed (code c10b7876): the agent-cost surface (`services/ai_economics`) was audited money-clean — aggregation is already `Decimal`-native and no float money reaches a sum; a money-exactness test locks the invariant |
| 2026-09-02 | Phase 4 (stablecoin canonical-identity read seam) | W4b lane landed (code 74b92014): new `services/stablecoin/canonical_identity.py` resolves current/legacy references to namespaced `stablecoin:*` canonical ids and surfaces the canonical spelling on read rows additively; legacy ids/rows untouched; read-seam tests added (15) |
| 2026-09-02 | Phase 4 (commerce metering money exactness) | W4b lane landed (code 139e6994): `services/commerce/metering.py` builds meter records via `to_decimal_string` and `summarize` accumulates in `Decimal`, so metering never sums float money; behavior unchanged by default; metering money-exactness tests added (4); remaining float surfaces in `models.py` / `service.py` / `economic_analytics.py` tracked for convergence |
| 2026-09-02 | Phase 4 (x402 decimal money) | W4b lane landed (code 02fab7b9): x402 pricing/discounts (`pricing.py`), interceptor fee elimination (`_FEE_FACTOR_DEC` — exact half-even at 4 dp, so a $0.05 capture fees 0.0014 rather than a float-round artifact 0.0015), policy caps (`policies.py`), and economic-graph money legs (`economic_graph.py` PAYS edges, `economic_mutations.py`) all compute in `Decimal` with `to_decimal_string` at the persistence boundary; wire JSON float types preserved; decimal-money tests added (8) |
| 2026-09-02 | Phase 6 (CI validator + tests) | C5-VALIDATOR landed (code c7773f82): new static gate `scripts/validate_universal_financial_assets.py` wired into `repo_doctor` (gate #44) enforcing namespaced ids, Decimal money (NUMERIC(38, 18), no binary-float columns), immutable append-only snapshots, observe-only posture, alias preservation, x402 seed completeness, and the deterministic sha256 `registry_version`; synchronized parser test in `tests/unit/test_repo_doctor_cli.py`; §36 matrix consolidated across the W2/W3 suites (tests/assets, tests/valuation, tests/value, stablecoin seam) |
| 2026-09-02 | Phase 6 (admin/discovery) | C5-ADMIN landed (code 82eb65aa): registry-admin facade + automated-discovery skeleton (`unresolved → candidate → verified → active`; resolver-seam suggestions are never auto-written, a human confirms then applies) served at `/v1/admin/assets`, flag-gated OFF (`AETHER_ASSETS_ADMIN_ENABLED` / `AETHER_ASSETS_ADMIN_MODE`); honest architecture §10A note (data-integrity scaffolding, not lending/underwriting/execution); DB-free tests green (7 new + sibling assets suite) |

When a phase lands, its row is updated here and the corresponding
migration-status ledger rows in
`docs/source-of-truth/FINANCIAL_DOMAIN_MIGRATION_STATUS.md` are moved. No phase
has fully shipped as of this ledger; Phase 2 (registry trunk), Phase 3
(graph reference surface + valuation engine core + migration B persistence +
`/v1/valuation` routes + registry→graph projector), Phase 4 (rollup/display seam
+ per-domain money-hardening + additive read seams), and Phase 6's validator +
admin/discovery halves (C5-VALIDATOR gate #44, C5-ADMIN `/v1/admin/assets`
console) have all landed, with the platform layers flag-gated default OFF until
operational validation. The two remaining gates before the program can claim
release readiness are the per-domain convergence onto the canonical model
(Phase 5, rows stay LEGACY until then) and the final `make ci-check` /
`make release-gate`.
