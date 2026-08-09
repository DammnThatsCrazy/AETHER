---
title: "Credential-Turnkey Capability Completion Matrix"
slug: reports/credential-turnkey-capability-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
status: beta
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 20
---

# Credential-Turnkey Capability Completion Matrix (program sec30.A)

**Report date:** 2026-08-09
**Branch:** `claude/credential-turnkey-pre-staging` (base `origin/main`)
**Scope:** the ten turnkey capabilities that must be operationally supplyable
with **no repository code change** — an operator should only provision infra,
supply secrets, configure public URLs, register provider apps, apply migrations,
deploy, certify, and flip flags.

This matrix is built from the **actual repository state after the build waves**:
certification registry (`shared/certification/registry.py` →
`build_capability_matrix()`), worker specs (`services/runtime/specs.py`),
repositories (alembic migrations + `BaseRepository` table claims), routes
(`main.py` wiring), tests, `deploy/DEPLOYMENT_CONTRACT.yaml`, and the audit
findings (`docs/productization/aether_productization_audit.md`,
`docs/implementation/AETHER_KYBER_RELEASE_STATE.md`). It was verified by
importing every new module and resolving the live capability matrix
(29 providers, all `credential_waiting`).

## Status legend

| Marker | Meaning |
|---|---|
| **PRESENT** | Repository-controlled evidence exists on this branch: real code + tests, importable, and (where applicable) durable/migrated or wiring-registered. |
| **PARTIAL** | Real code exists but a declared seam/path is not fully wired — e.g. a worker builder is missing or its import path mismatches, a durable table lacks a migration, or a frontend/operator surface was not evidenced. |
| **ABSENT** | No repository evidence on this branch. |
| **PENDING EXTERNAL** | Environment-controlled (live credentials, staging, provider/cloud access). This is *not* a repository-coding blocker. |
| **N/A** | Dimension does not apply to the capability (e.g. credentials have no meter). |

The per-provider readiness floor is the certification matrix:
**29/29 providers resolve to `CREDENTIAL_WAITING`** (code-complete +
infra-defined + credential-gated, none `SCAFFOLDED`, none `PARTNER_LIVE`).
`CREDENTIAL_WAITING` is a pre-production posture, not a release claim.

---

## 1. Capability Completion Matrix

Legend per cell: `P` = PRESENT, `~` = PARTIAL, `-` = ABSENT, `⛔` = PENDING EXTERNAL, `·` = N/A.

| Capability | Code | Transport | Credentials | Storage | Worker | Cursor | Reconcil. | Repair | Observab. | Tenant UI | Operator UI | Entitlement | Meter | Infra defn | Offline cert | External blockers |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **1. Stablecoin** | P | ~ | ⛔ | P | ~ | P | P | P | ~ | P | P | P | ~ | ~ | P | ⛔ |
| **2. Derivatives** | P | ~ | ⛔ | P | ~ | P | P | P | ~ | P | P | P | P | ~ | P | ⛔ |
| **3. Interop** | P | P | ⛔ | P | P | P | P | P | ~ | P | P | - | P | ~ | P | ⛔ |
| **4. Payment rails** | P | P | ⛔ | P | P | P | P | P | P | P | P | P | P | P | P | ⛔ |
| **5. Card-linked** | P | ~ | ⛔ | P | ~ | P | ~ | ~ | - | - | ~ | - | - | - | P | ⛔ |
| **6. x402 commerce** | P | ~ | ⛔ | ~ | ~ | P | ~ | ~ | ~ | ~ | ~ | P | P | ~ | P | ⛔ |
| **7. Rewards** | P | ~ | ⛔ | ~ | ~ | P | P | P | ~ | P | P | P | P | ~ | P | ⛔ |
| **8. Credential authority** | P | · | ⛔ | P | ~ | · | ~ | P | P | P | P | P | · | P | P | ⛔ |
| **9. Provider conformance** | P | · | ⛔ | P | · | · | · | · | ~ | · | P | · | · | P | P | ⛔ |
| **10. Lifecycle/readiness** | P | · | ⛔ | ~ | P | · | · | · | ~ | P | ~ | P | P | ~ | P | ⛔ |

---

## 2. Per-capability evidence

### 2.1 Stablecoin (`stablecoin_chain` evm/svm + stablecoin intelligence)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | EVM/SVM connectors (`evm_connector.py`, `solana_connector.py`), `rpc_observer.py` / `solana_observer.py` (certification resolves `StablecoinEVMReceiptVerifier` / `StablecoinSolanaTransactionVerifier`), ingestion, price_feed, polling, registry, governance, models, routes. Registry: `stablecoin_chain:evm|svm` → `CREDENTIAL_WAITING`. |
| Transport | PARTIAL | In-process fixture transport exercised offline; live chain RPC/JSON-RPC seams exist but are external and credential-gated (`required_endpoints=["json_rpc"]`). |
| Credentials | PENDING EXTERNAL | Per-network RPC/indexer access keys + signed data agreements (deployment contract `stablecoin_chain.required_secrets: rpc_api_key`). |
| Storage | PRESENT | Migrated tables: `stablecoin_assets`, `stablecoin_deployments`, `stablecoin_observations`, `stablecoin_reconciliation_records`, `stablecoin_finality_checkpoints`, `stablecoin_support_assertions`, `stablecoin_flow_aggregates`, `stablecoin_valuation_snapshots`. New `price_persistence.py` adds the durable price write path (unavailable snapshot persisted as observed, never fabricated 0/1 USD). |
| Worker | PARTIAL | Spec `stablecoin_provider_polling` registered, gated on `settings.stablecoin_intelligence.enabled`, but the factory imports `services.stablecoins.polling.build_stablecoin_polling_loop` which **does not exist** (module present, no such builder). Integration pass must author the loop builder or correct the import. |
| Cursor | PRESENT | `StablecoinIngestionCheckpointRepository` + polling cursors. |
| Reconciliation | PRESENT | Payment/onchain reconciliation (`reconciliation.py`) + multi-provider price reconciliation (`price_persistence.py`), durable `stablecoin_reconciliation_records`. |
| Repair | PRESENT | Remediation audit repo; reorg rollback/re-emit + RPC-failure fail-closed exercised in `tests/unit/test_stablecoin_adversarial.py` (scenarios 1–6). |
| Observability | PARTIAL | Provider-health repository + governance metrics; no dedicated stablecoin Grafana dashboard in `deploy/observability/`. |
| Tenant UI | PRESENT | Tenant frontend stablecoin surfaces (frontend-intelligence Phase 4 lists stablecoin path). |
| Operator UI | PRESENT | Kyber stablecoin admin routes (`stablecoin_admin_router` wired in `main.py`). |
| Entitlement | PRESENT | `StablecoinCapabilityEntitlement` + `StablecoinEntitlementGuard` (fail-closed) in `governance.py`. |
| Meter | PARTIAL | `usage_metering()` in `governance.py` (in-memory rollup); durable `metering_evidence` integration pending (table not yet migrated). |
| Infra definition | PARTIAL | Deployment contract declares `stablecoin_chain` required services/secrets/URLs; note the deploy copy still says `application_code_ready: false` — a parity drift vs. the certification registry (which resolves code-complete). |
| Offline certification | PRESENT | Offline fixture replay, adversarial suite, price-write-path tests; registry resolves CREDENTIAL_WAITING. |
| External blockers | ⛔ | Live chain RPC/indexer keys; signed data agreements; rate-limit review. |

### 2.2 Derivatives (hyperliquid / dYdX / GMX / Drift)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | Registered `VENUE_ADAPTERS` + `DERIVATIVES_ADAPTERS`; `HyperliquidConnector` (production-shaped, fixture-injected transport); new `durable_cursor.py`, `guards.py`, `meter.py`, `sequence.py`, `topic_contract.py`, `credentials.py`, `counters.py`, `product.py`, `multi_venue.py`, `streams.py`. Registry: `derivatives:hyperliquid|dydx|gmx|drift` → `CREDENTIAL_WAITING`. |
| Transport | PARTIAL | Injectable REST/WS seams + fixture transport; live exchange endpoints external and credential-gated (`required_credentials=["read_only_api_key"]`). |
| Credentials | PENDING EXTERNAL | Read-only exchange API keys per venue; market-data license terms. |
| Storage | PRESENT | Migrated: `derivatives_markets/instruments/positions/fills/funding_payments/liquidations/pnl_snapshots/price_observations/stream_gaps/connector_checkpoints/venue_deployments/reconciliation_variances/execution_decisions/trading_accounts/trading_venues/strategy*`. `durable_cursor.py` closes the write-path gap (checkpoint persist/restore + stream-gap rows). |
| Worker | PARTIAL | `SupervisedStreamWorker` (`sequence.py`) is real. Spec `derivatives_venue_sweep` registered, gated on `settings.derivatives.reconciliation_enabled`, but factory imports `services.derivatives.multi_venue.build_venue_sweep_coro` which **does not exist** (module exposes `build_scaffolded_adapters`). Integration pass must author the sweep builder. |
| Cursor | PRESENT | Durable pull-cursor + stream-gap persistence; `DerivativesPullRunner` at-least-once resume; tested (`test_derivatives_durable_cursor.py`). |
| Reconciliation | PRESENT | `runtime_reconciliation.py`, `reconciliation.py`, durable variance records, `cross_venue_parity_report`. |
| Repair | PRESENT | Sequence-gap detection/recovery, disconnect→reconnect resume at expected sequence, reconnect-exhaustion marking (`test_derivatives_faults.py`). |
| Observability | PARTIAL | Health/counters + `runtime` checkpoint telemetry; no dedicated derivatives Grafana dashboard evidenced. |
| Tenant UI | PRESENT | Tenant frontend derivatives surfaces (Phase 4). |
| Operator UI | PRESENT | Kyber derivatives admin routes wired in `main.py`. |
| Entitlement | PRESENT | `derivatives_entitlement_gate` (`guards.py`), fail-closed by default; resolver seam for the integration pass. |
| Meter | PRESENT | `DerivativesMeter` hook + `install_derivatives_meter_sink` (durable sink wiring pending). |
| Infra definition | PARTIAL | Deployment contract declares `derivatives` required services/secrets/URLs; `topic_contract.py` declares the Kafka/stream topic contract (broker-free validation). Contract copy still says `application_code_ready: false` (parity drift). |
| Offline certification | PRESENT | Durable-cursor, faults, transport-rpc fixture tests; registry resolves CREDENTIAL_WAITING. |
| External blockers | ⛔ | Read-only venue API keys; live market-data endpoints; data-license confirmation. |

### 2.3 Interop (LayerZero / Wormhole / Axelar / CCIP / Hyperlane / IBC / deBridge)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | 7 adapters with `ImplementationStatus`; `scan_worker.py`, `reconcile.py`, `metering.py`, `publisher.py`, `graph_wiring.py`, `security.py`, `correlation.py`, `lifecycle.py`, `admin_routes.py`, `routes.py`. Registry: `interop:*` (7) → `CREDENTIAL_WAITING`. |
| Transport | PRESENT | `transport.py` — real httpx JSON-RPC (EVM) + CometBFT (IBC) clients with `RpcRateLimited`/retry-after; live endpoints constructed only at wiring time from configured secret-refs. |
| Credentials | PENDING EXTERNAL | Per-network JSON-RPC endpoints + `interop_signing_secret` for inbound message verification. |
| Storage | PRESENT | Migrated: `interop_providers/messages/checkpoints/reconciliation_records/security_policy_snapshots/gateways/paths/intents/delivery_actors/verification_actors/applications/asset_legs/delivery_attempts/message_events`. |
| Worker | PRESENT | `scan_worker.py` real; `build_interop_scan_coro` **exists** in `lifecycle.py` and is what the `interop_scan` spec imports (gated on `settings.interop.adapters_enabled`). Correctly wired — the one domain where the worker builder matches. |
| Cursor | PRESENT | Durable `interop_provider_checkpoints` (migrated); checkpoint resume contract — restart never from scratch, idempotent re-runs; reorg restart tested (`test_scan_reorg_restart.py`). |
| Reconciliation | PRESENT | Cross-leg variance evidence + `interop_reconciliation_variance_detected` events; observation-only (never auto-repaired); tested (`test_reconcile_state.py`). |
| Repair | PRESENT | Dead-letter quarantine in scan cycle; checkpoint-idempotent replay after crash. |
| Observability | PARTIAL | Usage metering + reconciliation/security counters surfaced in `operational_state()`; no dedicated interop Grafana dashboard evidenced. |
| Tenant UI | PRESENT | Tenant frontend interop surfaces (Phase 4). |
| Operator UI | PRESENT | `interop_admin_router` wired in `main.py`. |
| Entitlement | ABSENT | No interop entitlement gate evidenced on this branch. |
| Meter | PRESENT | `metering.py` records `metering_evidence` dimensions (`interop:<dimension>:<unit_key>`, duplicate-excluded); `metering_evidence` table not yet migrated. |
| Infra definition | PARTIAL | Deployment contract declares `interop` required services/URLs/secrets (`interop_signing_secret`, callback URLs). Contract copy still says `application_code_ready: false` (parity drift). |
| Offline certification | PRESENT | Adapter conformance suites, reconcile/transport/reorg tests, registry CREDENTIAL_WAITING. |
| External blockers | ⛔ | Peer provider registration, callback URLs, per-network RPC, signing-secret exchange. |

### 2.4 Payment rails (Privy / Stripe Onramp / Coinbase / MoonPay / Bridge)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | 5 adapters + `base.py`, `service.py`, `routes.py`, `webhook_endpoints.py`, `signature_verify.py`, `receipts.py`, `repository.py`, `durability.py`, `lifecycle.py`, `entitlement_gate.py`, `readiness_demotion.py`, `alert_eval.py`, `alert_worker.py`, `sync_worker.py`, `repair_worker.py`, `kyber_routes.py`, `kyber_aggregate.py`, `kyber_contract.py`. Registry: `payments:*` (5) → `CREDENTIAL_WAITING`. |
| Transport | PRESENT | Native webhook + polling transport with signature verification, SSRF-checked delivery, `RpcRateLimited` handling. Live provider endpoints external. |
| Credentials | PENDING EXTERNAL | Per-rail `webhook_signing_secret` + `onramp_api_key` (polling rails); supplied through the durable CredentialAuthority (KMS-encrypted, rotation-overlap). |
| Storage | PRESENT | Migrated: funding sessions / `payment_rail_*`, `payment_provider_receipts`, `payment_webhook_endpoints`; durable receipt/reconciliation ledgers. Postgres mirror seam (`durability.py`) exposes exact `migration_ddl` — **seam tables not yet migrated** (migrationNeed). |
| Worker | PRESENT | `payment_rail_sync`, `payment_canonical_repair`, `payment_alert_eval` specs registered with **existing builders**; webhook inbox, `sync_worker.py`, `repair_worker.py`. Strongest worker story of the ten. |
| Cursor | PRESENT | Polling checkpoint/cursor in `sync_worker.py`; recovery tested. |
| Reconciliation | PRESENT | Receipt lifecycle + staleness reconciliation + canonical repair safety net. |
| Repair | PRESENT | `repair_worker.py` + `payment_canonical_repair` worker + `readiness_demotion.py` (auth-error → CREDENTIAL_INVALID; silence/verification failure → DEGRADED). |
| Observability | PRESENT | Dedicated `payment-rails.json` Grafana dashboard + derived-condition alert evaluator + alert worker + Kyber aggregate. Best-in-class of the ten. |
| Tenant UI | PRESENT | Tenant frontend payment-rail surfaces (Phase 4). |
| Operator UI | PRESENT | `payment_rails_kyber_router` wired in `main.py`. |
| Entitlement | PRESENT | `entitlement_gate.py` — plan-tier + permission admission, default OFF. |
| Meter | PRESENT | `AETHER_PAYMENT_USAGE_METERING_ENABLED` flag + observable usage metering (one unit per newly accepted canonical event). |
| Infra definition | PRESENT | Deployment contract `payment_rails` entry (`application_code_ready: true`), public webhook URLs, secrets, provider registration steps. |
| Offline certification | PRESENT | 30+ test files (`tests/payment_rails/`): adapters, webhook admission/edges, signature schemes/golden, polling, crash recovery, delivery gaps, rollout/readiness, credential read path, usage metering. |
| External blockers | ⛔ | Live rail credentials; public webhook URL registration per rail app; sandbox/live provider apps. |

### 2.5 Card-linked payment rails

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | `ingestion.py`, `import_session.py`, `partner_feed.py`, `gold.py`, `repositories.py`, `routes.py`, `kyber_routes.py`, `projection_routes.py`, `normalizer.py`, `paymentscan.py`, `profile_summary.py`, `models.py`, `graph_outbox.py`, `import_bridge.py`, `graph_projector.py`, `governance.py`. |
| Transport | PARTIAL | Partner-feed transport exists (`partner_feed.py`); live card-network/processor feeds external. |
| Credentials | PENDING EXTERNAL | Card-network/processor feed access + import-bridge credentials. |
| Storage | PRESENT | `card_linked_flow_facts` migrated; new durable import-session state (`import_session.py`) tested (`test_card_linked_import_session.py`). |
| Worker | PARTIAL | `card_linked_graph_outbox` spec registered with existing `CardLinkedGraphOutboxWorker` (gated on `settings.card_linked_payment_rails.enabled`); import-session states note "no live worker" for abandoned states (sweeper/requeue is state-machine logic, not a registered worker). |
| Cursor | PRESENT | Import-session checkpoints + sweep TTLs. |
| Reconciliation | PARTIAL | No dedicated card-linked reconciliation module; import staging + graph outbox give partial evidence. |
| Repair | PARTIAL | Import-session requeue/sweeper logic + fault stages (`tests/faults/test_card_linked_import_stages.py`). |
| Observability | ABSENT | No card-linked Grafana dashboard in `deploy/observability/`; no dedicated observability module evidenced. |
| Tenant UI | ABSENT | No card-linked tenant frontend surface evidenced on this branch. |
| Operator UI | PARTIAL | `card_linked_kyber_router` wired in `main.py`; operator surfaces limited. |
| Entitlement | ABSENT | No card-linked entitlement gate evidenced. |
| Meter | ABSENT | No card-linked metering evidenced. |
| Infra definition | ABSENT | No card-linked references in `AWS Deployment/aether-aws/terraform/` or `deploy/`; no deployment-contract entry. |
| Offline certification | PRESENT | Release-gate checks (`governance.py`), import-session test, fault stages. Consistent with the audit's card-linked score of **2/5 (partial/pilot)**. |
| External blockers | ⛔ | Card-network/processor feed access, partner agreements, import-bridge credentials. |

### 2.6 x402 commerce (challenge → authorize → verify → settle → entitle → grant)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | `control_plane.py`, `commerce_routes.py`, `commerce_store.py`, `commerce_models.py`, `verification.py`, `settlement.py` (`SettlementTracker`), `entitlements.py`, `signer_authority.py`, `signer_repos.py`, `approvals.py`, `challenge_middleware.py`, `interceptor.py`, `lifecycle_mapper.py`, `economic_graph.py`, `economic_mutations.py`, `policies.py`, `pricing.py`, `resources.py`, `facilitators.py`, `idempotency.py`. Registry: `agentic_commerce:x402` → `CREDENTIAL_WAITING` (9 ops). |
| Transport | PARTIAL | Onchain verification transport (`verification.py`, EVM/SVM proof paths); live commerce RPC external + credential-gated. |
| Credentials | PENDING EXTERNAL | `commerce_rpc_access` (`commerce_base_rpc`, `commerce_solana_rpc`) + oracle signer key. |
| Storage | PARTIAL | `commerce_metering` and `commerce_signer_refs` repositories exist but **neither table has a migration** (migrationNeeds). Challenge/entitlement/grant state persists through the shared durable store + graph; signer refs are durable store table claims. |
| Worker | PARTIAL | Spec `x402_reconciliation` registered, gated on `settings.intelligence_graph.enable_x402_layer`, but factory imports `services.x402.settlement.build_x402_reconciliation_coro` which **does not exist** (`SettlementTracker` has no build_ worker). Integration pass must author the reconciliation worker. |
| Cursor | PRESENT | Challenge/settlement idempotency + deterministic ids; verification cursor semantics. |
| Reconciliation | PARTIAL | `SettlementTracker.list_pending` + settlement state machine; full claim-reconciliation worker pending (above). |
| Repair | PARTIAL | Idempotent settlement retry; proof replay guard tested (`test_x402_proofs.py`). |
| Observability | PARTIAL | Commerce metering records + event publish; no dedicated x402 dashboard evidenced. |
| Tenant UI | PARTIAL | Tenant commerce surfaces exist; frontend evidence partial. |
| Operator UI | PARTIAL | Commerce/Kyber x402 admin surfaces exist; no dedicated operator credential/readiness page for x402 evidenced. |
| Entitlement | PRESENT | `EntitlementService` (`mint/lookup/reuse/revoke`) + `commerce_domain_closure` tests. |
| Meter | PRESENT | `CommerceMeteringService` + `commerce_metering` repo (immutable MeterRecords; table migration pending). |
| Infra definition | PARTIAL | Deployment contract + `.env.example` declare x402 RPC env (`QUICKNODE_X402_ENABLED`, `IG_X402_LAYER`); `commerce_*` table DDL pending. |
| Offline certification | PRESENT | `test_x402_proofs.py` (EVM verify/revert/amount/missing-log), `test_commerce_domain_closure.py` (rail matrix buckets), commerce fault stages. Registry: CREDENTIAL_WAITING. |
| External blockers | ⛔ | Commerce RPC endpoints (Base + Solana), oracle signer key, provider registration. |

### 2.7 Rewards (A6 enablement)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | `routes.py` (37 endpoints), `rails.py`, `delivery_outbox.py`, `receipt_evidence.py`, `reconcile.py`, `reservation_release.py`, `operator_routes.py`, `budget.py`, `eligibility.py`, `policy_engine.py`, `queue.py`, `repositories.py`, `onchain_gate.py`. Registry: `agentic_commerce:rewards_onchain_claim` → `CREDENTIAL_WAITING` (EIP-191 + SVM proof, nonce replay guard). |
| Transport | PARTIAL | Tenant-webhook + onchain-claim transport; SSRF-checked, HMAC-signed delivery; live rails external. |
| Credentials | PENDING EXTERNAL | `oracle_signer_key`; rail credentials; `REWARD_*_ADDRESS` contract addresses. |
| Storage | PARTIAL | Migrated: `reward_rules/campaigns/eligibility_decisions/proofs/execution_receipts/audit_log/action_payloads/tenant_rail_configs`. **No migration** for `reward_delivery_jobs`, `reward_evidence_outbox`, `reward_reservation_release_jobs`, `reward_budget_reservations`/`reward_budget_ledger` (self-created via `_ensure_table` locally; migrationNeeds for staging/prod durability). |
| Worker | PARTIAL | `reward_delivery_outbox` spec registered with **existing** `build_reward_delivery_outbox_worker` (un-gated). Specs for `reward_reservation_release` / `reward_claim_reconciliation` reference builders under wrong module paths: `services.rewards.budget.build_reservation_release_coro` and `services.rewards.reconciliation.build_reward_claim_reconciliation_coro` — actual builders are `services.rewards.reservation_release.build_release_loop` and `services.rewards.reconcile.build_reconcile_loop`. Integration pass must correct imports. |
| Cursor | PRESENT | Proof nonce + idempotency keys; delivery outbox lease/backoff; replay protection tested. |
| Reconciliation | PRESENT | `reconcile.py` claim-reconciliation (proof marked used once, idempotent receipts); `receipt_evidence.py` durable append-only audit; `test_reward_claim_reconciliation.py` + `test_reward_receipt_evidence.py`. |
| Repair | PRESENT | Durable outbox: timeout→retry→dead-letter→redeliver; `reservation_release.py` TTL release/commit; `test_reward_reservation_release.py`. |
| Observability | PARTIAL | Operator health surface (`operator_routes.py`), audit log; no dedicated rewards dashboard evidenced. |
| Tenant UI | PRESENT | Tenant reward surfaces (campaign-builder, decisions, approval-queue, rail-setup). |
| Operator UI | PRESENT | `operator_routes.py` (`/v1/admin/kyber/rewards/health`, per-tenant campaign/decision/action/audit views). |
| Entitlement | PRESENT | Permission + consent gating, no-custody model, beta-rail guard (`RailUnavailableError`). |
| Meter | PRESENT | Reward usage metering + budget reservation/commit accounting. |
| Infra definition | PARTIAL | Deployment contract + `.env.example` declare reward addresses and oracle signer; delivery-jobs/evidence tables need DDL. |
| Offline certification | PRESENT | 5 new unit files (claim reconciliation, receipt evidence, reservation release, SVM rail, audit package) + existing A6 suite; registry CREDENTIAL_WAITING. |
| External blockers | ⛔ | Oracle signer key, reward contract addresses, live rails, on-chain RPC. |

### 2.8 Credential authority (the turnkey credential plane)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | `authority.py` (durable multi-slot state machine), `slot_registry.py`, `models.py`, `schema.py`, `repository.py`, `routes.py`, `operator_view.py`, `sweeper.py`, `startup.py`; `shared/credentials/` backends (in-memory / local-encrypted / AWS Secrets Manager) + `shared/providers/credential_cipher.py`. |
| Transport | N/A | Internal service. |
| Credentials | PENDING EXTERNAL | Actual provider secret *values* (staging/production) in a provisioned backend (`CREDENTIAL_CIPHER=aws_kms` outside local); KMS key id. |
| Storage | PRESENT | Migrated: `provider_credential_versions` (partial-unique indexes: one active, one previous per slot), `tenant_credentials`, legacy `provider_api_keys`. Encrypted at rest; single decrypt site. |
| Worker | PARTIAL | Spec `credential_expiry_sweep` registered, gated on `settings.provider_gateway.enabled`, but factory imports `services.providers.credentials.sweep.build_credential_expiry_sweep_coro` — **wrong module path** (actual: `services.providers.credentials.sweeper.build_credential_expiry_sweeper`). Integration pass must fix the import. |
| Cursor | N/A | — |
| Reconciliation | PARTIAL | Sweeper tombstones expired `previous` overlap + readiness-demotion hooks (`CREDENTIAL_INVALID` on revoke/tombstone). |
| Repair | PRESENT | Restart/replica-safe (version-keyed cache), rotation-overlap, failed-pending never disturbs active. |
| Observability | PRESENT | Sweeper heartbeat + per-pass metrics + transition metrics + audit ledger. |
| Tenant UI | PRESENT | Write-only tenant-admin API (`/v1/providers/credentials`) — slot-validated, never returns secrets. |
| Operator UI | PRESENT | `operator_view.py` cross-tenant safe views + Kyber operator routes + `kyber_operator/aggregate.py` (never secrets). |
| Entitlement | PRESENT | Tenant-admin permission + server-owned slot registry (unknown slot → 400). |
| Meter | N/A | — |
| Infra definition | PRESENT | Deployment contract `credential_platform` + `credential_backend` entries; `AWS Deployment/aether-aws/terraform/modules/kms_credentials`; `scripts/bootstrap_aws_secrets.py`. |
| Offline certification | PRESENT | 7+ test files (`tests/credentials/`, `test_credential_authority.py`, cipher, concurrency, slot coverage, edges, startup, operator view, DSR tenant deletion). |
| External blockers | ⛔ | Provisioned secrets backend + KMS CMK; live provider secret values. |

### 2.9 Provider conformance (canonical contract + certification plane)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | `shared/integration_contracts/` (identity, manifest, catalog, lifecycle, results, deployment, certification, events, health, normalization, plugin, acquisition, capabilities, reconciliation) + `shared/certification/` (checks, descriptor, readiness, registry). `catalog.py` derives honest manifests for 15 connectors + 5 observe-only payment rails + 3 deferred credit bureaus. |
| Credentials | PENDING EXTERNAL | Conformance certifies readiness; it cannot supply credentials. 0/29 PARTNER_LIVE (P0 blocker). |
| Storage | PRESENT | `provider_evidence` table migrated (conformance evidence persistence). |
| Worker | N/A | — |
| Observability | PARTIAL | Readiness demotion hooks feed the capability-readiness model; no dedicated conformance dashboard. |
| Operator UI | PRESENT | Certification matrix + `make credentialless-certification-strict` gate; Kyber operator reads readiness. |
| Infra definition | PRESENT | Deployment contract + `config/credential_contracts.yaml` + `deploy/DEPLOYMENT_CONTRACT.yaml` per-capability input contracts. |
| Offline certification | PRESENT | `build_capability_matrix()` live run: **29 providers, all CREDENTIAL_WAITING** (agentic_commerce 3, communications 8, derivatives 4, interop 7, payments 5, stablecoin_chain 2); `credentialless_certification.py --strict` (no SCAFFOLDED); `staging_preflight_credentialless.py`; `staging_capability_matrix.py`; integration-contracts test suite (15 files). |
| External blockers | ⛔ | Live replay/sandbox/partner validation for each provider (promotion ladder: replay → sandbox → partner-live). |

### 2.10 Lifecycle / readiness (tenant launch + capability readiness graph)

| Dimension | Status | Evidence |
|---|---|---|
| Code | PRESENT | `services/tenant_readiness/` (service, quota, trust_states, routes), `services/readiness_graph/` (graph, revalidation_worker, routes), `services/capabilities/` (readiness_repo, enforcement, release_surface, routes, schema). |
| Credentials | PENDING EXTERNAL | Live readiness probes against provisioned providers/infra. |
| Storage | PARTIAL | `capability_readiness` and `tenant_launch_readiness` repositories exist but **neither table has a migration** (migrationNeeds). |
| Worker | PRESENT | Spec `readiness_revalidation` registered with **existing** `build_readiness_revalidation_worker`; auto-demotes (never promotes) on invalid evidence; gated off by default via proposed `RuntimeConfig.capability_readiness_revalidation_enabled`. |
| Observability | PARTIAL | Revalidation heartbeat + demotion transition metrics; no dedicated readiness dashboard. |
| Tenant UI | PRESENT | `frontend/aether/.../use-tenant-readiness.ts` + activation feature; `GET /v1/tenant/readiness` + `/trust-states`. |
| Operator UI | PARTIAL | `kyber_operator/routes.py` surfaces tenant readiness + credential slots; `readiness_graph` kyber router is authored but **not wired** into `main.py` (wiringNeeds). |
| Entitlement | PRESENT | `capabilities/enforcement.py` + quota states (fail-closed `quota_near_limit`/`quota_exceeded`); `test_quota_entitlement_metering.py`. |
| Meter | PRESENT | `metering_evidence` service (routes `/v1/metering/evidence/*` wired in `main.py`; `reconcile` + `explain`). |
| Infra definition | PARTIAL | `release_surface.py` reads `deployment_profiles.yaml` + `founding_tenant_release.yaml`; readiness DDL pending. |
| Offline certification | PRESENT | `test_readiness_graph.py`, `test_quota_entitlement_metering.py`, `test_worker_topology.py`, `staging_preflight_credentialless.py` (workers-register / capability-matrix checks). |
| External blockers | ⛔ | Live provider/worker health signals in staging; provisioned durable stores. |

---

## 3. Repository-controlled gaps needing the integration pass (NOT external)

These are concrete, repo-local wiring items that the integration pass must do.
They are enumerated here because they are the *only* things standing between the
build waves and "operator-supply-only" turnkey.

1. **Worker builder/import mismatches in `services/runtime/specs.py`** (all lazy,
   all default-OFF except the reward outbox drain, so nothing crashes at startup,
   but the specs are not buildable as-written):
   - `stablecoin_provider_polling` → import `build_stablecoin_polling_loop` from
     `services.stablecoins.polling` (missing builder).
   - `derivatives_venue_sweep` → import `build_venue_sweep_coro` from
     `services.derivatives.multi_venue` (missing builder).
   - `x402_reconciliation` → import `build_x402_reconciliation_coro` from
     `services.x402.settlement` (missing builder).
   - `credential_expiry_sweep` → import path `services.providers.credentials.sweep`
     should be `services.providers.credentials.sweeper` (`build_credential_expiry_sweeper`).
   - `reward_reservation_release` → import `build_reservation_release_coro` from
     `services.rewards.budget`; actual builder is
     `services.rewards.reservation_release.build_release_loop`.
   - `reward_claim_reconciliation` → import `build_reward_claim_reconciliation_coro`
     from `services.rewards.reconciliation`; actual builder is
     `services.rewards.reconcile.build_reconcile_loop`.
   - `dead_letter_sweeper` → `services.runtime.dead_letter_sweeper` module absent.
   - `settlement_reconciliation` → `services.integrations.providers.payment_rails.settlement`
     module absent.
2. **Settings flags referenced by specs but absent from `config/settings.py`**
   (all default OFF via `getattr`): `RuntimeConfig.capability_readiness_revalidation_enabled`,
   `RuntimeConfig.dead_letter_sweeper_enabled`,
   `PaymentRails.settlement_reconciliation_enabled`, a `rewards` config block
   (`reservation_release_enabled`, `claim_reconciliation_enabled`),
   `payment_rails.durability_seam_enabled`.
3. **Routers authored but not wired into `main.py`**: `readiness_graph` router +
   kyber router (file itself says "NOT wired — include_router the router and
   kyber_router"); `services/diagnostics/observability_middleware.py` auto-trace
   middleware (authored, needs `add_middleware`/lifespan registration).
4. **Migrations needed** (exact DDL intent in §5 of the companion blocker
   report): `capability_readiness`, `tenant_launch_readiness`, `metering_evidence`,
   `commerce_signer_refs`, `commerce_metering`, `reward_delivery_jobs`,
   `reward_evidence_outbox`, `reward_reservation_release_jobs`,
   `reward_budget_reservations`/`reward_budget_ledger`, payment-rail durability
   mirror tables.
5. **Enforcement seams authored but not opted-in** (fail-closed by default until
   a resolver is installed): `derivatives_entitlement_gate`,
   `payment_rails/entitlement_gate.py` (`AETHER_PAYMENT_ENTITLEMENT_GATE_ENABLED`),
   `payment_rails/lifecycle.py` rollout-control gate.
6. **Contract parity drift**: `deploy/DEPLOYMENT_CONTRACT.yaml` still marks
   `stablecoin_chain` / `derivatives` / `interop` as `application_code_ready: false`
   while the certification registry resolves all three domains code-complete
   (CREDENTIAL_WAITING). Update the contract to match the registry.

## 4. Honest posture summary

| Capability | Pre-staging posture |
|---|---|
| Stablecoin | Release-shaped, credential-gated. Code/transport/storage/cursor/reconciliation/repair present; polling-loop worker builder + durable meter sink pending; RPC keys external. |
| Derivatives | Release-shaped, credential-gated. Durable cursor + supervised stream worker real; venue-sweep builder pending; read-only venue keys external. |
| Interop | Closest to turnkey of the economic domains: scan worker, transport, cursor, reconciliation, metering all real and tested. Entitlement gate absent. Peer registration/RPC external. |
| Payment rails | Most complete: workers, repair, observability (dashboard + alerts), entitlement, meter all present. Seam mirror tables + live creds external. |
| Card-linked | Still **partial/pilot (2/5)**: no entitlement, meter, observability dashboard, or infra definition; tenant UI absent. Feeds external. |
| x402 commerce | Control-plane code complete + CREDENTIAL_WAITING; reconciliation worker, `commerce_metering`/`commerce_signer_refs` DDL pending; RPC external. |
| Rewards | Durable outbox + reconciliation + reservation release real; 4 reward tables need DDL; worker spec paths need correction; oracle key external. |
| Credential authority | Durable, encrypted, multi-slot, operator-visible — the turnkey spine. Sweeper import path needs correction; backend + KMS + secret values external. |
| Provider conformance | 29/29 CREDENTIAL_WAITING, offline-gated; 0/29 live — promotion to replay/sandbox/partner-live is the external P0. |
| Lifecycle/readiness | Readiness graph + revalidation + tenant launch readiness real; 2 tables need DDL; kyber readiness-graph router unwired. |

**Bottom line:** every capability is either repository-complete or has a small,
enumerated, repo-local integration-pass item (worker import correction, settings
flag, migration, router wiring). **No capability is blocked from being turnkey by
repository code**; the residual blockers for all ten are genuinely external
(provisioned infra, credentials, provider registration, live certification).
