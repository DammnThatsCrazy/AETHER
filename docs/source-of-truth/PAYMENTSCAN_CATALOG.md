---
title: PaymentScan Catalog Source of Truth
status: draft
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
