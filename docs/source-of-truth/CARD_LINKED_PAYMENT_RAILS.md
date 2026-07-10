---
title: Card-Linked Payment Rails Source of Truth
status: draft
last_synced_commit: pending
---

# Card-Linked Payment Rail Observability V1

Aether models card-linked activity as an observation-first extension of existing economic activity, payment rails, journeys, campaigns, graph, clusters, and Kyber diagnostics. It is **not** a standalone crypto-card product and must be surfaced under `Profile360 → Economic Activity → Payment Rails → Card-linked Activity`.

## Product boundary

Aether may observe, normalize, attribute, graph, cluster, recommend, surface, diagnose, and stage review. Aether must not process card payments, issue cards, custody funds, settle funds, sign transactions, execute payments or campaigns, store raw KYC/PAN/CVV/bank data, make automated consequential fraud/credit/reward-denial decisions, claim top-up volume is spend, or merge human identity based only on card-linked behavior.

## Required semantics

Every card-linked record, metric, graph edge, UI surface, benchmark, and campaign outcome carries a `basis` from the centralized `CardActivityBasis` set: `topup`, `funding`, `spend`, `settlement`, `clearing`, `refund`, `reversal`, `mixed`, `benchmark_only`, or `unknown`.

Rules:

- `topup != spend` and `funding != spend`.
- `settlement != spend` unless provider evidence explicitly defines it as spend-equivalent.
- `benchmark_only != user-level truth`.
- `mixed` must expose component breakdown.
- `unknown` must render visibly.

## Sources and default confidence

- PaymentScan: catalog/benchmark/aggregate intelligence only; default `source=paymentscan`, `reconciliation_state=benchmark_only`, `basis=benchmark_only` unless the exact source basis is represented, and `confidence=weak/probable`.
- Provider webhook: tenant-authorized signed provider evidence may represent `spend`, `settlement`, `refund`, or `reversal` with `confidence=strong/deterministic`.
- On-chain observer: wallet/card-funding observations default to `topup`, `funding`, or `settlement` with `confidence=probable/strong`.

## Privacy defaults

Blocked fields are rejected or redacted at ingestion: PAN, CVV, full card number, full bank account number, routing number, raw KYC documents/images, provider secrets, authorization headers, private API keys, and raw cardholder identity documents.

Consent gates:

- Card payment/top-up metadata → commerce.
- Wallet/on-chain transaction → web3.
- Agent-influenced card activity → agent + commerce.
- Credit/underwriting/card eligibility → credit explicit opt-in.
- Merchant/location/MCC/geographic behavior → location explicit opt-in where applicable.
- Raw card/KYC/bank data → blocked.

Regional modes are `US_STANDARD`, `EU_RESTRICTED`, `UK_RESTRICTED`, `APAC_RESTRICTED`, and `GLOBAL_AGGREGATE_ONLY`. EU/APAC user-level card activation and automated decisions default off; aggregate benchmarks are allowed only where contractual/legal basis exists.

## Feature flags

All V1 surfaces are default-off except safety restrictions:

- `AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED=false`
- `AETHER_PAYMENTSCAN_CATALOG_ENABLED=false`
- `AETHER_PAYMENTSCAN_BENCHMARKS_ENABLED=false`
- `AETHER_CARD_LINKED_PROFILE360_ENABLED=false`
- `AETHER_CARD_LINKED_CAMPAIGN_ATTRIBUTION_ENABLED=false`
- `AETHER_CARD_LINKED_CLUSTERING_ENABLED=false`
- `KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED=false`
- `AETHER_CARD_LINKED_EU_RESTRICTED_MODE=true`
- `AETHER_CARD_LINKED_APAC_RESTRICTED_MODE=true`
- `AETHER_CARD_LINKED_PROVIDER_PII_BLOCK=true`

## Canonical implementation points

- Shared contracts: `packages/shared/payment-catalog.ts` and `packages/shared/card-linked-payments.ts`.
- Backend semantics: `Backend Architecture/aether-backend/services/card_linked_payments/models.py`.
- Backend catalog: `Backend Architecture/aether-backend/services/payment_catalog/catalog.py`.
- Settings: `Backend Architecture/aether-backend/config/settings.py`.
