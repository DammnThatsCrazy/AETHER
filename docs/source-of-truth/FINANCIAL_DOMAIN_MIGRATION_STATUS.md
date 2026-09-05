---
title: Financial Normalization — Domain Migration Status
slug: architecture/financial-domain-migration-status
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
estimated_read_minutes: 6
toc_depth: 3
---
# Financial Normalization — Domain Migration Status

This is the output ledger for [Universal Financial
Normalization](./FINANCIAL_NORMALIZATION.md): one row per financial domain,
tracking how far each domain has moved onto the canonical model (canonical asset
identity + chain deployment, event-time valuation, ingestion adapter, and
reference graph edges). The architecture and vocabulary are defined in
[FINANCIAL_NORMALIZATION.md](./FINANCIAL_NORMALIZATION.md); the phase that moves
each domain is defined in
[../plans/FINANCIAL_NORMALIZATION_PHASES.md](../plans/FINANCIAL_NORMALIZATION_PHASES.md).

**State vocabulary** (per-domain): `CANONICAL` = on the canonical model end to
end; `PARTIAL` = canonical for some records/surfaces only; `LEGACY` = still on
the pre-program model; `BLOCKED` = cannot proceed without an external
dependency.

**Honesty rule.** No financial *domain* (commerce, e-commerce, …) has shipped
on the canonical model yet — those rows below remain LEGACY until domain
convergence lands. The two program-capability rows (universal asset registry,
event-time valuation engine) track through `PARTIAL` as their program phases
land and move to `CANONICAL` only when fully operational. As phases land, rows
are updated here — LEGACY → PARTIAL → CANONICAL — alongside the ledger in the
phases plan. The registry status, valuation status, adapter, and graph edge
columns stay empty (`—`) until the corresponding capability actually lands for
that domain.

## Ledger

| Domain | Registry status | Valuation status | Adapter | Graph edges | State |
| --- | --- | --- | --- | --- | --- |
| Universal asset + deployment registry (program capability) | Phase 2 landed — migration A + typed repos + seeds + resolver + registry facade + deterministic sha256 `registry_version`; `/v1/assets` routes flag-gated OFF by default; runtime seeding not enabled | — (registry rows carry metadata, not valuations) | — | Phase 3 landed — reference VertexType/EdgeType members + global reference schemas landed (EXCLUDED layer); registry→graph projector landed (ASSET / FIAT_CURRENCY / CHAIN / ASSET_DEPLOYMENT vertices + DEPLOYED_ON_CHAIN edges; opt-in seeder, default OFF) | PARTIAL |
| Event-time valuation engine (program capability) | — | Phase 3 landed — engine core (pure, port-injected `value_at` + `observe_price`) + migration B append-only persistence (`valuation_price_observations` / `valuation_snapshots` with the supersede carve-out, `tenant_value_policies`) + `/v1/valuation` routes; flag-gated OFF by default | — | Planned — Phase 3 (valuation snapshot vertices) | PARTIAL |
| Value (shared contract + `services/value`) | LEGACY — USD-first canonical contract; currency is a bare string | LEGACY — `USDValuation` only; peg-aware via `stablecoin_peg_verified` | — | — | LEGACY |
| Stablecoin registry | LEGACY — today's canonical asset + deployment registry; x402-seeded; **seed source** for the universal registry | LEGACY — peg-aware, source-backed stablecoin valuation | — | — | LEGACY |
| Stablecoin intelligence | LEGACY | LEGACY | — | — | LEGACY |
| Commerce | LEGACY | LEGACY | — | — | LEGACY |
| E-commerce | LEGACY | LEGACY | — | — | LEGACY |
| Unified financial profile | LEGACY — Profile360 financials on `safe_rollup` (USD-first); legacy summed fields deprecated | LEGACY | — | — | LEGACY |
| Payment rails | LEGACY | LEGACY | — | — | LEGACY |
| Wallet | LEGACY | LEGACY | — | — | LEGACY |
| x402 payments | LEGACY | LEGACY | — | — | LEGACY |
| Card-linked | LEGACY | LEGACY | — | — | LEGACY |
| Derivatives | LEGACY | LEGACY | — | — | LEGACY |
| Campaign / attribution / LTV | LEGACY | LEGACY | — | — | LEGACY |
| Agent cost | LEGACY | LEGACY | — | — | LEGACY |

## Notes

- **Program capability rows** (universal registry, event-time valuation engine)
  are tracked in this ledger even though they are new: until their phases land
  they are LEGACY (no shipped implementation). They move to CANONICAL when Phase
  2 (registry) and Phase 3 (valuation engine + graph surface) complete.
- **Stablecoin registry as seed source.** The two stablecoin rows carry the
  note that today's `services/stablecoin/` registry — the only canonical asset +
  deployment registry in the repository, x402-seeded from verified contracts —
  is the seed source the universal registry generalizes. The universal registry
  does not replace it in a breaking way: the stablecoin rows are imported as
  seed rows and legacy ids are preserved via alias rows.
- **Convergence order** for Phase 5 is commerce → e-commerce → unified financial
  profile → payment rails → wallet → x402 → card-linked → stablecoin convergence
  → derivatives → campaign/attribution/LTV → agent cost. Rows move in that
  order as each domain's adapter and graph edges land.
- State changes require the supporting code to exist and be gated; this document
  is updated after review with the phases-plan ledger, never ahead of it.

### W3 code-review resolution (2026-09-02, code c6e99f54)

Recorded so the review outcomes travel with the ledger, not just the commit:

- **HIGH-1 — fixed.** The registry→graph projector is idempotent in a
  storage-spelling-neutral sense (string-normalised comparison, so an int 6 in a
  build equals Neptune's `"6"` read-back), and a vertex whose content changed is
  rewritten in place via `node_versioned` (gateway upsert_vertex) rather than a
  duplicate `addV` on its existing id — safe on the Neptune pure-insert path.
- **MEDIUM-4 — fixed.** DEPLOYED_ON_CHAIN edges carry `actor_kind="system"`, the
  graph write validator's edge-actor vocabulary, so projection passes the strict
  Neptune edge-validation path; the broader `service` spelling is retained only
  on vertex intents (ledger-legal `MUTATION_ACTOR_KINDS`).
- **F1/F3/F6 — fixed.** `/v1/assets` + `/v1/valuation` prefixes classified in the
  route registry; value/policy writes reject reporting/allowed asset ids unknown
  to the registry (resolve-never-invent); a verified asset carrying no amount
  raises instead of recording a spurious unresolved row.
- **F2 — accepted as designed.** `/v1/valuation` observational writes are
  global-ADMIN and observation-only (mirroring `/v1/assets`); no execution
  capability exists behind any flag (`execution_by_aether` always False).
- **F5 / MEDIUM-3 — accepted (fail-loud).** The observation-ingest replay pre-scan
  makes genuine replays no-ops before the partial-index boundary, so the
  collision fires only on malformed cross-asset `source_record_id` reuse — where
  surfacing the conflict (rather than silently deduplicating) is correct.
- **MEDIUM-2 / NIT-6 — fixed.** Append-only immutability is enforced at the
  repository boundary: observation rows refuse `update_by_key`, and snapshot
  updates outside the `status` / supersede back-pointer carve-out are refused.

### W4a shared-layer note (2026-09-02, code 84069154)

Phase-4's rollup/display seam landed before the per-domain convergence lanes.
`safe_rollup` (`services/value/rollups.py`) is reporting-asset-keyed with a
byte-identical `fiat:USD` default: a reporting context adds a `reporting_totals`
envelope (priced/unpriced/excluded/stale counts, `coverage_percentage`,
`rollup_status`) plus opt-in `value_lineage`, conversion to a non-USD reporting
asset is never guessed (the caller supplies `amount_in_reporting_asset`, e.g.
backed by the valuation engine), and ownership rules gate the reporting view
exactly as they gate the USD view. `ValuationService.reporting_asset_id_for`
resolves the tenant reporting asset from `tenant_value_policies` (default
`fiat:USD`). No row above moves: the program-capability and per-domain rows
remain at their W3 state (per-domain models are still LEGACY — convergence is
Phase 5).

### W4b hardening + read-seam note (2026-09-02, codes 537a35fb / c10b7876 /
74b92014 / dbf2a140 / 139e6994 / 02fab7b9)

Phase-4 W4b landed six per-domain hardening lanes, all default-behavior-neutral
money/read work ahead of Phase-5 convergence:

- **Card-linked** (537a35fb): `_sum_usd`, `_volume`, `amount_bucket`, and
  profile-summary flow-filter accumulation now sum in `Decimal`, never binary
  float.
- **Agent cost** (c10b7876): `services/ai_economics` audited money-clean —
  aggregation was already `Decimal`-native; a money-exactness test locks it.
- **Stablecoin** (74b92014): additive `services/stablecoin/canonical_identity.py`
  read seam resolves current/legacy references to namespaced `stablecoin:*`
  canonical ids and surfaces the canonical spelling on read rows; legacy rows and
  ids are untouched.
- **Unified financial profile** (dbf2a140): `financials` threads
  `reporting_asset_id` into the reporting-asset-keyed `safe_rollup` so
  unknown/unpriced is never 0 and totals may be reporting-asset-keyed.
- **Commerce** (139e6994): metering records build via `to_decimal_string` and
  `summarize` accumulates in `Decimal`; remaining float surfaces tracked.
- **x402** (02fab7b9): pricing/discounts, interceptor fee elimination (exact
  half-even 4-dp `Decimal` — a $0.05 capture fees 0.0014, not a float artifact
  0.0015), policy caps, and economic-graph money legs persist via
  `to_decimal_string`; wire JSON float types preserved.

None of these moves a domain onto the canonical model end to end: no row above
changes state, and the per-domain rows remain **LEGACY** — these lanes harden
money math and add read-only seams on the existing model. Adapter + graph-edge
convergence onto the canonical engine is Phase 5.

### W5 validator + admin/discovery note (2026-09-02, codes c7773f82 / 82eb65aa)

Phase-6 halves landed ahead of domain convergence.

- **C5-VALIDATOR** (c7773f82): `scripts/validate_universal_financial_assets.py`
  is now a repo-doctor gate (#44) enforcing, statically, the normalization
  invariants the program's rows depend on — namespaced canonical ids, Decimal
  money (NUMERIC(38, 18), no binary-float money columns in the financial
  migrations), immutable append-only valuation snapshots, observation-only
  persisted rows (`execution_by_aether` False), legacy alias preservation,
  x402 seed completeness, and the deterministic sha256 `registry_version`. The
  §36 test matrix is consolidated across the existing W2/W3 suites.
- **C5-ADMIN** (82eb65aa): a registry-admin facade + automated-discovery
  skeleton (`unresolved → candidate → verified → active`; resolver-seam
  suggestions are never auto-written — a human confirms, then a human applies)
  served at `/v1/admin/assets`, flag-gated OFF
  (`AETHER_ASSETS_ADMIN_ENABLED` / `AETHER_ASSETS_ADMIN_MODE`). Documented as
  data-integrity scaffolding, observation-only, with no lending/underwriting or
  execution behavior (architecture §10A).

No row above changes state: the program-capability rows (universal asset
registry, event-time valuation engine) remain **PARTIAL** (they move to
CANONICAL only when fully operational after Phase-5 domain convergence), and the
per-domain rows remain **LEGACY** until their adapters + graph edges land.

Related material:

- [Financial Normalization — Architecture](./FINANCIAL_NORMALIZATION.md)
- [Financial Value Semantics](./FINANCIAL_VALUE_SEMANTICS.md)
- [Financial Normalization — Phased Implementation
  Program](../plans/FINANCIAL_NORMALIZATION_PHASES.md)
