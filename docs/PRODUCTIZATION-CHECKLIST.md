---
title: Productization Checklist
slug: operations/productization-checklist
section: operations
visibility: I
audience: [exec, architect, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# Productization Checklist

A running checklist of the productization surfaces and their readiness. See
[Productization](PRODUCTIZATION.md) for the gap analysis this complements.

## Governance & Control Plane

- [x] Centralized access control (tenant + Olympus roles, permission domains incl.
      `reliability`, `data_quality`)
- [x] Policy engine, security audit ledger (tamper-evident), tenant isolation
      verifier
- [x] Break-glass operator access, data retention + data requests, governance
      evidence packs
- [x] Routes: `/v1/security/*`, `/v1/admin/kyber/security/*`

## Reliability / SRE

- [x] Service / pipeline / queue health registries, incidents, runbooks, SLOs,
      postmortems, tenant impact
- [x] Tenant-safe status: `/v1/status/*`; operator: `/v1/admin/kyber/reliability/*`

## Data Quality / Intelligence Quality

- [x] Intelligence quality score + drift detection + contamination escalation
- [x] Tenant `/v1/data-quality/*`, operator `/v1/admin/kyber/intelligence-quality/*`
- [x] Aether Data Quality page, Kyber Intelligence Quality page

## Live Telemetry

- [x] Flag-guarded live signals across onboarding, customer success,
      billing/revops, reliability, and data quality
- [x] Dependency failure is unavailable/error, never a synthetic or empty-success
      fallback

## External Billing Readiness

- [x] `BillingProvider` interface; internal-only default; Stripe stub behind flags
- [x] Provider/mapping status in RevOps; tenant payment status

## Frontend

- [x] Aether tenant surfaces (onboarding, value, usage, security, status, data
      quality, audit exports)
- [x] Kyber operator surfaces (reliability, intelligence quality, revops, security,
      implementation, packages, deployment readiness, GTM)
- [x] Aether/Kyber live API runtime only; no browser MSW startup or normal mock
      environment
- [x] Fail-closed frontend environment validation and scoped legacy-worker/cache
      migration
- [x] Repository validator rejects runtime fixture imports and known synthetic
      production-bundle literals
- [x] Versioned backend demo seed/status/verify/reset pipeline, idempotency, and
      tenant-isolated reset (merged in PR #494)
- [ ] Clean-install, API-unavailable, seed, reset, staging, and production
      certification. Local data-truth and route-state evidence exists, but
      credentialed staging and hosted execution evidence is still required.

## Frontend Intelligence Five-Phase Program

- [x] Phase 1: canonical exploration client/provider, query cancellation and
      stale-response protection, result-table query semantics, and canonical
      truth/capability states
- [x] Phase 2: context-preserving entity, profile, graph, cluster, campaign,
      journey, and geo exploration workflows
- [x] Phase 3: mounted comparison workbench with preflight/finding truth guards,
      plus exact canonical context transport and durable saved views in Noesis
- [x] Phase 4: canonical domain truth/readiness presentation and verified
      mutation postconditions on the implemented connector, reward, delivery,
      stablecoin, derivatives, interop, and payment-rail paths
- [ ] Phase 5 release certification: make the complete hosted test tree green,
      execute credentialed provider and staging rehearsals, record
      accessibility/performance/rollback evidence, and obtain a GO verdict.
      Until then the release verdict is **NO-GO**.

## OODA Suggestion Intelligence

- [x] Canonical `Suggestion` entity: 15 statuses, 8 OODA phases, full audit trail
- [x] Lifecycle state machine with legal-transition enforcement and terminal-state guards
- [x] Policy engine: approval gates for high-risk classes + risk_score ≥ 0.7 + irreversible actions
- [x] Priority scorer: weighted composite formula, P0–P3 thresholds, class overrides
- [x] Tenant isolation: every query, event, cache key, and channel scoped by `tenant_id`
- [x] Secret redaction: `redact_for_tenant()` strips operator-only and sensitive fields
- [x] Signal adapters: data quality, SDK health, SDK drift, graph, profile360, notification, recommendation, governance, reliability, Noesis (10 total)
- [x] Outcome loop: `MEASURED → LEARNED → CLOSED` with learning feedback signals
- [x] Kyber operator surfaces: OODA command center + review queue (`/intelligence/suggestions`, `/intelligence/suggestions/review`)
- [x] Aether tenant surfaces: suggestion feed + feedback controls (`/suggestions`)
- [x] Noesis read-only intents: lookup, summary, review queue, explain, outcome lookup
- [x] Realtime channels: `suggestions.feed`, `suggestions.review`, `suggestions.outcomes`
- [x] Feature flags: `AETHER_SUGGESTIONS_ENABLED`, `AETHER_SUGGESTIONS_EXECUTION_ENABLED` (default false)
- [x] 13 backend unit test files covering lifecycle, scorer, policy, tenant isolation, adapters, outcome
- [x] Backfill script: `scripts/backfill_suggestions.py` (`--dry-run`, `--tenant-id`, `--source`, `--limit`)

## Deployment & Local Dev

- [x] Env-driven config, safe-by-default feature flags, documented local commands
- [x] `.env.example` covers all new flags and placeholders
- [x] Normal local startup is backend-backed and never seeds automatically
- [x] Backend seed policy refuses production and requires an explicit staging
      policy and tenant allowlist (merged in PR #494)

## Reward Enablement (A6)

- [x] Oracle signer key guarded — `ORACLE_SIGNER_KEY` blocks Hardhat/Anvil default in non-local
      (`_require_env()` in `services/oracle/routes.py` and `services/rewards/routes.py`)
- [x] Durable storage enforced — `REWARD_REQUIRE_DURABLE_STORE=true` causes startup failure
      without PostgreSQL in non-local environments
- [x] Tenant isolation — every reward table has `tenant_id`; all queries tenant-scoped;
      cross-tenant access returns 403
- [x] Idempotency — `(tenant_id, idempotency_key)` unique constraint in
      `reward_eligibility_decisions`; duplicate events return the same decision
- [x] No-custody language — no "Aether distributes", "Aether pays", or "Aether holds funds"
      in any route response, doc, or UI surface
- [x] Consent gating — reward decisions respect `requires_consent_purposes` from rule;
      missing consent → `blocked_consent` decision
- [x] Proof replay prevention — nonce `UNIQUE` constraint in `reward_proofs`;
      used proofs cannot be re-submitted
- [x] Audit log — all approve/reject/revoke/deliver actions appended to `reward_audit_log`
      (append-only, no updates)
- [x] Beta rail guard — beta rails (`stripe_credit`, `loyalty_points`, `coupon`,
      `internal_credit`, `x402_credit`) raise `RailUnavailableError(reason="beta_unavailable")`
- [x] Routes: `/v1/rewards/*` (37 endpoints across campaigns, rules, evaluate, decisions,
      actions, proofs, receipts, rails); operator view: `/v1/admin/kyber/rewards/*`
- [x] Frontend: Aether tenant (campaign-builder, decisions, approval-queue, rail-setup);
      Kyber operator (rewards-health, rewards-drilldown)

## Credential-Turnkey Pre-Staging Build Waves (2026-08-09)

Status of the credential-turnkey build waves on `claude/credential-turnkey-pre-staging`.
`[x]` = repository-controlled evidence present on this branch; `[ ]` = repo-local
integration item OR external/credential item still pending. Release verdict
remains **NO-GO** until live provider validation (0/29 `PARTNER_LIVE` today).

### Credential authority (durable, multi-slot, encrypted)

- [x] Durable multi-slot credential authority (`provider_credential_versions`, partial-unique
      indexes: one active + one previous per slot), encrypted at rest, single decrypt site,
      restart/replica-safe (migration landed `20260812_provider_credential_versions`)
- [x] Server-owned slot registry derived from adapter descriptors (unknown slot → 400);
      write-only tenant-admin API `/v1/providers/credentials/*`; operator-safe cross-tenant
      views never leak secrets (Kyber routes + `services/kyber/aggregate.py`)
- [x] Credential expiry/overlap sweep worker authored (`services/providers/credentials/sweeper.py`)
- [ ] Sweep worker import path in `services/runtime/specs.py` points at `credentials.sweep`; must
      resolve to `credentials.sweeper` (integration pass)
- [ ] Actual secret values + KMS CMK (`CREDENTIAL_CIPHER=aws_kms`) supplied in staging/production
      (external — see `reports/credential-turnkey-external-blockers.md`)

### Provider conformance / certification plane

- [x] Certification matrix now resolves **29 providers — all `CREDENTIAL_WAITING`** (added
      communications ×8 and agentic-commerce ×3 to the original 18 first-release economic
      providers); `credentialless-certification-strict` floor holds (no `SCAFFOLDED`)
- [x] Provider conformance contracts (`shared/integration_contracts/*`) with manifests for
      15 connectors + 5 observe-only payment rails + 3 deferred credit bureaus
- [ ] Zero `PARTNER_LIVE` providers — replay/sandbox/partner-live promotion is live-credential
      work (external P0); readiness remains pre-production

### Lifecycle / readiness plane

- [x] Tenant launch readiness (`/v1/tenant/readiness`, `/trust-states`) + tenant hook
      `use-tenant-readiness.ts`; fail-closed checklist (all-pending until recorded)
- [x] Capability readiness graph + supervised revalidation worker (auto-demote, never promote),
      fail-closed node resolvers (absence is not health)
- [ ] `capability_readiness` / `tenant_launch_readiness` / `metering_evidence` tables need
      alembic DDL (integration pass); Kyber readiness-graph router authored but unwired

### Durable delivery / reconciliation across the economic domains

- [x] Durable cursors: derivatives pull/stream cursors + stream-gap persistence, interop
      `interop_provider_checkpoints` checkpoint-resume contract (crash-safe, idempotent replay)
- [x] Reconciliation: stablecoin multi-provider price reconcile + payment/onchain reconcile,
      interop cross-leg variance evidence, reward claim reconciliation (proof nonce replay guard)
- [x] Repair: payment-rail canonical-repair safety net + readiness demotion (auth-error →
      `CREDENTIAL_INVALID`, silence → `DEGRADED`), reward reservation-release TTL sweep,
      reward durable delivery outbox (durable-before-ack, dead-letter)
- [x] Entitlement/meter seams: derivatives entitlement gate, payment-rail plan-tier gate,
      interop/derivatives/commerce/x402 usage meters (some durable sinks pending wiring)
- [ ] Worker builder/import mismatches in `services/runtime/specs.py` (stablecoin polling,
      derivatives venue sweep, x402 reconciliation, reward reservation/claim paths) must be
      corrected/authored (integration pass; all default-OFF so no startup impact)
- [ ] Reward delivery/evidence/reservation tables (`reward_delivery_jobs`,
      `reward_evidence_outbox`, `reward_reservation_release_jobs`,
      `reward_budget_reservations`/`reward_budget_ledger`) need alembic DDL for staging/prod
      durability (integration pass)

### Infra definition (provisioning-READY, not provisioned)

- [x] `deploy/DEPLOYMENT_CONTRACT.yaml` declares per-capability required services/secrets/
      public URLs/registration steps; Kafka topic provisioner + `topics.json`; ClickHouse DDL
      schemas; KMS credential module; `scripts/bootstrap_aws_secrets.py`
- [ ] Cloud apply, credential supply, public URL routing, provider-app registration, and live
      certification remain external (staging/cloud access required)

## Partner ecosystem / marketplace / developer platform

Partner ecosystem, marketplace, and developer-platform functionality are
**future-flagged and intentionally not implemented in this pass**. The flags
`AETHER_PARTNER_ECOSYSTEM_ENABLED`, `AETHER_MARKETPLACE_ENABLED`,
`AETHER_DEVELOPER_PLATFORM_ENABLED`, and `KYBER_PARTNER_ECOSYSTEM_ENABLED` exist,
default off, and gate nothing yet. No partner models, routes, UI, or external
partner APIs are shipped. This can be built later without a config migration.
