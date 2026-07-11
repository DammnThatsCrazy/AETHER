# Financial Value Semantics

Canonical, USD-first value semantics for every financial/economic value Aether
surfaces. Aether **observes and prices** value; it never custodies, settles, or
executes.

- TypeScript contract: `packages/shared/value.ts` (`AetherValue`, `MetricKind`,
  `USDValuation`, `NativeValue`, `RollupResult`).
- Backend mirror: `Backend Architecture/aether-backend/services/value/`
  (`models.py`, `valuation.py`, `rollups.py`).
- Gates: `scripts/validate_financial_value_semantics.py` (contract + no
  cross-currency sums) and `scripts/validate_frontend_value_display.py`
  (canonical display).

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

The deterministic CI path trusts only `fiat_identity` (USD) and
`provider_reported` USD; FX and market pricing come from the pluggable
price-source layer and never require live third-party credentials in tests. A
price source being unavailable yields **unpriced**, not zero.

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

## Adoption status

Profile360 financials + the Profile360 contextual panels render via the
canonical path. The broader economic surfaces (derivatives, card-linked,
campaigns, TVL/LTV, x402) remain on a documented adoption backlog tracked by the
allowlist in `scripts/validate_frontend_value_display.py`; new surfaces must use
the canonical value contract from the start.
