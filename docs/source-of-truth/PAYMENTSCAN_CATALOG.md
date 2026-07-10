---
title: PaymentScan Catalog Source of Truth
status: stable
source_files:
  - packages/shared/payment-catalog.ts
  - Backend Architecture/aether-backend/services/payment_catalog/catalog.py
  - Backend Architecture/aether-backend/services/card_linked_payments/paymentscan.py
last_synced_commit: pending
---

# PaymentScan Catalog and Benchmarks

PaymentScan is used by Aether V1 as a catalog, benchmark, and aggregate intelligence source. PaymentScan-only records are never deterministic user-level truth and must default to `basis=benchmark_only` (or an explicit source-reported basis), `source=paymentscan`, and weak/probable confidence.

The current seed was checked against the public PaymentScan site on 2026-07-10. PaymentScan describes its surface as tracking crypto payment card usage/adoption and comparing volumes, transactions, and active users across card programs from on-chain data. It also publishes a crypto-card comparison page listing several major card programs. The V1 seed includes the user-required PaymentScan program/issuer/network/dimension minimums.

## Card programs

Canonical slugs:

- `redotpay` — RedotPay; aliases: Red.Pay, Redot Pay
- `kast` — KAST
- `etherfi` — EtherFi; alias: ether.fi
- `plasma_one` — Plasma One
- `karta` — Karta
- `tria` — Tria
- `gnosis` — Gnosis; alias: Gnosis Pay
- `cypher` — Cypher
- `kolo` — Kolo
- `ready` — Ready
- `bfinance` — BFinance
- `metamask` — MetaMask; alias: MetaMask Card
- `holyheld` — Holyheld
- `bitget_wallet` — Bitget Wallet
- `avici` — Avici
- `safepal` — SafePal
- `solayer` — Solayer
- `avalanche_card` — Avalanche Card
- `exa` — Exa
- `tuyo` — Tuyo
- `solflare` — Solflare
- `phantom_cash` — Phantom Cash
- `hyperbeat` — Hyperbeat

## Issuers

- `rain` — Rain
- `wirex` — Wirex
- `bridge` — Bridge
- `ur` — UR
- `kulipa` — Kulipa
- `immersve` — Immersve

## Payment networks

- `visa` — Visa
- `mastercard` — Mastercard
- `unknown` — Unknown

## Chain dimensions

`ethereum`, `tron`, `bsc`, `optimism`, `solana`, `arbitrum`, `base`, `other`, and `unknown`.

## Currency/asset dimensions

`usdc`, `usdt`, `eure`, `gbpe`, `usd24`, `liquidusd`, `other`, and `unknown`.

## V1 ingestion and freshness

`Backend Architecture/aether-backend/services/card_linked_payments/paymentscan.py`
implements the catalog/benchmark pipeline:

- `sync_catalog(tenant_id)` refreshes freshness state from the seed and
  records a `paymentscan` provider-health sync so Kyber can surface catalog
  staleness.
- `ingest_benchmark(...)` persists one benchmark observation. `entity_ref`
  resolves display names/aliases through the catalog (`Red.Pay` → `redotpay`);
  unknown refs are kept under slug `unknown` so coverage gaps stay visible.
  Basis defaults to `benchmark_only`; a source-reported basis (e.g. a top-up
  volume metric) is kept exactly, but `reconciliation_state` is ALWAYS
  `benchmark_only` — PaymentScan data never becomes user-level truth.
  Confidence is `probable` only for methodology-backed metric types
  (`program_count`, `issuer_count`, `network_share`); everything else is `weak`.
- `catalog_freshness(tenant_id)` reports last sync, staleness, and per-type
  entity counts for Kyber diagnostics.

Benchmark rows are excluded from user-level flow listings, gold rollups,
cluster cohorts, and graph projection. The tenant benchmarks endpoint
carries the notice "PaymentScan benchmarks are catalog/market
intelligence — not user-level card spend."
