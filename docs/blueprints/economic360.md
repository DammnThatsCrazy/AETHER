# Economic360 — Intelligence-Projection Blueprint

**Registry id:** `economic360`
**Projection kind:** `measurement_360`
**Blueprint for:** the registry row's `implementationBlueprint` /
`legacyBindings.migrationBlueprint` — the vertical slice (S3) that converges
`economic360` to `implementationState: "implemented"`.

---

## What it is

Economic360 is an **intelligence projection over canonical Aether truth** — it is
NOT a competing system of record (ADR-010, `ownsCanonicalTruth: false`). It
answers "what is the economic picture of this subject?" (campaign, episode, or
source) by **reading** the canonical economic authorities — AI execution
economics, computed campaign economics, value normalization / safe rollups, and
value diagnostics — and projecting a typed, evidence-grounded, tenant-scoped
result through the Intelligence Projection Plane's shared contracts
(`ProjectionRequest` → `ProjectionResult`).

It never writes. `graphMutationPolicy: read_only`; there is no write path at all.

## Why

The backend ships an economic surface (`/v1/economic`, `/v1/profile/{id}/economic`)
as mounted routes and services, but nothing stated what the *surface* is relative
to canonical truth. Without a declared authority boundary, a composite read drifts
toward a parallel store that re-answers questions the canonical planes already
answer. This slice lands `economic360` as a first-class projection: a real
provider implementing the `IntelligenceProjectionProvider` protocol, reading the
same canonical sources the routes already read, and doing so **fail-isolated and
tenant-scoped**.

## How it works

### Canonical sources (read-only)

| Section | Canonical source read |
|---|---|
| `summary` | `services/value` `safe_rollup` over tenant-scoped value records; the absorbed `metric-registry.json` vocabulary |
| `state` | `services/economic/value_diagnostics.diagnose_rollup` over the rollup |
| `evidence` | the reused `EvidenceRef`s grounding every claim |
| `outcomes` | canonical computed results; **degraded honestly** while `outcome360` is `in_flight` |
| `findings` | typed `EconomicWarning` anti-patterns (`MIXED_CURRENCY`, `MISSING_PRICE`, `POSSIBLE_DOUBLE_COUNT`) |

The provider reads canonical sources **defensively** through
`services/economic/ai_*` (AI execution facts + cost selection),
`services/economic/computed_results` + `services/computation/campaign` (canonical
campaign economics), `services/value` (USD-first safe rollups) and
`services/economic/value_diagnostics`. Every read is wrapped: an unavailable
backing source degrades its section (typed `degraded` / `missing` / `empty`),
never crashes, never fabricates. A `RuntimeError` in a source reader yields a
`missing` summary with no exception detail surfaced.

### USD-first value semantics (the no-cross-currency invariant)

Every monetary amount in the economic contracts
(`services/economic/economic360_contracts.py`) is a `MonetaryAmount` carrying
`amount` + `currency` **and** an explicit normalized `usd_value`
(`None` when unpriced — never coerced to `0`). The invariants:

1. **No cross-currency sums, ever.** `safe_usd_total` sums ONLY normalized USD
   figures; a raw native sum across currencies is **rejected**
   (`MixedCurrencyError`, `native_total`). This mirrors the safe-rollup shape
   from `services/value` — the projection never produces a mixed native scalar.
2. **Monetary absences stay `None`.** Unpriced amounts are `usd_value: None`;
   `MISSING_PRICE` is a typed warning, not an invented figure.
3. **Anti-patterns are typed warnings, not fabricated values.** `MIXED_CURRENCY`,
   `MISSING_PRICE` and `POSSIBLE_DOUBLE_COUNT` surface as
   `EconomicWarning` codes on the `findings` section.

`EconomicValuationContext` records `price_source` + `priced_at` so `MISSING_PRICE`
is signaled without fabricating a value: an unpriced context keeps
`price_source == "unavailable"` and `priced_at is None`.

### No redefinition

The slice reuses the canonical `EntityRef` / `EvidenceRef` / `PageRequest` /
`TimeRangeFilter` primitives from `services/operational_intelligence/models.py`
— the economic package declares NO second copy (parity-tested).

### Dependency story (profile360 / relationship360 / outcome360)

`economic360` declares `projectionDependencies: [profile360, relationship360,
outcome360]` — all three are still `implementationState: in_flight`. The runtime
registry's `build_context` computes them as `missing` (a legal computed state,
never an exception), and the provider **degrades honestly** instead of failing:

* `summary` → `degraded` (profile360 enrichment unavailable)
* `state` → `degraded` (relationship360 enrichment unavailable)
* `outcomes` → `degraded` with the reason "outcome360 dependency is not yet
  implemented; outcome economics are not projected (in_flight)"

The projection still returns a valid `ProjectionResult` with `dependencyState`
echoed verbatim from the registry. When those slices land, the provider's
sections lift to `available` with **zero code change** — the degradation is
already dep-state driven.

### Metric absorption (the 4 pending refs cleared)

`metric-registry.json` absorbed 11 economic metrics, including the 4 pending refs
(`campaign_spend`, `campaign_roas`, `campaign_cac`, `campaign_ltv`) plus the
program's economic metric set (`costs`, `exposure`, `gross_value`, `ltv`,
`margin`, `net_value`, `refunds`). The hand-authored
`shared/measurement/registry.py` added the same 11 `MetricDefinition`s
field-for-field.

Before — 4 `pendingReference` entries, all `resolvesInProjection: economic360`:

```json
{ "id": "campaign_spend", "kind": "metric",
  "reason": "economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json",
  "resolvesInProjection": "economic360" }
{ "id": "campaign_roas", "kind": "metric", ... }
{ "id": "campaign_cac",  "kind": "metric", ... }
{ "id": "campaign_ltv",  "kind": "metric", ... }
```

After — zero `pendingReference`; `metricRefs` extended to
`["revenue", "campaign_spend", "campaign_roas", "campaign_cac", "campaign_ltv"]`
(the pending declarations are removed because their targets now resolve). The
provider surfaces these in the `summary` section's `metrics` map
(`campaign_spend`, `gross_value`, `campaign_roas` computable from canonical
records; `campaign_cac` / `campaign_ltv` honestly `missing` until customer counts
are available).

### Zero-pending declaration

With the 4 pending refs cleared and no `pendingAuthority`, `economic360` is a
**zero-pending** row eligible for `implementationState: "implemented"` and
`legacyBindings.migrationMode: "converged"` once the orchestrator flips it.
`ownsCanonicalTruth` stays structurally `false`.

## What it means for the graph

Economic360 projects *over* the graph's economic truth — AI execution facts,
computed campaign metrics, value normalization — and never writes to it. The
graph remains the single system of record; the projection is a read-only lens
that can be run, degraded, or rebuilt without touching canonical state. Because
the provider is fail-isolated and order-resilient, it can land **before or
after** profile360 / relationship360 / outcome360 without corrupting them, and
it lifts to full `available` automatically when those sibling projections land.

## Definition of Done

This slice follows the canonical vertical-slice checklist —
`docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`
(registry row zero-pending + converged, shared-contract conformance, runtime
provider, evidence, tenant isolation, `read_only` graph policy, targeted tests,
and `make ci-check` green).

## Test surface (slice S3)

* `test_economic_contracts.py` — USD-first invariants (mixed-currency rejection,
  `MISSING_PRICE`, `POSSIBLE_DOUBLE_COUNT`, monetary absences stay `None`),
  `extra="forbid"`, no-redefinition of canonical primitives.
* `test_economic360_metric_parity.py` — the hand-authored registry contains the
  11 absorbed metrics, field-for-field with `metric-registry.json`.
* `test_economic360_provider.py` — valid `ProjectionResult` with typed sections
  and evidence-grounded claims; missing-dep honest degradation (never raises);
  content-free degradation; tenant isolation; registration (success / duplicate
  / version-mismatch / unknown id).
