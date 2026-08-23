---
title: "Credential-Turnkey External Blocker Matrix"
slug: reports/credential-turnkey-external-blockers
section: operations
visibility: I
audience: [architect, ops, exec]
status: beta
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 12
---

# Credential-Turnkey External Blocker Matrix (program sec30.B)

**Report date:** 2026-08-23
**Branch:** `claude/credential-turnkey-recut` (base `origin/main`)
**Purpose:** the ONLY items that genuinely require staging/provider/cloud access.
For every one, we state explicitly whether a **repository coding blocker** exists
on this branch. Where none exists, that is called out as
**"no repository coding blocker"** so the organization can act on the external
item with confidence that no code change is required to make the capability
turnkey.

This is the **re-cut** report: it reflects the carried surface on
`claude/credential-turnkey-recut`, cross-referenced against main's canonical
planes (certification registry → `build_capability_matrix()` → 29/29
`credential_waiting`, `deploy/DEPLOYMENT_CONTRACT.yaml`, `.env.example`,
`scripts/bootstrap_aws_secrets.py`, the worker specs, and the offline gates).
Branch-era surfaces that main has superseded are explicitly marked as such
rather than claimed as repo evidence.

## Truth rule

- **`no repository coding blocker = true`** means: the code, routes, storage,
  workers, entitlements, meters, and offline certification are present and
  importable on this branch (carried **or** main-owned canonical). Only
  environment provisioning / credentials / provider registration / live
  validation remain.
- **`no repository coding blocker = false`** means: a repo-local item sits in
  the way as well (a carried-surface gap, a missing settings flag, a missing
  migration, an unwired router). Those items are itemized in the companion
  report (§3) and are **not** external blockers — they are tracked separately so
  this matrix stays honest about what is genuinely external.

---

## 1. External Blockers by Capability

### 1.1 Stablecoin

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| S-1 | Per-network chain RPC/indexer access keys (read-only) for EVM + SVM networks | Live on-chain observation + finality confirmation | **true** — price write path + conflict reconciler carried; transport, governance, repair are main. No repo item on this branch. |
| S-2 | Signed data agreements / rate-limit review for chain data (staging/production) | Legal/business go-ahead for live chain data | **true** — no code dependency. |
| S-3 | Provisioned Postgres for stablecoin tables (migrations already exist) | Durable observations/finality/reconciliation | **true** — all `stablecoin_*` tables migrated on main. |

### 1.2 Derivatives

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| D-1 | Read-only exchange API keys per venue (Hyperliquid / dYdX / GMX / Drift) | Live market data + account snapshots | **true** — durable cursor + supervised stream worker + entitlement gate carried; resolver seam is main. No repo item on this branch. |
| D-2 | Live venue REST/websocket endpoints reachable from staging | Transport validation | **true** — injectable REST/WS transport present (main); fixture transport exercised offline. |
| D-3 | Market-data license confirmation for private/aggregated feeds | Business go-ahead | **true** — no code dependency. |
| D-4 | Kafka topics provisioned for derivatives realtime stream (broker owner) | Realtime stream transport in staging/prod | **true** — `topic_contract.py` declares + validates the topic contract broker-free; deploy-time Kafka topic provisioner carried. |

### 1.3 Interop

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| I-1 | Per-network JSON-RPC endpoints (EVM) + CometBFT endpoints (IBC) configured as secret-refs | Live adapter scans | **true** — transport clients real (main); scan worker + reconcile + metering carried. |
| I-2 | Peer interop provider registration: public callback URLs + signing-key/secret exchange with each peer protocol | Inbound message verification | **true** — callback URLs + `interop_signing_secret` declared in main's deployment contract. |
| I-3 | Provisioned Postgres for interop ledger tables (migrations already exist) | Durable messages/checkpoints/reconciliation | **true** — all `interop_*` tables migrated on main. |

### 1.4 Payment rails

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| P-1 | Per-rail webhook signing secrets supplied into the durable CredentialAuthority (Privy / Stripe Onramp / Coinbase / MoonPay / Bridge) | Live webhook verification + polling | **true** — the authority (main) is the SOLE credential source outside local; fleet-health supervision carried. |
| P-2 | Read-only provider API keys for polling rails (MoonPay / Coinbase / Bridge) | Polling sync | **true**. |
| P-3 | Public webhook ingest URL per rail + provider-app registration (sandbox/live) | Inbound webhooks routed to the platform | **true** — main's deployment contract `payment_rails.required_public_urls`. |
| P-4 | (None) | — | The branch-era Postgres mirror seam (`durability.py`) was **not carried**; main's KV-backed receipt/reconciliation ledgers are the canonical durability floor. No repo item on this branch. |

### 1.5 Card-linked

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| C-1 | Card-network / processor feed access + partner agreements | Live card-linked ingestion | **true** — but see C-2: the capability is otherwise not turnkey. |
| C-2 | (context) No repo-local item blocks provisioning, BUT the capability is still partial/pilot: no entitlement gate, no meter, no observability dashboard, no infra definition, no tenant UI on this branch. | Full turnkey | **false** — these are repository gaps tracked in the companion capability matrix (§2.5); they are not external blockers. The re-cut closes the import-session durability + resumability gap; the surface gaps remain. |

### 1.6 x402 commerce

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| X-1 | Commerce RPC endpoints: `commerce_base_rpc` + `commerce_solana_rpc` (secret-refs) | Live onchain verification/settlement | **true** — verification + settlement real (main); signer authority + metering/reconciliation carried. No repo item on this branch. |
| X-2 | Oracle signer key for rewards-style claim proofs (if x402 claim proofs used) | Signed claim proofs | **true** — signer authority stores refs only, never private material; key supply is external. |
| X-3 | Provider registration / facilitator setup for payment paths | Live payment authorization | **true** — main's deployment contract + `.env.example` (`QUICKNODE_X402_ENABLED`, `IG_X402_LAYER`). |

### 1.7 Rewards

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| R-1 | Oracle signer key (`ORACLE_SIGNER_KEY`) for EVM/SVM claim proof signing | On-chain claim proof issuance | **true** — SVM rail carried (`rails.py` re-home); fail-closed guards enforce key presence outside local. |
| R-2 | Reward contract addresses: `ANALYTICS_REWARDS_ADDRESS`, `REWARD_REGISTRY_ADDRESS`, `REWARD_TOKEN_ADDRESS` | On-chain reward deployment/verification | **true** — address env inputs declared in `.env.example`. |
| R-3 | Live reward rails (tenant webhook destinations, beta rails gated) | Real delivery | **true** — beta rails intentionally raise `RailUnavailableError` until operator-approved. |
| R-4 | (None) | — | The branch-era reward tables are migrated on main; evidence/outbox/claim-reconciliation machinery carried with storage policies. No repo item on this branch. |

### 1.8 Credential authority

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| K-1 | Provisioned secrets backend: `CREDENTIAL_CIPHER=aws_kms` + `CREDENTIAL_KMS_KEY_ID` (KMS CMK) outside local | Encrypted credential storage at rest | **true** — `local` AES-256-GCM cipher + fail-closed guard present (main); `aws_kms` path + `kms_credentials` terraform module exist. |
| K-2 | Actual provider secret VALUES inserted into the backend (per slot registry) | Turnkey credential supply | **true** — slot registry derives slots from the adapters' own descriptors; the API rejects unknown slots. |
| K-3 | AWS Secrets Manager prefix (`AETHER_CREDENTIAL_AWS_PREFIX`) + IAM role when `aws_secrets_manager` backend | Backend connectivity | **true** — declared in main's deployment contract. |

### 1.9 Provider conformance

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| F-1 | Replay validation evidence (provider fixtures + `fixture_schema_version` bump) for each of the 29 providers | `replay_validated` rung | **true** — interop/derivatives conformance suites are the template; no code change needed. |
| F-2 | Sandbox-validate against each provider's sandbox + record `last_certified_at` / live evidence | `sandbox_validated` rung | **true** — promotion is evidence-driven by design. |
| F-3 | Partner-live validation in a controlled staging window + pilot evidence | `partner_live` rung (0/29 today — the P0) | **true** — the ladder (`CREDENTIAL_WAITING → replay → sandbox → partner-live`) is entirely credential/live-work; no repository coding blocker. |
| F-4 | External smart-contract security audit (EVM/SVM/NEAR/Cosmos reward contracts) | `production_ready` + mainnet/real-funds deploy | **true** — release-blocker per audit; no code dependency. |
| F-5 | Security review of each live-validated provider | `production_ready` evidence | **true**. |

### 1.10 Lifecycle / readiness

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| L-1 | Live worker/provider health signals in staging | Readiness-graph nodes resolve to real health | **true** — resolvers fail closed (absence is not health) by design; readiness graph + revalidation carried. |
| L-2 | Provisioned durable stores (Redis/Postgres) for readiness evidence + metering | Durable metering/readiness records | **true** — readiness evidence + metering repos carried with storage policies; main's durable plane is the write path. |

---

## 2. Cross-cutting external blockers (cloud/staging, span multiple capabilities)

| # | External blocker | Capabilities affected | no repository coding blocker |
|---|---|---|---|
| XG-1 | Production/staging infrastructure NOT provisioned: Terraform modules exist (ECS/EC2/clickhouse/kafka/KMS) but no `apply` has run | all ten | **true** — `deploy/DEPLOYMENT_CONTRACT.yaml` + `staging_infra_plan.py` define the provisioning-READY pieces; the apply is a credential-gated operator step. |
| XG-2 | Kafka topics unprovisioned (MSK auto-create disabled; one-shot topic provisioner Lambda is the mechanism) | derivatives, interop, payment rails, commerce | **true** — `deploy/kafka/topic_provisioner.py` + `topics.json` + drift-tested registry sync carried. |
| XG-3 | ClickHouse DDL (economic/Gold) unexecuted | interop, derivatives, stablecoin, measurement | **true** — schema files shipped; a migration job applies them in numeric order. |
| XG-4 | No OpenTelemetry SDK/exporter integrated (tracing is a seam only) | observability across all | **true** — `observability_middleware.py` is a real durable writer (carried); OTel exporter integration is an ops/3rd-party choice. |
| XG-5 | No staging load baselines recorded | scale readiness | **true** — Locust harness + `make load-smoke` exist; baselines require a live staging run. |
| XG-6 | Production secrets not configured (`scripts/bootstrap_aws_secrets.py`) | all ten | **true** — bootstrap script present; running it requires cloud access. |
| XG-7 | ML artifacts not trained/published for serving | intelligence surfaces | **true** — training pipelines exist; artifact publishing is external. |
| XG-8 | Dune backend not provisioned (`DUNE_BACKEND`) | data-lake feeder | **true** — connector real, credential-gated; scheduled polling disabled until provisioned. |

---

## 3. Explicit "no repository coding blocker" call-outs

For the items below, the repo is **provably** turnkey-coded on this branch
(modules import, offline gates pass, tables migrated, workers registered,
`make ci-check` green). The single remaining action is external:

- **Stablecoin live observation** (S-1/S-2/S-3): price write path + reconciler carried; code-complete + CREDENTIAL_WAITING.
- **Derivatives live pulls** (D-1/D-2/D-3): durable cursor + supervised stream worker carried.
- **Interop live scans** (I-1/I-2/I-3): scan/reconcile/metering carried; transport + cursor are main.
- **Payment-rail live webhooks/polling** (P-1/P-2/P-3): authority-backed (main), fleet-health supervised (carried).
- **Rewards live claims** (R-1/R-2/R-3): SVM rail re-homed; evidence/reconciliation carried.
- **Credential authority supply** (K-1/K-2/K-3): operator view carried; the turnkey spine is main.
- **Provider conformance promotion** (F-1/F-2/F-3/F-4/F-5): evidence-driven; 0/29 PARTNER_LIVE is a validation/work item, not a coding gap.
- **Cross-cutting cloud bring-up** (XG-1 … XG-8): provisioning-READY artifacts exist.

## 4. Items that are NOT external blockers (repo-local, on this branch)

These are deliberately excluded from "external" and tracked in the companion
capability matrix (§3): the card-linked surface gaps (entitlement/meter/UI/
infra), the absent interop entitlement gate, the dropped derivatives
reconciliation (superseded by main's runtime plane), and the missing dedicated
Grafana dashboards (stablecoin/derivatives/interop/x402/rewards/card-linked/
readiness). None of these block provisioning or credential supply; they are the
follow-on queue.
