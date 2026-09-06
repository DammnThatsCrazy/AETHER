# Financial Value Semantics

Canonical, USD-first value semantics for every financial/economic value Aether
surfaces. Aether **observes and prices** value; it never custodies, settles, or
executes.

- TypeScript contract: `packages/shared/value.ts` (`AetherValue`, `MetricKind`,
  `USDValuation`, `NativeValue`, `RollupResult`).
- Backend mirror: `Backend Architecture/aether-backend/services/value/`
  (`models.py`, `valuation.py`, `rollups.py`).
- Gates: `scripts/validate_financial_value_semantics.py` (contract + no
  cross-currency sums), `scripts/validate_frontend_value_display.py`
  (canonical display), and `scripts/validate_cross360_monetary_fx.py` (the
  context-360 family + cross-360 composition seam stay on this canonical path
  — no geography- or population-specific FX).

## Core rules

1. **USD-first, native-preserving.** The primary display value is USD where a
   trustworthy USD valuation exists; the native value (amount + currency/asset)
   is always preserved as a secondary drilldown and never discarded.
2. **Decimal strings, never floats.** `amount` and `usd_value` are decimal
   strings. Floats are never persisted or summed.
3. **Unknown is never zero.** A missing/stale/unpriced/conflicted USD value is
   `usd_value: null` with an `unavailable` freshness — never coerced to `"0"`.
4. **No mixed-currency scalar sums.** Values in different native currencies are
   never added into one scalar without a valid USD valuation. Rollups group by
   native currency and only sum USD across values that carry a trustworthy USD
   valuation.
5. **Stablecoins are peg-aware.** A stablecoin is not assumed to be $1; valuation
   is peg-aware and source-backed (see `services/stablecoin/valuation.py`).
6. **Metric kinds don't mix.** `balance`, `flow`, `kpi`, `forecast`,
   `valuation`, `liability`, `cost`, `fee`, `revenue`, `risk_exposure`, and
   `unknown` are distinct. Liabilities are never counted as assets.
7. **Exclusions are explicit.** `include_in_rollups: false` requires an
   `exclusion_reason`. Testnet and spam/untrusted assets are excluded from
   trusted production USD rollups by default.
8. **One FX seam — no geography- or population-specific FX.** A cross-360
   monetary metric is computed through this canonical value contract and its FX
   provenance (`services/value` — the `packages/shared/value.ts` mirror) only.
   There is no per-slice FX beside it: no location-flavored or cohort-flavored
   rate table, no second `Money` class, no re-pricing inside the context-360
   family (`temporal360`/`geographic360`/`population360`, their `services/geo`
   plane, the exploration path, or the cross-360 composition seam in
   `shared/projection_engine/composition.py`). A composite that carries a
   monetary metric takes it **pre-priced** from economic360 /
   `services.value`; the cross-360 composition union (`CompositionResult`)
   moves section content unchanged — it never re-prices by geography or
   population.

## Valuation methods

| Method | When |
|---|---|
| `fiat_identity` | Native currency is USD — usd_value = amount |
| `provider_reported` | A trustworthy `value_usd`/`amount_usd` is supplied |
| `fx_rate` | Non-USD fiat converted via an FX rate |
| `market_price` | Token/asset priced from a market source |
| `stablecoin_peg_verified` | Peg-aware, source-backed stablecoin valuation |
| `manual` | Operator-provided |
| `unavailable` | No trusted USD price within the freshness window (usd_value null) |

The pluggable price-source layer (`services/value/price_sources.py`) resolves
USD across fiat identity, FX, token market price, and **peg-aware stablecoin
valuation** (reusing `services/stablecoin/valuation.classify_peg` — a stablecoin
is never assumed to be $1). Real adapters (FX API, market data, Chainlink peg
feeds) are credential-gated and registered at deploy time; CI runs against
deterministic fixtures and never requires live credentials. A source being
unavailable yields **unpriced**, not zero.

Rollup inclusion additionally honors `services/value/ownership_rules.py`:
liabilities are never counted as assets; testnet and spam/untrusted assets are
excluded from trusted production rollups; counterparty/external/observed
relationships are excluded from an owned portfolio. Cross-source agreement is
tracked by `services/value/reconciliation.py` (`matched` / `conflict` /
`sdk_only` / `provider_only` / `stale`).

Higher-level rules libraries build on this: `tvl_rules` (gross/net TVL,
wrapped/LP double-count prevention), `ltv_rules` (historical/predicted/net LTV),
`portfolio_rules` (cash/stablecoin/volatile/liability buckets + net worth), and
`account_rules` (Web2 asset vs liability classification). Durable snapshots
persist via `services/value/repositories.py` (tables added in migration
`20260721_value_semantics`).

## Safe rollups

`services.value.safe_rollup(records)` returns a `RollupResult`:

- `total_usd`: decimal string, or **null** when nothing can be priced (never
  `"0"` on absence).
- `by_native_currency`: per-currency native totals + USD (when priced) + count.
- `unpriced_count` / `stale_count` / `excluded_count`.
- `rollup_status`: `complete` (all priced), `partial` (some priced), or
  `unavailable` (none priced); also `stale` / `conflicted`.
- `native_currency` / `native_total`: the single-currency raw sum, exposed only
  when unambiguous (one native currency); **null** when currencies are mixed.

## Profile360 financials

`Profile360Aggregator.financials()` and `.summary()` previously summed raw
`float(amount)` across all transfers regardless of currency — a release blocker.
They now use `safe_rollup`:

- Canonical USD-first fields: `inflow_usd`, `outflow_usd`, `net_usd`,
  `settled_usd`, `rollup_status`, `by_native_currency`,
  `unpriced_count`/`stale_count`/`excluded_count`, and a `valuation` breakdown.
- Legacy fields (`inflow_total`, `outflow_total`, `net`, `settled_total`) are
  **deprecated** and populated only when values share a single native currency
  (unambiguous); they are `null` when currencies are mixed — a mixed-currency
  scalar is never produced.
- Each recent item carries a canonical `value` envelope (native + USD valuation).

## Display contract

The frontend renders values through `frontend/shared` value components
(`ValueDisplay`, `formatUSD`, `formatAetherValue`) — never a per-file currency
formatter (enforced by `validate_frontend_value_display.py`).

```
Primary:   $12,430.22 USD
Secondary: 1.84 ETH on Base
Warning:   stale / unpriced / conflict (when applicable)

Unavailable →  Primary: "Value unavailable"  (never $0.00)
Liability   →  Primary: -$4,200.00 USD  (labelled Liability, never an asset)
```

## Generalization to multiple reporting assets

The USD-first invariants above are the base case of a more general model this
repository is moving toward: **Universal Financial Normalization**
([FINANCIAL_NORMALIZATION.md](./FINANCIAL_NORMALIZATION.md)). Today the single
reporting/display asset is USD (`USDValuation`). Under the generalized model,
USD becomes one configured reporting asset among several (canonically
`fiat:USD`, with other reporting assets seeded over time), while every invariant
above is preserved and restated in reporting-asset-agnostic form:

- **Reporting amount is null, never 0.** A missing/stale/unpriced/conflicted
  reporting valuation is `reporting_amount: null` — never coerced to `"0"` in
  any reporting asset.
- **No mixed-currency scalar sums.** Native values in different currencies are
  never added into one scalar; rollups key totals by reporting asset and keep
  native amounts per native currency, exactly as `safe_rollup` does for USD
  today.
- **Native is preserved.** The native amount + currency/asset survives as the
  secondary drilldown and is never discarded when a reporting valuation is
  attached.
- **Stablecoins remain peg-aware.** A stablecoin is never assumed to equal a
  reporting asset at a fixed 1:1 rate, regardless of the reporting asset.
- **Unknown stays unknown.** Unresolved/unpriced/conflicted values stay
  explicit (`null`, `unavailable`) rather than guessed or zeroed.

Migration toward the generalized model is additive: the existing USD-first
contracts and invariants in this document remain authoritative until the
reporting-asset layer lands (Phase 1–3 of the [Financial Normalization — Phased
Implementation Program](../plans/FINANCIAL_NORMALIZATION_PHASES.md)), and the
domain-by-domain move is tracked in the [Financial Domain Migration
Status](./FINANCIAL_DOMAIN_MIGRATION_STATUS.md) ledger.

## Adoption status

Profile360 financials + the Profile360 contextual panels render via the
canonical path. The broader economic surfaces (derivatives, card-linked,
campaigns, TVL/LTV, x402) remain on a documented adoption backlog tracked by the
allowlist in `scripts/validate_frontend_value_display.py`; new surfaces must use
the canonical value contract from the start.
