---
title: "Partner Onboarding Guide"
slug: productization/staging-capstone/partner-onboarding-guide
section: operations
visibility: I
audience: [ops, architect, buyer]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
---

# Partner Onboarding Guide

Onboarding a data/integration partner (a provider whose observations AETHER
ingests, or a tenant integrating the SDK). Self-serve tenant signup mechanics
are owned by `docs/CUSTOMER-ONBOARDING.md`; this guide covers the parts specific
to the credential-waiting economic providers.

## 1. Scope the integration

- Identify the provider domain (payments / derivatives / interop /
  stablecoin_chain) and confirm it exists in the capability matrix
  (`PROVIDER_CAPABILITY_MATRIX_GUIDE.md`). If the provider is not in the
  first-release scope, it is out of scope for this cycle.
- Confirm the integration is **observation-only**. AETHER never initiates
  payments, trades, or cross-chain messages. A partner asking for execution is a
  scope mismatch.

## 2. Consent and data rights

- Every ingest path is consent-gated. Confirm the partner's data-sharing basis
  and the tenant consent purpose before enabling ingestion
  (`docs/source-of-truth/CONSENT_MODEL.md`,
  `docs/source-of-truth/INTEGRATION_CONSENT_REGISTRY.md`).
- Card-linked and identity-bearing flows have hard PII/region/consent gates —
  a rejected ingest during onboarding is usually a missing consent basis, not a
  bug.

## 3. Credentials

- Provision the secret(s) from `CREDENTIAL_SECRET_REFERENCE.md` into the vault
  under the documented ref. Read-only for derivatives; webhook signing secret
  for payments; per-network RPC for interop/stablecoin.
- Never accept a credential with trade/withdraw/execution scope.

## 4. Validate before enabling

- Run replay → sandbox validation per `CREDENTIAL_WAITING_PROMOTION_GUIDE.md`.
- Keep the provider rollout flag OFF until one lifecycle has been observed end to
  end in staging and reconciliation is clean.
- Capture the run as pilot evidence (`PILOT_EVIDENCE_GUIDE.md`).

## 5. Handover

- Point the partner's operators at the relevant runbook in `docs/runbooks/`.
- Record the provider, consent basis, credential ref, and validation evidence in
  the onboarding record.

## Never do

- Never enable a partner provider in production before live + security evidence.
- Never onboard an execution/custody integration — AETHER is observation-only,
  no-custody.

See also: `docs/CUSTOMER-ONBOARDING.md`,
`docs/productization/staging-capstone/DESIGN_PARTNER_PRIVATE_BETA_OPERATING_GUIDE.md`.
