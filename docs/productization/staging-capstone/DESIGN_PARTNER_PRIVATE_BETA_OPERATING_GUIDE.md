---
title: "Design-Partner / Private-Beta Operating Guide"
slug: productization/staging-capstone/design-partner-private-beta-operating-guide
section: operations
visibility: I
audience: [exec, ops, architect]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
---

# Design-Partner / Private-Beta Operating Guide

How to run AETHER as a private beta with a small number of design partners while
it is credential-waiting / pilot-ready. The operating principle: **be explicit
about what is and is not validated**, and never let a partner infer production
guarantees that the scorecard does not support.

## Entry criteria

- The subsystems the partner will touch are at least release-ready (4) on the
  scorecard, or the partner has explicitly accepted a pilot of a lower-scored
  area (e.g. an economic domain at 3, card-linked at 2).
- A staging environment is up per `STAGING_DEPLOYMENT_GUIDE.md` with the
  preflight gate green.
- Consent basis and credentials are in place per
  `PARTNER_ONBOARDING_GUIDE.md`.

## What to promise (and what not to)

- **Promise:** observation-only intelligence, tenant isolation, consent
  enforcement, durable ingest, and the recovery behaviors proven in
  `tests/chaos/` (rate-limit/timeout/reorg/disconnect/idempotency/DLQ recovery).
- **Do not promise:** live provider coverage that has not been validated,
  mainnet reward payouts (blocked pending external audit), recorded scale
  baselines (not yet captured), or any `production_ready` claim.

## Operating cadence

1. **Weekly readiness check:** run `make production-status`; share the honest
   scorecard, not a rounded-up version.
2. **Per-domain operations:** operators use the `docs/runbooks/` set; escalate
   with the exact failing command.
3. **Evidence capture:** every partner pilot produces evidence per
   `PILOT_EVIDENCE_GUIDE.md`. Evidence is what moves a score, not partner
   enthusiasm.
4. **Kill switches:** every economic/agent surface is flag-gated and default
   OFF. Keep a documented rollback: flag off > redeploy.

## Exit / graduation

A subsystem graduates from beta only when it has live + security evidence and
the scorecard reflects it (scorecard and audit updated together). Graduating the
smart-contract rails additionally requires a clean external audit.

## Never do

- Never round the scorecard up for a partner conversation.
- Never enable a live provider or mainnet rail to unblock a demo.
- Never run a design partner against production data without consent + isolation
  verified (`docs/TENANT-ISOLATION-VERIFICATION.md`).

See also: `PILOT_EVIDENCE_GUIDE.md`, `STAGING_DEPLOYMENT_GUIDE.md`,
`LIMITATIONS_AND_NON_GOALS.md`.
