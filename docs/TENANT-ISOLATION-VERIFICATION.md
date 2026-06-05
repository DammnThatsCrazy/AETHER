---
title: Tenant Isolation Verification
slug: enterprise/tenant-isolation-verification
section: enterprise
visibility: I
audience: [ops, security]
status: stable
since_version: "13.0.0"
---

# Tenant Isolation Verification

`TenantIsolationVerifier` (`services/security/isolation_verifier.py`) runs
structured checks over each tenant-scoped resource store and persists the results
so Kyber can show the latest run.

## Implemented controls

- Checks recommendations, decisions, actions, dispatches, outcomes, playbooks,
  audit exports, billing records, integration configs, onboarding / customer
  success scope, and that Kyber views are **aggregate-only**.
- Each check confirms every record carries a `tenant_id` and that no record is
  visible across tenant boundaries.
- Results are **summary-only**: check name, `pass`/`warn`/`fail` status, record
  counts, and sampled offending record ids — **never raw private tenant data**.
- Latest results are persisted (`IsolationResultRepository`) and surfaced at
  `GET /v1/admin/kyber/security/tenant-isolation`.

## Tenant vs Kyber visibility

Verifier results are an operator/Kyber surface. Tenants do not see other tenants'
isolation findings; the existence of isolation enforcement is documented to
tenants but raw cross-tenant counts are Kyber-only.

## Planned controls

- Scheduled background verification runs with alerting on `fail`.
- Row-level isolation assertions at the database layer in production deployments.

## Known gaps / not certified

- Verification samples and counts records via the repository layer; it is a
  detective control, not a preventive database constraint. No certification is
  claimed.
