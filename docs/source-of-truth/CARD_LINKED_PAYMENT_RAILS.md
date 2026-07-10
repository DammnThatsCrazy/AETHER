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

## V1 route and surface contract

The implementation now exposes the card-linked rail as a payment-rail sub-surface rather than a standalone crypto-card product:

- Tenant ingestion:
  - `POST /v1/card-linked-payment-rails/ingest/provider-webhook` for tenant-authorized off-chain provider card spend, settlement, refund, or reversal evidence.
  - `POST /v1/card-linked-payment-rails/ingest/onchain` for wallet/on-chain card top-up, funding, or settlement observations.
- Profile360:
  - `GET /v1/profile/{entity_id}/card-linked-activity`.
  - `GET /v1/profile/{entity_id}/economic/card-linked`.
  - `GET /v1/profile/{entity_id}/drill/card-linked/{object_id}`.
- Campaign360/card-linked outcomes:
  - `GET /v1/card-linked-payment-rails/campaigns/{campaign_id}/outcomes`.
- Graph Explorer/Cluster360 support:
  - `GET /v1/card-linked-payment-rails/graph` supports filters for card program, basis, chain, campaign, and minimum volume.
  - `GET /v1/card-linked-payment-rails/clusters` returns review-only behavioral/economic clusters.
- Kyber Payment Rails Diagnostics:
  - `GET /v1/admin/kyber/payment-rails/card-linked/diagnostics` reports catalog coverage, PaymentScan status, source/basis quality, unmatched events, reconciliation conflicts, region restrictions, consent suppression, blocked PII attempts, graph queue health, and top-up-vs-spend mislabeling warnings.

All routes are behind the default-off card-linked flags. Profile360, Campaign360, clustering, and Kyber diagnostics have separate rollout flags so tenants can enable surfaces incrementally without changing the observation boundary.

The tenant-facing Aether UI consumes these routes in-place: Profile360 adds a `Card-linked Activity` tab under the economic/payment-rails area, and Campaign360 adds `Card-linked Outcomes`. Neither surface is a standalone crypto-card dashboard; both render basis labels and top-up/spend warnings directly beside the metrics.

## Graph and identity safeguards

Card-linked graph projections include CardLinkedFlow, CardProgram, CardIssuer, PaymentNetwork, Campaign, Journey, Chain, and Token nodes. Edges carry `basis`, `confidence`, `tenant_id`, and `evidence_refs`; generated card-linked edges explicitly set `identity_merge_evidence=false` so card-linked behavior cannot become deterministic identity-merge proof by default.

## Campaign and cluster safeguards

Campaign card-linked outcomes include basis/source/confidence breakdowns and separate top-up/funding volume from spend volume. Cluster outputs are marked review-only intelligence and must not trigger automated denial, suppression, adverse credit, final fraud, pricing, or reward-denial actions.
