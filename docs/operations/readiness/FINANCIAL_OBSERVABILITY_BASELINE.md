---
title: Financial Observability Baseline Manifest
slug: readiness/financial-observability-baseline
section: operations
visibility: I
audience: [ops, architect, buyer, dev-senior]
status: beta
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 12
toc_depth: 3
source_files:
  - config/readiness/features/agentic-x402.yaml
  - config/readiness/features/card-linked-payments.yaml
  - config/readiness/features/payment-rail-observability.yaml
  - config/readiness/features/derivatives-intelligence.yaml
  - config/readiness/features/stablecoin-intelligence.yaml
  - config/readiness/features/interoperability-intelligence.yaml
  - config/readiness/features/financial-observability.yaml
  - docs/_generated/adapter-certification-matrix.json
  - services/api/main.py
  - services/api/config/settings.py
  - services/api/workers/runtime/specs.py
  - services/api/workers/runtime/consumer_specs.py
  - services/api/shared/plans/service_catalog.py
  - config/storage_policies.yaml
source_hashes:
  "config/readiness/features/agentic-x402.yaml": "sha256:ec203e0b0e415c0687560b3789381b3a3a299f3aa9191f7e80455457cb6fd6d1"
  "config/readiness/features/card-linked-payments.yaml": "sha256:9ca83bcafa071741b917fc51ed0aa254df4edd16e08a32f444b01062b413454a"
  "config/readiness/features/derivatives-intelligence.yaml": "sha256:c6f89bda2e4b5d3da437d52aa755fd32c80a0caad09601ff2b55f4472dac72b9"
  "config/readiness/features/financial-observability.yaml": "sha256:792afb8661dd2810ba228bf3a1794f921b12a14226404446772315b04e781d35"
  "config/readiness/features/interoperability-intelligence.yaml": "sha256:99f3bd9c8f300ddaf4acddc0f8fa1ca1398c40a85714f23ea838c9990b0b2293"
  "config/readiness/features/payment-rail-observability.yaml": "sha256:35f8b2e23e1f314c1019e034ecea6e4c18505b5b30f4dd306c5b7dd9c5aea608"
  "config/readiness/features/stablecoin-intelligence.yaml": "sha256:5c29163de8ee74d854a0b0d51f7dd96dcfc0d27a05f3bb1d3b82fd9b7549f14e"
  "config/storage_policies.yaml": "sha256:dd0170e28a9e22f6169ece57f2a05063d18f4b7a7e369dda182bbb5ef4f383e3"
  "docs/_generated/adapter-certification-matrix.json": "sha256:30c99f26bb77d405851ce92caa915c358988e140e290808a21d538f594fdc7de"
  "services/api/config/settings.py": "sha256:abde25ae3783e080355d11c81bafcfdff643240934ea50a0859e4fabdfb97441"
  "services/api/main.py": "sha256:e6dc26fdca74faf4ae6c7b43feb3ff53187739986eb4399fb1033bd7e263ab79"
  "services/api/shared/plans/service_catalog.py": "sha256:9c219b76d41c52f8691d2ed11f888c91f051768a58933174e0852d1741519a15"
  "services/api/workers/runtime/consumer_specs.py": "sha256:c78159537971b6e5eeb0ef86cd982118f47f34f82349e86f5f4536872137c5d5"
  "services/api/workers/runtime/specs.py": "sha256:440199aa711ba2c921b88bbd5df3a40659e05fafabba052149b4171acc68ac3e"
---

# Financial Observability Baseline Manifest

> W0 baseline: what exists, where it is promoted, what it is waiting on, and who owns it.

This is the reconciliation record for the financial-observability work order. It
is a snapshot, not a live dashboard. It was taken on 2026-10-29 from a working
tree based on `origin/development` at `50bb9ec10`, including the readiness-record
corrections in the same change. `docs/_generated/FEATURE-READINESS.md` remains
the generated score; this page records the branch and evidence reconciliation
behind that score.

The work-order boundary applies throughout: Aether observes, normalizes,
reconciles, and presents authorized financial evidence. It does not process
payments, issue cards, custody assets, trade, or execute.

## 1. Snapshot and branch reconciliation

| Ref | Commit | Date | Note |
|---|---|---|---|
| `origin/main` | `c83924adf` | 2026-10-16 | Stripe webhook configuration fix (#812) |
| `origin/staging` | `2c6a83195` | 2026-10-16 | Promote development to staging (#814) |
| `origin/development` | `50bb9ec10` | 2026-10-26 | Current development head (#837) |

Promotions are squash/tree snapshots, not fast-forwards. `main` is **not** an
ancestor of `staging` or `development`, so ancestry alone gives false answers to
"is this promoted?"

| Promotion | Commit | Date | Tree relation |
|---|---|---|---|
| Development to staging (#783) | `386e98f8c` | 2026-10-15 | Tree `c8d2d5ad5` |
| Staging to main (#784) | `a8c1f4f6e` | 2026-10-15 | Same tree `c8d2d5ad5` |
| Development to staging (#807) | `fd436b7a1` | 2026-10-16 | Staging refresh |
| Development to staging (#814) | `2c6a83195` | 2026-10-16 | Current staging |
| Development only (#817, #830, #831) | `dd878ce34`, `3d6a9ef77`, `aabdba222` | 2026-10-22/23 | Not promoted |

Content is present in `main` even where the commit is not an ancestor: #765
(`37fd04806`) is promoted through the identical #783/#784 trees. Use tree/blob
comparison, not `git merge-base --is-ancestor`, for promotion claims.

Two-dot tree divergence at this snapshot:

| Pair | Files changed | Insertions | Deletions |
|---|--:|--:|--:|
| `main` to `staging` | 596 | 32,541 | 6,351 |
| `staging` to `development` | 603 | 214,326 | 5,250 |
| `main` to `development` | 1,083 | 245,515 | 10,249 |

These counts are whole-repository drift, not financial-only drift. The practical
consequence is that a capability can be "in main" by content while its promoting
commit is absent from main's ancestry.

## 2. Capability manifest

Scores below are the migration-derived readiness model at this snapshot:
implementation percent, productionization percent, repository ceiling, and
activation state. They are proxies. In particular, the card-linked score is
conservative relative to its code and tests (§4).

| Capability | Code on | Readiness | Activation | Owner |
|---|---|---|---|---|
| Payment rail observability | main, staging, development | 80/50, `RUNTIME_INTEGRATED`, achieved | `LIVE_DATA_WAITING` | financial-platform |
| Stripe commerce evidence | main, staging, development | Part of payment-rail record | Provider credential / live data | financial-platform |
| Card-linked payment rails | main, staging, development | 60/25, `CODE_COMPLETE`, not achieved | `CREDENTIAL_WAITING` | financial-platform |
| Derivatives intelligence | main, staging, development | 80/50, `RUNTIME_INTEGRATED`, achieved | `INFRASTRUCTURE_WAITING` | financial-platform |
| Stablecoin intelligence | main, staging, development | 80/50, `RUNTIME_INTEGRATED`, achieved | `LIVE_DATA_WAITING` | financial-platform |
| Interoperability intelligence | main, staging, development | 80/50, `RUNTIME_INTEGRATED`, achieved | `INFRASTRUCTURE_WAITING` | financial-platform |
| Agentic x402 and agent lifecycle | main, staging, development | 100/100, `VERIFIED`, achieved | `ENVIRONMENT_VALIDATION_PENDING` | agent-platform |
| Wallet ownership evidence | main, staging, development | No dedicated readiness record | Staging validation | platform / identity |
| Prediction markets | development only | No readiness record | Provider credentials, promotion | Unassigned |
| Financial credential turnkey | main, staging, development | 100/100, `CREDENTIAL_TURNKEY`, achieved | `CREDENTIAL_WAITING` | financial-platform |
| Provider certification | main, staging, development | 28 providers, all `credential_waiting` | Provider credentials | financial-platform |

### 2.1 Payment rail observability

- **Implementation evidence:** routes under `/v1/integrations/providers` and
  `/v1/integrations/webhooks/payment-rails`; Kyber diagnostics under
  `/v1/admin/kyber/payment-rails`; `payment_rail_sync`,
  `payment_canonical_repair`, `payment_alert_eval`, and
  `x402_settlement_reconciliation` workers; Silver/Gold storage policies.
- **Stripe:** `payment_intent.succeeded` normalizes only with a verified
  signature; the webhook returns 503 rather than accepting unsigned traffic when
  the secret or SDK is absent (#812). Reconciliation requires exact order
  reference, amount, currency, and completion.
- **Limits:** no live provider data has flowed through the plane; every rollout
  flag defaults off. Card and payout evidence remain observation-only.
- **Owner:** `financial-platform`, operated by `platform-ops`.

### 2.2 Card-linked payment rails

- **Implementation evidence:** card-linked routes under
  `/v1/integrations/providers/payment-rails/card-linked`; Kyber diagnostics under
  `/v1/admin/kyber/payment-rails/card-linked`; graph-projection operator plane
  under `/v1/kyber/card-linked/graph-projection`; migration
  `20260713_card_linked_payments`; PII/region/consent gates; idempotent
  tenant-scoped flow upserts; Silver projector and `card_linked_graph_outbox`
  worker; Aether, Campaign360, and Kyber read surfaces.
- **Tests:** `services/api/tests/card_linked_payments/` passes (31 tests),
  including cross-tenant isolation.
- **Recorded gap:** a distinct service-catalog entry, plan entitlement resolver,
  and durable usage meter are not wired (Section 6 W3). The current record's
  `persistence-and-migrations` and `authorization-and-tenant-isolation` controls
  read false even though the migration and isolation tests exist; the score is
  deliberately left conservative until W3 re-models the commercial controls.
- **Activation:** provider credentials. All ten card-linked flags default off,
  except the EU/APAC restriction and provider-PII block, which default on.
- **Owner:** `financial-platform`, operated by `platform-ops`.

### 2.3 Derivatives intelligence

- **Implementation evidence:** `/v1/derivatives` and `/v1/derivatives/runtime`
  reads; Kyber ops under `/v1/admin/kyber/derivatives`; venue sweep and position
  materializer workers; derivatives storage families; Aether and Kyber pages.
- **Limits:** the shared scorecard records that the entitlement guard, usage
  meter sink, and graph mutations are not wired, and the materializer has never
  run on venue data. Observation-only; no execution capability.
- **Activation:** venue credentials and infrastructure.
- **Owner:** `financial-platform`, operated by `platform-ops`.

### 2.4 Stablecoin intelligence

- **Implementation evidence:** `/v1/stablecoins` reads and Kyber ops; provider
  polling worker; stablecoin storage families; Aether and Kyber pages; an
  opt-in usage-metering flag.
- **Limits:** billing-plan mapping, quota enforcement, and overage warning
  surfaces are not wired; all rollout flags default off.
- **Activation:** live provider data and credentials.
- **Owner:** `financial-platform`, operated by `platform-ops`.

### 2.5 Interoperability intelligence

- **Implementation evidence:** `/v1/interoperability` reads and
  `/v1/admin/kyber/interop` ops; `interop_scan` worker; interop storage and
  certification entries for seven adapters.
- **Limits:** observation-only; Aether never relays, routes, or recovers
  messages. Infrastructure dependencies remain external.
- **Activation:** infrastructure and credentials.
- **Owner:** `financial-platform`, operated by `platform-ops`.

### 2.6 Agentic x402 and agent lifecycle

- **Implementation evidence:** `x402-lifecycle-projection` consumes server-owned
  commerce topics; the ingestion worker projects validated SDK lifecycle
  observations; the agent execution consumer applies source-authority rules.
  Repositories are tenant-scoped; eight lifecycle consumer tests pin
  registration and authority behavior.
- **Correction in this change:** the readiness record previously said no
  consumer existed and scored runtime wiring false. It now records 100%
  implementation and an `ENVIRONMENT_VALIDATION_PENDING` activation because no
  running deployment has exercised the consumers.
- **Open question:** which mapper-owned tables populate, and how the agent
  consumer overlaps the separate `AgentExecutionProjector` Silver path.
- **Owner:** `agent-platform`, operated by `platform-ops`.

### 2.7 Wallet ownership evidence

- **Implementation evidence:** wallet challenge and verify routes under
  `/v1/identity/verification/wallet/challenges`; wallet signal and evidence
  types in identity resolution; no dedicated rollout flag.
- **Limits:** there is no dedicated readiness record or scorecard area for wallet
  evidence. Source authority, evidence review, and unresolved-identity limits
  exist; adversarial financial proof remains open. Requires the identity
  verification token key in hosted environments.
- **Owner:** `platform` / `identity`, operated by `platform-ops`.

### 2.8 Prediction markets

- **Implementation evidence:** development-only `services/api/value/prediction_markets/`,
  `/v1/prediction-markets` normalize/read routes, Polymarket and Kalshi
  normalizers, and migration `20261023_prediction_market_observations` (#817,
  #830).
- **Limits:** not on main or staging; no readiness feature record, no worker, no
  Aether/Kyber page, no service-catalog or meter entry. Both adapters are
  `credential_waiting` and accept caller-submitted payloads only; live polling
  and order execution are unsupported.
- **Activation:** promotion, credentials, and an assigned owner.
- **Owner:** unassigned; proposed `financial-platform`.

### 2.9 Financial credential turnkey

- **Implementation evidence:** `scripts/financial_credential_readiness.py`;
  seven payment/stablecoin providers are ready at `credential_waiting`;
  operational invariants pass (single Alembic head, receipt and endpoint
  uniqueness migrations, payment worker roles and flags).
- **Limit:** "ready" means the code and configuration are ready for credentials,
  not that a provider connection has been certified. Derivatives, prediction
  markets, and interop are outside this seven-provider financial set.
- **Owner:** `financial-platform`, operated by `platform-ops`.

### 2.10 Provider certification

- **Implementation evidence:** generated matrix at
  `docs/_generated/adapter-certification-matrix.json`.
- **Current state:** 28 first-release providers, all `credential_waiting`, zero
  live. Domains: communications 8, derivatives 4, interop 7, payments 5,
  prediction_market 2, stablecoin_chain 2. No import errors.
- **Rule:** `credential_waiting` is not production-ready. The generated matrix is
  authoritative for counts and per-provider state; the guide no longer hardcodes
  a provider count.

## 3. Surface inventory

### 3.1 Rollout flags

All flagship economic flags default off except the card-linked restriction and
PII blocks, which default on.

| Domain | Flags |
|---|---|
| Payment rails | `AETHER_PAYMENT_RAILS_ENABLED`, `AETHER_PROVIDER_{PRIVY,STRIPE,COINBASE,MOONPAY,BRIDGE}_ENABLED`, `KYBER_PAYMENT_RAILS_ENABLED`, webhook consent/rate-limit/quarantine, canonical outbox/repair, credential authority, usage metering, alert evaluation |
| Card-linked | `AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED`, `AETHER_PAYMENTSCAN_{CATALOG,BENCHMARKS}_ENABLED`, `AETHER_CARD_LINKED_{PROFILE360,CAMPAIGN_ATTRIBUTION,CLUSTERING}_ENABLED`, `KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED`, `AETHER_CARD_LINKED_{EU,APAC}_RESTRICTED_MODE` (default on), `AETHER_CARD_LINKED_PROVIDER_PII_BLOCK` (default on) |
| Derivatives | `AETHER_DERIVATIVES_{RUNTIME,RECONCILIATION,PNL,PROFILE360,API,NOESIS}_ENABLED`, `KYBER_DERIVATIVES_OPS_ENABLED` |
| Stablecoin | `AETHER_STABLECOIN_{INTELLIGENCE,INGESTION,VALUATION,FLOWS,PROFILE360,API,NOESIS,KILL_SWITCH,USAGE_METERING}_ENABLED` |
| Interop | `AETHER_INTEROP_{INGESTION,ADAPTERS,LAYERZERO,GRAPH,PROFILE360,API,NOESIS}_ENABLED`, `KYBER_INTEROP_OPS_ENABLED` |
| Prediction | `AETHER_PREDICTION_MARKET_INGESTION_ENABLED`, `AETHER_PROVIDER_{POLYMARKET,KALSHI}_ENABLED` |
| x402 graph | `IG_X402_LAYER`; `COMMERCE_CONTROL_PLANE_ENABLED` defaults on |

### 3.2 Routes

| Mount | Prefix |
|---|---|
| Payment rails | `/v1/integrations/providers`, `/v1/integrations/webhooks/payment-rails`, `/v1/admin/kyber/payment-rails` |
| Card-linked | `/v1/integrations/providers/payment-rails/card-linked`, `/v1/admin/kyber/payment-rails/card-linked`, `/v1/kyber/card-linked/graph-projection` |
| Derivatives | `/v1/derivatives`, `/v1/derivatives/runtime`, `/v1/admin/kyber/derivatives` |
| Stablecoin | `/v1/stablecoins`, `/v1/admin/kyber/stablecoins` |
| Interop | `/v1/interoperability`, `/v1/admin/kyber/interop` |
| Prediction markets | `/v1/prediction-markets` (development only) |
| x402 | `/v1/x402` |
| Wallet | `/v1/identity/verification/wallet/challenges` |

Card-linked and prediction routes fail closed behind disabled flags. The
card-linked graph-projection operator plane is mounted unconditionally but each
route re-checks the Kyber flag.

### 3.3 Workers

| Worker | Domain |
|---|---|
| `payment_rail_sync` | payment rails / card-linked Gold |
| `payment_canonical_repair` | payment rails |
| `payment_alert_eval` | payment rails |
| `x402_settlement_reconciliation` | x402 |
| `card_linked_graph_outbox` | card-linked graph projection |
| `stablecoin_provider_polling` | stablecoin |
| `interop_scan` | interoperability |
| `derivatives_venue_sweep` | derivatives |
| `derivatives_position_materializer` | derivatives |
| `x402-lifecycle-projection` (consumer) | x402 / agent lifecycle |
| `agent_marketplace_graph_outbox`, `agent_marketplace_catalog_observer` | agent marketplace |

No prediction-market worker exists.

### 3.4 Commercial path

- `service_catalog.py` includes `Rail-Watch` over
  `/v1/integrations/providers/*`, `Stablecoin Intelligence` over
  `/v1/stablecoins/*`, `Derivatives Intelligence` over
  `/v1/derivatives/runtime/*`, and `Interoperability Intelligence` over
  `/v1/interoperability/*`.
- There is no distinct card-linked entry and no `/v1/prediction-markets/*`
  entry. `Prediction` in the catalog is `/v1/ml/*` model inference, not
  prediction markets.
- Payment rails and stablecoin have usage-metering flags. Card-linked and
  prediction markets have no meter. Derivatives has a guard module but the
  shared scorecard records its entitlement resolver and meter sink as unwired.

### 3.5 Storage and UI

- Storage policies exist for `card_linked_*` (audit, benchmarks, flow facts,
  flows, provider health, reconciliation), `prediction_market_observations`,
  `derivatives_*`, `stablecoin_*`, and `silver_x402_flow_facts`;
  `check_storage_policies.py` passes 482 checks.
- Aether reads: payment rails (including card-linked section), Campaign360
  card-linked outcomes, derivatives, stablecoins, interop, agent 360. Kyber
  reads: payment rails and card-linked diagnostics, derivatives, stablecoins,
  interop, agent telemetry. No prediction-market page exists.

## 4. Discrepancies and dispositions

| Finding | Disposition |
|---|---|
| `agentic-x402.yaml` said no consumer calls the mappers and scored runtime wiring false | Corrected: consumers are registered and tested; record is now VERIFIED with `ENVIRONMENT_VALIDATION_PENDING` for the missing deployment run |
| Card-linked readiness controls read persistence and tenant isolation false | Left conservative for W0; evidence exists (migration, 31 passing tests) and the record now says so. W3 re-models commercial controls |
| Card-linked `remaining_after_ceiling` claimed repo-controlled credentials | Corrected: achieved is now false, remaining work lists the W3 catalog/entitlement/meter, and credentials remain an activation blocker |
| Prediction markets have no readiness record, worker, UI, catalog entry, or owner | Recorded as a gap; W8/W9 planning must not assume it is baseline capability |
| Provider guide hardcoded "28 providers" | Replaced with generated-matrix authority |
| Branch ancestry gives false promotion answers | Documented; use tree/blob comparison |
| Local `main` was stale | Snapshot uses fetched `origin/*` refs |

No capability is marked provider-validated in this baseline. Agentic x402 is
repository-`VERIFIED` but not deployment-validated. Financial observability is
credential-turnkey: its code and configuration invariants pass, but it has no
live credentials.

## 5. Gate evidence

Run from the working tree at `50bb9ec10` plus these edits, using
`.venv/bin/python`:

| Gate | Result |
|---|---|
| `validate_readiness_model.py` | 33 records, OK |
| `financial_credential_readiness.py` | 7 providers ready at `credential_waiting`; all operational invariants pass |
| `validate_settings_flags.py` | 425 env-backed fields read |
| `validate_meter_names.py` | OK |
| `validate_contracts.py` | 8 checks, 416 events |
| `validate_backend_reachability.py` | OK, 73 allowed unreachable modules |
| `check_storage_policies.py` | PASS, 482 checks, 486 resource types |
| Lifecycle consumer tests | 8 passed |
| Card-linked tests | 31 passed |
| `docs-check` | Generator, idempotency, frontmatter, and drift components pass; the command's clean-tree gate reports only the intended uncommitted generated/synced diff |

## 6. Open decisions

1. Whether card-linked becomes a distinct commercial SKU or remains bundled
   under `Rail-Watch` (W3).
2. Which team owns prediction markets, and whether to add a readiness record,
   worker, and UI before or after promotion (W8/W9).
3. What external evidence counts as provider certification, and who signs it
   (W5/W8).
4. The staging validation order across payment rails, card-linked, derivatives,
   stablecoin, and x402.
5. Whether wallet evidence gets its own readiness record or remains a sub-gate
   of identity resolution.

## 7. Next slice

The next step is W1 per the approved sequence. This baseline does not authorize
enabling any flag, connecting a provider, or claiming staging/production
readiness.
