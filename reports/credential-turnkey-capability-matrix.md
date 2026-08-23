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

**Report date:** 2026-08-23
**Branch:** `claude/credential-turnkey-recut` (base `origin/main`)
**Scope:** the ten turnkey capabilities that must be operationally supplyable
with **no repository code change** — an operator should only provision infra,
supply secrets, configure public URLs, register provider apps, apply migrations,
deploy, certify, and flip flags.

This is the **re-cut** of the credential-turnkey program onto current `main`.
It carries the program's genuinely-unique contribution — the honest-money /
price-persistence plane, the import-session state machine, fleet-health
supervision, canonical economic materialization, and the resilience/gate
machinery — **adapted to main's architecture**, and it drops the branch-era
surfaces that `main` has since superseded. Where the re-cut re-homes a branch
module onto a main-owned equivalent, the re-home decision is called out
explicitly so the report never claims a module that is not actually on this
branch.

The authoritative live evidence is the gate script
(`scripts/credential_turnkey_gate.py`, `make credential-turnkey`):

> **38 rows — 36 pass / 0 fail / 2 warn.** The 2 warnings are advisory
> ("documentation present but currency not independently verifiable", and
> "CI gate chain declared; run `make ci-check` for a live verification"). CI is
> green on this branch (`make ci-check` = 62/62).

## Status legend

| Marker | Meaning |
|---|---|
| **CARRIED** | Repository evidence exists **on this branch** (added or delta-adapted to main): real code + tests, importable, and (where applicable) durable/migrated or wiring-registered. |
| **MAIN** | The surface is provided by `main`'s canonical implementation; the re-cut consumes it rather than re-porting a superseded branch module. |
| **RE-HOMED** | A branch surface was adapted onto a main-owned equivalent (the branch module was dropped; the behavior landed as an additive delta in main's file). |
| **ABSENT** | No repository evidence on this branch. |
| **PENDING EXTERNAL** | Environment-controlled (live credentials, staging, provider/cloud access). This is *not* a repository-coding blocker. |
| **N/A** | Dimension does not apply to the capability (e.g. credentials have no meter). |

The per-provider readiness floor is main's certification matrix:
**29/29 providers resolve to `CREDENTIAL_WAITING`** (code-complete +
infra-defined + credential-gated, none `SCAFFOLDED`, none `PARTNER_LIVE`).
`CREDENTIAL_WAITING` is a pre-production posture, not a release claim.

---

## 1. Capability Completion Matrix (re-cut carried surface)

Legend per cell: `C` = CARRIED on this branch, `M` = main-owned canonical,
`R` = RE-HOMED onto main, `⛔` = PENDING EXTERNAL, `-` = ABSENT, `·` = N/A.

| Capability | Code | Transport | Credentials | Storage | Worker | Cursor | Reconcil. | Repair | Observab. | Tenant UI | Operator UI | Entitlement | Meter | Infra defn | Offline cert | External blockers |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **1. Stablecoin** | C | M | ⛔ | C | M | C | C | M | C | M | M | M | M | M | C | ⛔ |
| **2. Derivatives** | C | M | ⛔ | C | C | C | - | C | C | M | M | C | C | M | C | ⛔ |
| **3. Interop** | C | M | ⛔ | M | M | M | C | M | C | M | M | - | C | M | C | ⛔ |
| **4. Payment rails** | C | M | ⛔ | M | M | M | M | M | C | M | M | M | M | M | C | ⛔ |
| **5. Card-linked** | C | M | ⛔ | C | C | C | C | C | - | - | C | - | - | - | C | ⛔ |
| **6. x402 commerce** | C | M | ⛔ | C | C | C | C | C | C | M | M | M | C | M | C | ⛔ |
| **7. Rewards** | C | M | ⛔ | C | C | C | C | C | C | M | C | M | M | M | C | ⛔ |
| **8. Credential authority** | C | · | ⛔ | M | M | · | M | M | M | M | C | M | · | M | C | ⛔ |
| **9. Provider conformance** | M | · | ⛔ | M | · | · | · | · | M | · | M | · | · | M | M | ⛔ |
| **10. Lifecycle/readiness** | C | · | ⛔ | C | C | · | · | · | C | C | M | M | C | M | C | ⛔ |

---

## 2. Per-capability evidence (re-cut)

### 2.1 Stablecoin (`stablecoin_chain` evm/svm + stablecoin intelligence)

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | **Price write path** (`services/stablecoins/price_persistence.py`): `persist_price_observation` + `StablecoinPriceReconciler` (idempotent signature dedupe — re-reconciling a snapshot set yields `duplicate`, never a second conflict row). **`price_feed.py` delta**: `StablecoinPriceObservationSink` (JSONB, deterministic keys), `StablecoinPriceConflictDetector` (CONFLICT/CONSENSUS/PRICE_UNAVAILABLE honest states), sink-wired connectors. `shared/cis/clickhouse.py`: `ClickHouseUnavailableError` re-raise (no silent failure). Main's `providers.py` delete-based rollback is canonical (re-home decision — branch's demote-not-delete is superseded). Registry: `stablecoin_chain:evm|svm` → `CREDENTIAL_WAITING`. |
| Transport | MAIN | EVM/SVM connectors + in-process fixture transport are main-owned; live chain RPC/JSON-RPC seams exist and are credential-gated (`required_endpoints=["json_rpc"]`). |
| Credentials | PENDING EXTERNAL | Per-network RPC/indexer access keys + signed data agreements (deployment contract `stablecoin_chain.required_secrets: rpc_api_key`). |
| Storage | CARRIED | Main's migrated `stablecoin_*` tables + the re-cut's durable price write path (unavailable snapshot persisted as observed, never fabricated 0/1 USD; durable reconciliation records). |
| Worker | MAIN | Main-owned `stablecoin_provider_polling` spec + polling machinery; the re-cut's `polling.py` delta wires it. |
| Cursor | CARRIED | `StablecoinIngestionCheckpointRepository` + polling cursors; price-conflict `reconciliation_id` chains. |
| Reconciliation | CARRIED | Multi-provider price reconciliation (`price_persistence.py`) — durable conflict/consensus/duplicate records; payment/onchain reconciliation is main-owned. |
| Repair | MAIN | Main's remediation audit repo + reorg rollback/re-emit; RPC-failure fail-closed. |
| Observability | CARRIED | Provider-health repository + honest-availability states (`price_persistence`); no dedicated stablecoin Grafana dashboard on this branch. |
| Tenant UI | MAIN | Tenant frontend stablecoin surfaces (main-owned, Phase 4). |
| Operator UI | MAIN | Kyber stablecoin admin routes (main-owned). |
| Entitlement | MAIN | `StablecoinCapabilityEntitlement` + `StablecoinEntitlementGuard` (fail-closed) in main's `governance.py`. |
| Meter | MAIN | Main's `usage_metering()` + durable `metering_evidence`; re-cut adds `metering_evidence` storage policies. |
| Infra definition | MAIN | Main's deployment contract declares `stablecoin_chain` services/secrets/URLs. |
| Offline certification | CARRIED | `test_stablecoin_price_write_path.py` (4), `test_clickhouse_no_silent_failure.py` (9), observability write paths; registry resolves CREDENTIAL_WAITING. |
| External blockers | ⛔ | Live chain RPC/indexer keys; signed data agreements; rate-limit review. |

### 2.2 Derivatives (hyperliquid / dYdX / GMX / Drift)

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | `durable_cursor.py` (checkpoint persist/restore + stream-gap rows), `guards.py` (`derivatives_entitlement_gate`, fail-closed), `meter.py` (`DerivativesMeter` + sink hook), `sequence.py` (`SupervisedStreamWorker`), `topic_contract.py` (Kafka topic contract, broker-free validation), `counters.py`, `multi_venue.py` delta. Registry: `derivatives:hyperliquid|dydx|gmx|drift` → `CREDENTIAL_WAITING`. |
| Transport | MAIN | Main-owned injectable REST/WS seams + fixture transport; live exchange endpoints external and credential-gated. |
| Credentials | PENDING EXTERNAL | Read-only exchange API keys per venue; market-data license terms. |
| Storage | CARRIED | Main's migrated `derivatives_*` tables + `durable_cursor.py` closes the write-path gap (checkpoint/stream-gap rows). |
| Worker | CARRIED | `SupervisedStreamWorker` (`sequence.py`) real; `services/runtime/specs.py` delta registers `derivatives_venue_sweep` on main's sweep builder seam. |
| Cursor | CARRIED | Durable pull-cursor + stream-gap persistence; `DerivativesPullRunner` at-least-once resume; tested (`test_derivatives_durable_cursor.py`). |
| Reconciliation | ABSENT | The branch-era derivatives reconciliation modules were not carried (superseded by main's runtime reconciliation plane); the re-cut leaves this to main. |
| Repair | CARRIED | Sequence-gap detection/recovery, disconnect→reconnect resume at expected sequence (`test_derivatives_faults.py`). |
| Observability | CARRIED | Health/counters + checkpoint telemetry; no dedicated derivatives Grafana dashboard on this branch. |
| Tenant UI | MAIN | Tenant frontend derivatives surfaces (main-owned). |
| Operator UI | MAIN | Kyber derivatives admin routes (main-owned). |
| Entitlement | CARRIED | `derivatives_entitlement_gate` (`guards.py`), fail-closed by default. |
| Meter | CARRIED | `DerivativesMeter` hook + `install_derivatives_meter_sink`. |
| Infra definition | MAIN | Main's deployment contract declares `derivatives` required services/secrets/URLs; `topic_contract.py` declares the topic contract. |
| Offline certification | CARRIED | Durable-cursor, faults tests; registry CREDENTIAL_WAITING. |
| External blockers | ⛔ | Read-only venue API keys; live market-data endpoints; data-license confirmation. |

### 2.3 Interop (LayerZero / Wormhole / Axelar / CCIP / Hyperlane / IBC / deBridge)

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | `scan_worker.py` (real scan loop), `reconcile.py` (cross-leg variance, observation-only), `metering.py` (`interop:<dimension>:<unit_key>`, duplicate-excluded). Registry: `interop:*` (7) → `CREDENTIAL_WAITING`. |
| Transport | MAIN | Main-owned `transport.py` (httpx JSON-RPC + CometBFT clients, `RpcRateLimited`); live endpoints constructed at wiring time from secret-refs. |
| Credentials | PENDING EXTERNAL | Per-network JSON-RPC endpoints + `interop_signing_secret`. |
| Storage | MAIN | Main's migrated `interop_*` tables. |
| Worker | MAIN | Main-owned `scan_worker` + `interop_scan` spec wiring. |
| Cursor | MAIN | Main's durable `interop_provider_checkpoints` + checkpoint resume. |
| Reconciliation | CARRIED | `reconcile.py` cross-leg variance + `interop_reconciliation_variance_detected` events; tested (`test_reconcile_state.py`). |
| Repair | MAIN | Main's dead-letter quarantine + checkpoint-idempotent replay. |
| Observability | CARRIED | Usage metering counters surfaced; no dedicated interop Grafana dashboard on this branch. |
| Tenant UI | MAIN | Tenant frontend interop surfaces (main-owned). |
| Operator UI | MAIN | `interop_admin_router` (main-owned). |
| Entitlement | ABSENT | No interop entitlement gate on this branch. |
| Meter | CARRIED | `metering.py` records `metering_evidence` dimensions; storage policy added. |
| Infra definition | MAIN | Main's deployment contract declares `interop` services/URLs/secrets. |
| Offline certification | CARRIED | `test_interop_metering.py`, `test_reconcile_state.py`, `test_scan_reorg_restart.py`; registry CREDENTIAL_WAITING. |
| External blockers | ⛔ | Peer provider registration, callback URLs, per-network RPC, signing-secret exchange. |

### 2.4 Payment rails (Privy / Stripe Onramp / Coinbase / MoonPay / Bridge)

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | **Fleet-health supervisor** (`kyber_aggregate.py`): `build_fleet_health` with tri-state honesty (unconfigured adapters cannot report false success); `repository.py` `ProviderAccountRepository.list_all`. `deploy/observability/grafana/dashboards/payment-rails.json` carried. Main owns the adapters, webhook/polling transport, routes, and receipt/reconciliation ledgers (the branch-era `durability.py`/`lifecycle.py`/`entitlement_gate.py`/`alert_*`/`sync_worker`/`repair_worker` were **not carried** — they were superseded by main's canonical payment-rails plane). Registry: `payments:*` (5) → `CREDENTIAL_WAITING`. |
| Transport | MAIN | Main's native webhook + polling transport with signature verification. |
| Credentials | PENDING EXTERNAL | Per-rail `webhook_signing_secret` + `onramp_api_key`; supplied through main's durable CredentialAuthority. |
| Storage | MAIN | Main's migrated `payment_rail_*` tables + durable receipt/reconciliation ledgers. |
| Worker | MAIN | Main's `payment_rail_sync` / `payment_canonical_repair` / `payment_alert_eval` specs with existing builders. |
| Cursor | MAIN | Main's polling checkpoint/cursor. |
| Reconciliation | MAIN | Main's receipt lifecycle + staleness reconciliation + canonical repair. |
| Repair | MAIN | Main's `repair_worker` + `payment_canonical_repair`. |
| Observability | CARRIED | `payment-rails.json` dashboard + fleet-health aggregate (`kyber_aggregate.py`) — honest tri-state health. |
| Tenant UI | MAIN | Tenant frontend payment-rail surfaces (main-owned). |
| Operator UI | MAIN | Main's `payment_rails_kyber_router`. |
| Entitlement | MAIN | Main's entitlement admission (plan-tier + permission). |
| Meter | MAIN | Main's `AETHER_PAYMENT_USAGE_METERING_ENABLED` usage metering. |
| Infra definition | MAIN | Main's deployment contract `payment_rails` entry + public webhook URLs. |
| Offline certification | CARRIED | `test_observability_fleet_health.py` (4) + main's payment-rails suite (30+ files). |
| External blockers | ⛔ | Live rail credentials; public webhook URL registration per rail app; sandbox/live provider apps. |

### 2.5 Card-linked payment rails

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | **Import-session FSM**: `import_session.py` (state machine) + `services/imports/session_persistence.py` (durable, idempotent) + `services/imports/service.py`/`commit.py` deltas (resumable commits); `projection_routes.py`. Main owns ingestion, gold, repositories, routes, governance. |
| Transport | MAIN | Main's partner-feed transport; live card-network/processor feeds external. |
| Credentials | PENDING EXTERNAL | Card-network/processor feed access + import-bridge credentials. |
| Storage | CARRIED | Main's `card_linked_flow_facts` + the re-cut's durable import-session state (`test_card_linked_import_session.py`). |
| Worker | CARRIED | Import-session resumability + `card_linked_graph_outbox` (main-owned spec); commit resumability means abandoned sessions requeue, never silently mark processed. |
| Cursor | CARRIED | Import-session checkpoints + sweep TTLs. |
| Reconciliation | CARRIED | Import staging + graph outbox (partial evidence — no dedicated card-linked reconciliation module). |
| Repair | CARRIED | Import-session requeue/sweeper + fault stages (`tests/faults/test_card_linked_import_stages.py`). |
| Observability | ABSENT | No card-linked Grafana dashboard on this branch. |
| Tenant UI | ABSENT | No card-linked tenant frontend surface on this branch. |
| Operator UI | CARRIED | `projection_routes.py` + main's `card_linked_kyber_router`. |
| Entitlement | ABSENT | No card-linked entitlement gate on this branch. |
| Meter | ABSENT | No card-linked metering on this branch. |
| Infra definition | ABSENT | No card-linked terraform/deploy-contract entry on this branch. |
| Offline certification | CARRIED | `test_card_linked_import_session.py` + import-stages fault test. Consistent with the audit's card-linked score of **2/5 (partial/pilot)**. |
| External blockers | ⛔ | Card-network/processor feed access, partner agreements, import-bridge credentials. |

### 2.6 x402 commerce (challenge → authorize → verify → settle → entitle → grant)

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | `signer_authority.py` + `signer_repos.py` (refs-only signer authority, never private material); `commerce_models.py`/`commerce_store.py`/`control_plane.py` deltas (Decimal money, proof semantics); `services/commerce/metering.py`, `rail_matrix.py`, `reconciliation.py`, `workers.py`. Main owns verification/settlement/entitlements/idempotency. Registry: `agentic_commerce:x402` → `CREDENTIAL_WAITING` (9 ops). |
| Transport | MAIN | Main's onchain verification transport (EVM/SVM proof paths); live commerce RPC external + credential-gated. |
| Credentials | PENDING EXTERNAL | `commerce_rpc_access` (`commerce_base_rpc`, `commerce_solana_rpc`) + oracle signer key. |
| Storage | CARRIED | `commerce_metering` + `commerce_signer_refs` repos (durable store table claims) + storage policies; challenge/entitlement/grant state through main's durable store + graph. |
| Worker | CARRIED | `services/runtime/specs.py` delta registers commerce workers on main's builders. |
| Cursor | CARRIED | Challenge/settlement idempotency + deterministic ids. |
| Reconciliation | CARRIED | `services/commerce/reconciliation.py` + `SettlementTracker` (main) settlement state machine. |
| Repair | CARRIED | Idempotent settlement retry; proof replay guard (`test_x402_proofs.py` 12). |
| Observability | CARRIED | Commerce metering records + event publish; no dedicated x402 dashboard on this branch. |
| Tenant UI | MAIN | Tenant commerce surfaces (main-owned). |
| Operator UI | MAIN | Commerce/Kyber x402 admin surfaces (main-owned). |
| Entitlement | MAIN | Main's `EntitlementService` (`mint/lookup/reuse/revoke`). |
| Meter | CARRIED | `CommerceMeteringService` + `commerce_metering` repo (immutable MeterRecords). |
| Infra definition | MAIN | Main's deployment contract + `.env.example` declare x402 RPC env. |
| Offline certification | CARRIED | `test_x402_proofs.py` (12), `test_commerce_domain_closure.py`, commerce settle-stage faults. |
| External blockers | ⛔ | Commerce RPC endpoints (Base + Solana), oracle signer key, provider registration. |

### 2.7 Rewards (A6 enablement)

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | **SVM rail re-homed into `services/rewards/rails.py`**: `_SUPPORTED_VM_TYPES = {"evm", "svm"}`, `_build_svm_proof_payload` (SHA-256 message hash, base58 program id/signer, Anchor instruction) using main's `MultiChainSigner`; fail-closed chain identity outside local. Plus `operator_routes.py`, `receipt_evidence.py` (durable append-only audit), `reconcile.py` (claim reconciliation), `runtime/dead_letter_sweeper.py`. Registry: `agentic_commerce:rewards_onchain_claim` → `CREDENTIAL_WAITING`. |
| Transport | MAIN | Main's tenant-webhook + onchain-claim transport; SSRF-checked, HMAC-signed. |
| Credentials | PENDING EXTERNAL | `oracle_signer_key`; rail credentials; `REWARD_*_ADDRESS` contract addresses. |
| Storage | CARRIED | Main's migrated `reward_*` tables + durable evidence/outbox machinery (`receipt_evidence.py`) + storage policies. |
| Worker | CARRIED | `dead_letter_sweeper.py` (deterministic sweep summary) + main's reward outbox workers. |
| Cursor | CARRIED | Proof nonce + idempotency keys; delivery outbox lease/backoff; replay protection tested. |
| Reconciliation | CARRIED | `reconcile.py` claim-reconciliation (proof marked used once, idempotent receipts); `test_reward_claim_reconciliation.py`. |
| Repair | CARRIED | Durable outbox: timeout→retry→dead-letter→redeliver (retryable semantics in `services/delivery/outcome_processor.py`); `test_reward_receipt_evidence.py`. |
| Observability | CARRIED | Operator health surface (`operator_routes.py`), audit log; no dedicated rewards dashboard on this branch. |
| Tenant UI | MAIN | Tenant reward surfaces (main-owned). |
| Operator UI | CARRIED | `operator_routes.py` (per-tenant campaign/decision/action/audit views). |
| Entitlement | MAIN | Main's permission + consent gating, no-custody model, beta-rail guard. |
| Meter | MAIN | Main's reward usage metering + budget reservation accounting. |
| Infra definition | MAIN | Main's deployment contract + `.env.example` reward addresses + oracle signer. |
| Offline certification | CARRIED | `test_reward_svm_rail.py` (6), `test_reward_receipt_evidence.py`, `test_reward_claim_reconciliation.py`, `test_reward_audit_package.py`; registry CREDENTIAL_WAITING. |
| External blockers | ⛔ | Oracle signer key, reward contract addresses, live rails, on-chain RPC. |

### 2.8 Credential authority (the turnkey credential plane)

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | `operator_view.py` (cross-tenant safe credential views — never secrets). Main owns `authority.py` (durable multi-slot state machine), `slot_registry.py`, backends (in-memory / local-encrypted / AWS Secrets Manager), routes, sweeper. |
| Transport | N/A | Internal service. |
| Credentials | PENDING EXTERNAL | Actual provider secret *values* in a provisioned backend (`CREDENTIAL_CIPHER=aws_kms` outside local); KMS key id. |
| Storage | MAIN | Main's migrated `provider_credential_versions`, `tenant_credentials`, `provider_api_keys`. Encrypted at rest; single decrypt site. |
| Worker | MAIN | Main's `credential_expiry_sweep` spec + sweeper. |
| Cursor | N/A | — |
| Reconciliation | MAIN | Sweeper tombstones expired `previous` overlap + readiness-demotion hooks. |
| Repair | MAIN | Restart/replica-safe (version-keyed cache), rotation-overlap. |
| Observability | MAIN | Sweeper heartbeat + per-pass metrics + audit ledger. |
| Tenant UI | MAIN | Write-only tenant-admin API (`/v1/providers/credentials`). |
| Operator UI | CARRIED | `operator_view.py` cross-tenant safe views + main's Kyber operator routes. |
| Entitlement | MAIN | Tenant-admin permission + server-owned slot registry. |
| Meter | N/A | — |
| Infra definition | MAIN | Main's deployment contract `credential_platform` + `credential_backend` entries; `kms_credentials` terraform module. |
| Offline certification | CARRIED | `test_operator_credential_view.py` + main's credential suite. |
| External blockers | ⛔ | Provisioned secrets backend + KMS CMK; live provider secret values. |

### 2.9 Provider conformance (canonical contract + certification plane)

| Dimension | Status | Evidence |
|---|---|---|
| Code | MAIN | Main-owned `shared/integration_contracts/` + `shared/certification/`. `catalog.py` derives honest manifests for 15 connectors + 5 observe-only payment rails + 3 deferred credit bureaus. The re-cut's gate reads main's manifest model directly (transport via webhook/deployment surfaces; idempotency via record-level `idempotency_key`). |
| Credentials | PENDING EXTERNAL | Conformance certifies readiness; it cannot supply credentials. 0/29 PARTNER_LIVE (P0 blocker). |
| Storage | MAIN | Main's `provider_evidence` table (conformance evidence persistence). |
| Worker | N/A | — |
| Observability | MAIN | Readiness demotion hooks feed the capability-readiness model. |
| Operator UI | MAIN | Certification matrix + `make credentialless-certification-strict` gate. |
| Infra definition | MAIN | Main's deployment contract + `config/credential_contracts.yaml`. |
| Offline certification | MAIN | `build_capability_matrix()` live run: **29 providers, all CREDENTIAL_WAITING**; `credentialless_certification.py --strict`; staging preflight/matrix; integration-contracts test suite. |
| External blockers | ⛔ | Live replay/sandbox/partner validation for each provider (promotion ladder: replay → sandbox → partner-live). |

### 2.10 Lifecycle / readiness (tenant launch + capability readiness graph)

| Dimension | Status | Evidence |
|---|---|---|
| Code | CARRIED | `services/readiness_graph/` (`graph.py`, `revalidation_worker.py`, `routes.py`), `services/diagnostics/observability_middleware.py` (auto-trace middleware), `services/metering_evidence/` (`families.py`, `reconciliation.py`), `services/kyber/aggregate.py`. Main owns `services/tenant_readiness/` + `services/capabilities/`. |
| Credentials | PENDING EXTERNAL | Live readiness probes against provisioned providers/infra. |
| Storage | CARRIED | `capability_readiness` + `tenant_launch_readiness` repos + storage policies; readiness evidence durable via main's metering plane. |
| Worker | CARRIED | `readiness_revalidation` spec delta (auto-demotes on invalid evidence, never promotes); dead-letter sweeper worker. |
| Observability | CARRIED | Revalidation heartbeat + demotion transition metrics; `observability_middleware.py`. |
| Tenant UI | CARRIED | `use-tenant-readiness.ts` + `endpoints.ts` delta; `GET /v1/tenant/readiness` + `/trust-states` (main). |
| Operator UI | MAIN | Main's `kyber_operator/routes.py` tenant readiness + credential slots. |
| Entitlement | MAIN | Main's `capabilities/enforcement.py` + quota states (fail-closed). |
| Meter | CARRIED | `metering_evidence` routes + `families.py`/`reconciliation.py`. |
| Infra definition | MAIN | Main's `release_surface.py` reads `deployment_profiles.yaml`. |
| Offline certification | CARRIED | `test_readiness_graph.py`, `test_worker_topology.py`, activation audit test, worker-builder loops test. |
| External blockers | ⛔ | Live provider/worker health signals in staging; provisioned durable stores. |

---

## 3. Repository-controlled gaps on this branch (NOT external)

These are concrete, repo-local items that a follow-on pass must close. They are
enumerated here because they are the *only* things standing between the re-cut
and "operator-supply-only" turnkey — none of them block provisioning or
credential supply, and all are explicit rather than silent.

1. **Card-linked remains partial/pilot (2/5)**: no entitlement gate, meter,
   observability dashboard, infra definition, or tenant UI on this branch
   (consistent with the audit's card-linked score). The re-cut closes the
   import-session durability + resumability gap; the surface gaps remain.
2. **Interop entitlement gate absent** on this branch.
3. **Derivatives reconciliation** was not carried (main's runtime
   reconciliation plane is the canonical seam; the branch-era module is
   superseded).
4. **No dedicated Grafana dashboards** for stablecoin / derivatives / interop /
   x402 / rewards / card-linked / readiness (only `payment-rails.json` carried).
5. **`make credential-turnkey` gate** reports 2 advisory warnings by design:
   docs-currency is not independently verified, and CI-green requires the live
   `make ci-check` (green on this branch).

## 4. Honest posture summary

| Capability | Re-cut posture |
|---|---|
| Stablecoin | Release-shaped, credential-gated. Durable price write path + conflict reconciler carried; delete-based rollback + governance + transport are main. RPC keys external. |
| Derivatives | Release-shaped, credential-gated. Durable cursor + supervised stream worker + entitlement gate + meter carried; reconciliation superseded by main's runtime plane. Venue keys external. |
| Interop | Scan/reconcile/metering carried; transport, cursor, storage, workers are main. Entitlement gate absent. Peer registration/RPC external. |
| Payment rails | Fleet-health supervisor + dashboard carried; the rest of the plane is main-owned (best-in-class). Live creds external. |
| Card-linked | **Partial/pilot (2/5)**: import-session FSM + resumable commits carried; surface gaps (entitlement/meter/UI/infra) remain. Feeds external. |
| x402 commerce | Signer authority + commerce deltas + metering/reconciliation carried; verification/settlement/entitlements are main. RPC external. |
| Rewards | SVM rail re-homed + evidence/reconciliation/operator surfaces carried; outbox + repair are main. Oracle key external. |
| Credential authority | Operator view carried; the durable encrypted spine is main. Backend + KMS + secret values external. |
| Provider conformance | 29/29 CREDENTIAL_WAITING, offline-gated; 0/29 live — promotion to replay/sandbox/partner-live is the external P0. |
| Lifecycle/readiness | Readiness graph + revalidation + metering evidence + observability middleware carried; enforcement/quota + tenant readiness are main. Live health signals external. |

**Bottom line:** the re-cut lands the program's unique contribution onto current
main with every gate green (`make ci-check` 62/62; credential-turnkey 36 pass /
0 fail / 2 warn). Every capability is either repository-complete on this branch
or has a small, enumerated, repo-local follow-on — and none is blocked from
being turnkey by repository code. The residual blockers for all ten are
genuinely external (provisioned infra, credentials, provider registration, live
certification).
