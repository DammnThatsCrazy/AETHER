---
title: "Limitations & Non-Goals"
slug: productization/staging-capstone/limitations-and-non-goals
section: operations
visibility: I
audience: [exec, architect, ops, buyer]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
---

# Limitations & Non-Goals

An honest, single-page statement of what AETHER does **not** do (yet) at the
staging-capstone point. If a claim elsewhere contradicts this page, this page
and `make production-status` win. The overall posture is **release-shaped,
credential-waiting / pilot-ready — NOT production-ready**.

## Current limitations (things we intend to do, not done yet)

- **No live economic provider.** All 29 first-release providers are
  `credential_waiting`: code-complete and credential-gated, none validated
  against a live endpoint. See `PROVIDER_CAPABILITY_MATRIX_GUIDE.md`.
- **No mainnet smart-contract deployment.** Blocked pending external audit
  (`EXTERNAL_AUDIT_PREPARATION_GUIDE.md`). On-chain reward proofs stay gated.
- **No recorded scale baselines.** The Locust harness exists; staging baselines
  are not captured. Neptune throughput/cost and identity-merge throughput are
  unvalidated at scale.
- **Infrastructure not provisioned; ML artifacts not trained.** Terraform exists
  but is not stood up; production secrets are not loaded; ML serving artifacts
  are not published.
- **Economic domains are pre-production.** Stablecoin, derivatives, interop, and
  payment-rail observability are at 3/5; card-linked is at 2/5. All rollout flags
  default OFF and no live data has flowed through them.
- **Some read paths deferred.** e.g. the Silver import projector, the in-code
  metric registry's TS twin, end-to-end MeasurementContext threading — tracked,
  not shipped.

## Non-goals (deliberate; not on the roadmap for this phase)

- **Execution / custody.** AETHER is observation-only and no-custody by
  construction. It never initiates or settles a payment, never places or cancels
  a trade, never sends a cross-chain message, and never holds funds. A request
  for execution or custody is a scope mismatch, not a feature gap.
- **Direct agent graph mutation.** Agents never write the graph directly — every
  mutation goes through staged review → operator approval → commit.
- **Optimistic readiness.** The certification plane refuses to infer
  `production_ready` from structure; a score never moves without live + security
  evidence. "Looks complete" is not a readiness claim.
- **Bare-zero metrics.** The measurement integrity plane never emits a bare `0`
  on missing/insufficient data — it carries an explicit `value_state`.

## How this stays honest

The canonical readiness source is `scripts/production_status.py`
(`make production-status`); its dated narrative is
`docs/productization/aether_productization_audit.md`. They are updated together
and the audit is re-stamped whenever scores or evidence change. Do not describe
an area as production-ready in any doc unless the scorecard supports it.

See also: `docs/productization/aether_productization_audit.md`,
`CREDENTIAL_WAITING_PROMOTION_GUIDE.md`, `PILOT_EVIDENCE_GUIDE.md`.
