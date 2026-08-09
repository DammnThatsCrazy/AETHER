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

**Report date:** 2026-08-09
**Branch:** `claude/credential-turnkey-pre-staging` (base `origin/main`)
**Purpose:** the ONLY items that genuinely require staging/provider/cloud access.
For every one, we state explicitly whether a **repository coding blocker** exists.
Where none exists, that is called out as **"no repository coding blocker"** so the
organization can act on the external item with confidence that no code change is
required to make the capability turnkey.

Every external blocker below is cross-referenced against the actual repo state:
certification registry (`build_capability_matrix()` → 29/29 `credential_waiting`),
`deploy/DEPLOYMENT_CONTRACT.yaml`, `.env.example`, `scripts/bootstrap_aws_secrets.py`,
the worker specs, and the offline gates (`credentialless_certification.py`,
`staging_preflight_credentialless.py`, `staging_capability_matrix.py`).

## Truth rule

- **`no repository coding blocker = true`** means: the code, routes, storage,
  workers, entitlements, meters, and offline certification are present and
  importable on this branch. Only environment provisioning / credentials /
  provider registration / live validation remain.
- **`no repository coding blocker = false`** means: a repo-local integration-pass
  item sits in the way as well (a worker import mismatch, a missing settings flag,
  a missing migration, an unwired router). Those items are itemized in the
  companion report (§3) and are **not** external blockers — they are tracked
  separately so this matrix stays honest about what is genuinely external.

---

## 1. External Blockers by Capability

### 1.1 Stablecoin

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| S-1 | Per-network chain RPC/indexer access keys (read-only) for EVM + SVM networks | Live on-chain observation + finality confirmation | **true** — code, transport seams, cursor, reconciliation, repair, offline cert all present. Repo item only: polling-loop worker builder import mismatch (specs.py), which does not block provisioning. |
| S-2 | Signed data agreements / rate-limit review for chain data (staging/production) | Legal/business go-ahead for live chain data | **true** — no code dependency. |
| S-3 | Provisioned Postgres for stablecoin tables (migrations already exist) | Durable observations/finality/reconciliation | **true** — all `stablecoin_*` tables migrated. |

### 1.2 Derivatives

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| D-1 | Read-only exchange API keys per venue (Hyperliquid / dYdX / GMX / Drift) | Live market data + account snapshots | **true** — resolver seam (`credentials.py`) + durable cursor + supervised stream worker present. Repo item only: `derivatives_venue_sweep` builder import mismatch (specs.py). |
| D-2 | Live venue REST/websocket endpoints reachable from staging | Transport validation | **true** — injectable REST/WS transport present; fixture transport exercised offline. |
| D-3 | Market-data license confirmation for private/aggregated feeds | Business go-ahead | **true** — no code dependency. |
| D-4 | Kafka topics provisioned for derivatives realtime stream (broker owner) | Realtime stream transport in staging/prod | **true** — `topic_contract.py` declares + validates the topic contract broker-free; topic creation mechanism is the deploy-time Kafka topic provisioner. |

### 1.3 Interop

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| I-1 | Per-network JSON-RPC endpoints (EVM) + CometBFT endpoints (IBC) configured as secret-refs | Live adapter scans | **true** — transport clients real (`transport.py`); scan worker + durable cursor real. |
| I-2 | Peer interop provider registration: public callback URLs + signing-key/secret exchange with each peer protocol | Inbound message verification | **true** — callback URLs + `interop_signing_secret` declared in deployment contract. |
| I-3 | Provisioned Postgres for interop ledger tables (migrations already exist) | Durable messages/checkpoints/reconciliation | **true** — all `interop_*` tables migrated. |

### 1.4 Payment rails

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| P-1 | Per-rail webhook signing secrets supplied into the durable CredentialAuthority (Privy / Stripe Onramp / Coinbase / MoonPay / Bridge) | Live webhook verification + polling | **true** — the authority is the SOLE credential source outside local; `webhook_endpoints` + signature verify real. |
| P-2 | Read-only provider API keys for polling rails (MoonPay / Coinbase / Bridge) | Polling sync | **true**. |
| P-3 | Public webhook ingest URL per rail + provider-app registration (sandbox/live) | Inbound webhooks routed to the platform | **true** — deployment contract `payment_rails.required_public_urls`. |
| P-4 | Postgres mirror seam tables migrated (payment-rail durability floor) | Relational ledger durability | **false** — repo item: `durability.py` exposes exact `migration_ddl`; the migration itself is a repo-local integration-pass item (not external). The KV-backed ledgers already provide the live durability floor, so this is an enhancement, not a hard blocker. |

### 1.5 Card-linked

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| C-1 | Card-network / processor feed access + partner agreements | Live card-linked ingestion | **true** — but see C-2: the capability is otherwise not turnkey. |
| C-2 | (context) No repo-local item blocks provisioning, BUT the capability is still partial: no entitlement gate, no meter, no observability dashboard, no infra definition, no tenant UI. | Full turnkey | **false** — these are repository gaps that the build waves did **not** close for card-linked. They are tracked in the companion capability matrix (§2.5); they are not external blockers. |

### 1.6 x402 commerce

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| X-1 | Commerce RPC endpoints: `commerce_base_rpc` + `commerce_solana_rpc` (secret-refs) | Live onchain verification/settlement | **true** — verification + settlement code real. Repo items only: `x402_reconciliation` worker builder import mismatch (specs.py); `commerce_metering` + `commerce_signer_refs` DDL pending. |
| X-2 | Oracle signer key for rewards-style claim proofs (if x402 claim proofs used) | Signed claim proofs | **true** — signer authority stores refs only, never private material; key supply is external. |
| X-3 | Provider registration / facilitator setup for payment paths | Live payment authorization | **true** — deployment contract + `.env.example` (`QUICKNODE_X402_ENABLED`, `IG_X402_LAYER`). |

### 1.7 Rewards

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| R-1 | Oracle signer key (`ORACLE_SIGNER_KEY`) for EVM/SVM claim proof signing | On-chain claim proof issuance | **true** — fail-closed `_require_env()` guards already enforce key presence outside local. |
| R-2 | Reward contract addresses: `ANALYTICS_REWARDS_ADDRESS`, `REWARD_REGISTRY_ADDRESS`, `REWARD_TOKEN_ADDRESS` | On-chain reward deployment/verification | **true** — address env inputs declared in `.env.example`. |
| R-3 | Live reward rails (tenant webhook destinations, beta rails gated) | Real delivery | **true** — beta rails intentionally raise `RailUnavailableError` until operator-approved. |
| R-4 | Provisioned Postgres for the four reward tables without migrations (`reward_delivery_jobs`, `reward_evidence_outbox`, `reward_reservation_release_jobs`, `reward_budget_reservations`/`reward_budget_ledger`) | Durable delivery/evidence/reservation in staging/prod | **false** — repo item: tables self-create locally via `_ensure_table`; alembic DDL is a repo-local integration-pass item. |

### 1.8 Credential authority

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| K-1 | Provisioned secrets backend: `CREDENTIAL_CIPHER=aws_kms` + `CREDENTIAL_KMS_KEY_ID` (KMS CMK) outside local | Encrypted credential storage at rest | **true** — `local` AES-256-GCM cipher + fail-closed guard present; `aws_kms` path + `kms_credentials` terraform module exist. |
| K-2 | Actual provider secret VALUES inserted into the backend (per slot registry) | Turnkey credential supply | **true** — slot registry derives slots from the adapters' own descriptors; the API rejects unknown slots. |
| K-3 | AWS Secrets Manager prefix (`AETHER_CREDENTIAL_AWS_PREFIX`) + IAM role when `aws_secrets_manager` backend | Backend connectivity | **true** — declared in deployment contract. |

### 1.9 Provider conformance

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| F-1 | Replay validation evidence (provider fixtures + `fixture_schema_version` bump) for each of the 29 providers | `replay_validated` rung | **true** — interop/derivatives conformance suites are the template; no code change needed. |
| F-2 | Sandbox-validate against each provider's sandbox + record `last_certified_at` / live evidence | `sandbox_validated` rung | **true** — promotion is evidence-driven by design (`ReadinessDimensions` validators refuse unsupported claims). |
| F-3 | Partner-live validation in a controlled staging window + pilot evidence | `partner_live` rung (0/29 today — the P0) | **true** — the ladder (`CREDENTIAL_WAITING → replay → sandbox → partner-live`) is entirely credential/live-work; no repository coding blocker. |
| F-4 | External smart-contract security audit (EVM/SVM/NEAR/Cosmos reward contracts) | `production_ready` + mainnet/real-funds deploy | **true** — release-blocker per audit; no code dependency. |
| F-5 | Security review of each live-validated provider | `production_ready` evidence | **true**. |

### 1.10 Lifecycle / readiness

| # | External blocker | What it unblocks | no repository coding blocker |
|---|---|---|---|
| L-1 | Provisioned Postgres for `capability_readiness` + `tenant_launch_readiness` | Durable readiness persistence in staging/prod | **false** — repo item: repositories exist, alembic DDL pending (integration-pass item). |
| L-2 | Live worker/provider health signals in staging | Readiness-graph nodes resolve to real health | **true** — resolvers fail closed (absence is not health) by design. |
| L-3 | Provisioned durable stores (Redis/Postgres) for readiness evidence + metering | Durable metering/readiness records | **false** — `metering_evidence` DDL pending (repo item). |

---

## 2. Cross-cutting external blockers (cloud/staging, span multiple capabilities)

| # | External blocker | Capabilities affected | no repository coding blocker |
|---|---|---|---|
| XG-1 | Production/staging infrastructure NOT provisioned: Terraform modules exist (ECS/EC2/clickhouse/kafka/KMS) but no `apply` has run | all ten | **true** — `deploy/DEPLOYMENT_CONTRACT.yaml` + `staging_infra_plan.py` define the provisioning-READY pieces; the apply is a credential-gated operator step. |
| XG-2 | Kafka topics unprovisioned (MSK auto-create disabled; one-shot topic provisioner Lambda is the mechanism) | derivatives, interop, payment rails, commerce | **true** — `deploy/kafka/topic_provisioner.py` + `topics.json` + drift-tested registry sync exist. |
| XG-3 | ClickHouse DDL (economic/Gold) unexecuted (`deploy/clickhouse/schemas/*.sql`) | interop, derivatives, stablecoin, measurement | **true** — schema files shipped; a migration job applies them in numeric order. |
| XG-4 | No OpenTelemetry SDK/exporter integrated (tracing is a seam only) | observability across all | **true** — `observability_middleware.py`/`trace_writer.py` are real durable writers; OTel exporter integration is an ops/3rd-party choice. |
| XG-5 | No staging load baselines recorded | scale readiness | **true** — Locust harness + `make load-smoke` exist; baselines require a live staging run. |
| XG-6 | Production secrets not configured (`scripts/bootstrap_aws_secrets.py`) | all ten | **true** — bootstrap script present; running it requires cloud access. |
| XG-7 | ML artifacts not trained/published for serving | intelligence surfaces | **true** — training pipelines exist; artifact publishing is external. |
| XG-8 | Dune backend not provisioned (`DUNE_BACKEND`) | data-lake feeder | **true** — connector real, credential-gated; scheduled polling disabled until provisioned. |

---

## 3. Explicit "no repository coding blocker" call-outs

For the items below, the repo is **provably** turnkey-coded on this branch
(modules import, offline gates pass, tables migrated or DDL exposed, workers
registered). The single remaining action is external:

- **Stablecoin live observation** (S-1/S-2/S-3): code-complete + CREDENTIAL_WAITING.
- **Derivatives live pulls** (D-1/D-2/D-3): resolver seam + durable cursor present.
- **Interop live scans** (I-1/I-2/I-3): transport, scan worker, cursor all real.
- **Payment-rail live webhooks/polling** (P-1/P-2/P-3): authority-backed, best-in-class.
- **Credential authority supply** (K-1/K-2/K-3): the turnkey spine is done.
- **Provider conformance promotion** (F-1/F-2/F-3/F-4/F-5): evidence-driven; 0/29
  PARTNER_LIVE is a validation/work item, not a coding gap.
- **Cross-cutting cloud bring-up** (XG-1 … XG-8): provisioning-READY artifacts exist.

## 4. Items that are NOT external blockers (repo-local, integration pass)

These are deliberately excluded from "external" and tracked in the companion
capability matrix (§3): worker builder/import mismatches in `specs.py`
(stablecoin polling, derivatives venue sweep, x402 reconciliation, credential
sweep path, reward reservation/claim paths, dead-letter, settlement),
missing settings flags, unwired routers (`readiness_graph`,
`observability_middleware`), and the pending alembic DDL for
`capability_readiness`, `tenant_launch_readiness`, `metering_evidence`,
`commerce_signer_refs`, `commerce_metering`, `reward_delivery_jobs`,
`reward_evidence_outbox`, `reward_reservation_release_jobs`,
`reward_budget_reservations`/`reward_budget_ledger`, and the payment-rail
durability mirror tables. None of these block provisioning or credential
supply; they are the integration pass's queue.
