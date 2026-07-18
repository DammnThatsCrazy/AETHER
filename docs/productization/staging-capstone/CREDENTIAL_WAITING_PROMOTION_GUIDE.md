---
title: "Credential-Waiting Promotion Guide"
slug: productization/staging-capstone/credential-waiting-promotion-guide
section: operations
visibility: I
audience: [architect, ops, security]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/certification/readiness.py
  - Backend Architecture/aether-backend/shared/certification/checks.py
canonical_owner: platform@aether
last_synced_commit: "ac900d5"
---

# Credential-Waiting Promotion Guide

How a first-release provider moves from `credential_waiting` toward live. There
is **no imperative state machine** — promotion is evidence-driven. The registry
re-resolves each provider's state from source, and `ReadinessDimensions`
validators refuse any state the evidence does not support. You cannot type a
higher state; you must produce the evidence.

## The ladder

```
credential_waiting (2)  ->  replay_validated (3)  ->  sandbox_validated (4)  ->  partner_live (5)
```

`production_ready` is a SEPARATE claim layered on top — never inferred from
structure.

## Gate at each rung (enforced by readiness.py + checks.py)

| Target | Required evidence | Also enforced by `check_honest_status` |
|---|---|---|
| `replay_validated` | `replay_validated=True` | a declared `fixture_schema_version` or `ctx['replay_evidence']` |
| `sandbox_validated` | `sandbox_validated=True` (implies `replay_validated`) | live evidence (`ctx['live_evidence']` or `last_certified_at`) |
| `partner_live` | `live_validated=True` (implies `credential_supplied`) | live evidence present |
| `production_ready` | `live_validated AND security_reviewed` (+ `externally_audited` if `requires_external_audit`) | — |
| `pilot_ready` | `code_complete AND infra_defined AND replay_validated` | — |

## Promotion procedure

1. **Supply the credential/endpoint** listed in
   `CREDENTIAL_SECRET_REFERENCE.md` (vault ref for payments, read-only API key
   for derivatives, per-network JSON-RPC for interop/stablecoin).
2. **Replay-validate:** capture provider fixtures, bump the descriptor's
   `fixture_schema_version`, and prove decode/normalization against them
   (`replay_validated`). The interop and derivatives conformance suites are the
   template.
3. **Sandbox-validate:** run against the provider's sandbox and record
   `last_certified_at` / `ctx['live_evidence']` (`sandbox_validated`).
4. **Partner-live:** validate against the live provider in a controlled staging
   window and capture pilot evidence (`PILOT_EVIDENCE_GUIDE.md`).
5. **Security review** (and external audit where required) before any
   `production_ready` claim or scorecard bump.

## Verify

- `make credentialless-certification-strict` — every first-release provider is
  at least `credential_waiting`, none `scaffolded`.
- `make production-status` — the scorecard must not describe a provider as
  production-ready without live evidence. Update the scorecard AND
  `docs/productization/aether_productization_audit.md` together.

## Never do

- Never set a higher `state` by hand to make the matrix look further along.
- Never claim `production_ready` from code completeness alone.
- Never enable a provider rollout flag before its rung-4/5 evidence exists.
