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

- [x] Flag-guarded live signals with in-memory fallback across onboarding,
      customer success, billing/revops, reliability, and data quality

## External Billing Readiness

- [x] `BillingProvider` interface; internal-only default; Stripe stub behind flags
- [x] Provider/mapping status in RevOps; tenant payment status

## Frontend

- [x] Aether tenant surfaces (onboarding, value, usage, security, status, data
      quality, audit exports)
- [x] Kyber operator surfaces (reliability, intelligence quality, revops, security,
      implementation, packages, deployment readiness, GTM)

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

## Partner ecosystem / marketplace / developer platform

Partner ecosystem, marketplace, and developer-platform functionality are
**future-flagged and intentionally not implemented in this pass**. The flags
`AETHER_PARTNER_ECOSYSTEM_ENABLED`, `AETHER_MARKETPLACE_ENABLED`,
`AETHER_DEVELOPER_PLATFORM_ENABLED`, and `KYBER_PARTNER_ECOSYSTEM_ENABLED` exist,
default off, and gate nothing yet. No partner models, routes, UI, or external
partner APIs are shipped. This can be built later without a config migration.
