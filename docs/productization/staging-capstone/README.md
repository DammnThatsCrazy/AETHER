---
title: "Staging Capstone — Operating Guide Set"
slug: productization/staging-capstone/readme
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 2
---

# Staging Capstone — Operating Guide Set

This directory is the operating documentation for the state AETHER reached
across the staging-readiness PR series (1–6): canonicalization, the
credentialless certification plane, all 29 first-release providers at
`CREDENTIAL_WAITING`, security correctness fixes, durable budget/outbox, and the
supervised agent real seam with approval invariants.

The honest headline: AETHER is **release-shaped and credential-waiting / pilot-
ready — NOT production-ready**. No first-release economic provider has been
validated against a live endpoint, and no mainnet smart-contract deployment is
permitted before external audit. The canonical readiness figures live in
`scripts/production_status.py` (`make production-status`) and its dated narrative
`docs/productization/aether_productization_audit.md`.

## Contents

| Guide | Purpose |
|---|---|
| `PROVIDER_CAPABILITY_MATRIX_GUIDE.md` | How to read the generated capability matrix and provider states |
| `CREDENTIAL_SECRET_REFERENCE.md` | Which secrets each provider needs and where they live |
| `CREDENTIAL_WAITING_PROMOTION_GUIDE.md` | How a provider moves from credential-waiting toward live |
| `PILOT_EVIDENCE_GUIDE.md` | What evidence a pilot must capture before any score moves |
| `PARTNER_ONBOARDING_GUIDE.md` | Onboarding a data/integration partner |
| `DESIGN_PARTNER_PRIVATE_BETA_OPERATING_GUIDE.md` | Running the private beta with design partners |
| `STAGING_DEPLOYMENT_GUIDE.md` | Bringing up a staging environment safely |
| `DISASTER_RECOVERY_GUIDE.md` | Recovery objectives and per-subsystem procedures |
| `EXTERNAL_AUDIT_PREPARATION_GUIDE.md` | Getting the smart contracts ready for external audit |
| `LIMITATIONS_AND_NON_GOALS.md` | What AETHER deliberately does NOT do (yet) |

## Related

- Runbooks: `docs/runbooks/` (payment-rails, card-linked, stablecoin-observer,
  derivatives-stream, interop-observer, reward-delivery, EVM/SVM deploy-emergency,
  agent-runtime-mutation-review, staging-preflight).
- Economic domain readiness:
  `docs/productization/economic-interoperability-intelligence/RELEASE_READINESS.md`.
- Credentialless chaos/recovery evidence: `tests/chaos/`.
