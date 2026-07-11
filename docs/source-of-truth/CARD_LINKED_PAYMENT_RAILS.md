---
title: Card-Linked Payment Rails Source of Truth
status: stable
source_files:
  - packages/shared/card-linked-payments.ts
  - Backend Architecture/aether-backend/services/card_linked_payments/models.py
  - Backend Architecture/aether-backend/services/card_linked_payments/ingestion.py
  - Backend Architecture/aether-backend/services/card_linked_payments/gold.py
  - Backend Architecture/aether-backend/services/card_linked_payments/governance.py
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

## V1 pipeline (Bronze → Silver → Gold → Graph)

All modules live in `Backend Architecture/aether-backend/services/card_linked_payments/`.

1. **Ingestion** (`ingestion.py`, `normalizer.py`, `paymentscan.py`) — four
   sources with deterministic idempotency keys and per-source basis
   enforcement: provider webhooks (spend/settlement/refund/reversal only),
   on-chain observations (topup/funding/settlement only), SDK events
   (six card-context event types; SDK spend claims are downgraded to
   `unknown` and audited as `basis_warning`), and tenant imports.
   Blocked-PII fields raise at ingestion and are audited; region policy
   (`EU_RESTRICTED`/`UK_RESTRICTED`/`APAC_RESTRICTED`) and missing consent
   strip user-level attribution fields, also audited.
2. **Storage** (`repositories.py`, Alembic `20260713_card_linked_payments`) —
   durable stores for flows (UNIQUE `(tenant_id, idempotency_key)`),
   benchmarks, provider health, reconciliation records, and privacy audits.
3. **Silver** (`services/silver/projectors/card_linked_projector.py`) —
   registered LAST in the dispatcher chain; never the canonical-activity
   owner; writes `card_linked_flow_facts`.
4. **Gold** (`gold.py`) — entity economic activity (top-up and spend counted
   and summed separately, `basis="mixed"` when both are present), campaign
   outcomes, program/issuer benchmarks, and cluster features. Benchmark rows
   are excluded from every user-level rollup; nothing is model-training
   eligible. `materialize_gold` is invoked on demand and, when
   `AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` is on, periodically per tenant by
   the supervised payment-rail sync worker (`services/integrations/providers/
   payment_rails/sync_worker.py`) — the periodic hook the plane previously
   lacked (`card_linked_gold_materialized_total`).
5. **Reconciliation** (`ingestion.py::_try_reconcile`) — an on-chain top-up
   and a provider spend that share `wallet_address_hash` + card program link
   as `matched`; matching upgrades `reconciliation_state` only and never
   rewrites `basis`.
6. **Graph** (`graph_projector.py`) — vertices CardProgram/CardIssuer/
   PaymentNetwork/CardLinkedFlow/CardBenchmark; edges USED_PROVIDER, FUNDED,
   ATTRIBUTED_TO, CAME_FROM, PARTICIPATED_IN, OCCURRED_ON, USED_ASSET,
   RUNS_ON, ISSUED_BY, FOLLOWED_BY, INITIATED_OR_INFLUENCED. Every
   card-linked edge maps to `RelationshipLayer.EXCLUDED`: card-linked
   behavior is never deterministic identity-merge evidence. Benchmark rows
   are never projected.

## Surfaces

- Tenant API: `/v1/integrations/providers/payment-rails/card-linked/*`
  (catalog, flows, benchmarks, summary, campaign outcomes) — `routes.py`.
- Profile360: `/v1/profile/{id}/card-linked-activity`,
  `/v1/profile/{id}/economic/card-linked`, and
  `/v1/profile/{id}/drill/card-linked/{object_id}` — `profile_summary.py`
  builds the summary, filtered flows, entity story
  (campaign → provider → top-up → spends), provenance, and warnings.
- Campaign360: outcomes carry an explicit `attribution_basis`
  (`direct`/`temporal`/`probabilistic`/`benchmark_only`/`insufficient_evidence`);
  correlation is never presented as causality.
- Clusters (`clusters.py`) — review/intelligence cohorts only (program,
  top-up asset, funding chain, high-volume, repeat-spend,
  campaign-converted, issuer exposure, refund-loop-suspect,
  agent-influenced). Every cluster carries `enforcement: "never"`; the
  suspicious cohort's advisory says "stage for human investigation; never
  auto-deny."
- Kyber diagnostics (`diagnostics.py`, `kyber_routes.py`) —
  `/v1/admin/kyber/payment-rails/card-linked/{diagnostics,clusters,release-gate}`,
  operator-gated via `require_kyber_operator`: PaymentScan freshness,
  coverage by source/basis, basis-support-by-source, unmatched evidence,
  reconciliation conflicts, region/consent suppression counts, blocked-PII
  attempts, and basis-mislabeling warnings.

## Release gate

`governance.py::run_release_gate()` runs eleven fail-closed structural
checks (catalog seeded, basis validation, top-up/spend non-conflation,
blocked-PII rejection, flags default off, PaymentScan benchmark-only
handling, graph projection honesty, Profile360/Campaign360/Kyber surface
presence, source-of-truth docs present). The gated test suite fails the
build on any violation, and Kyber exposes the same results read-only.

## Canonical implementation points

- Shared contracts: `packages/shared/payment-catalog.ts` and `packages/shared/card-linked-payments.ts`.
- Backend semantics: `Backend Architecture/aether-backend/services/card_linked_payments/models.py`.
- Backend catalog: `Backend Architecture/aether-backend/services/payment_catalog/catalog.py`.
- Settings: `Backend Architecture/aether-backend/config/settings.py`.
