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
last_synced_commit: "71d96f6"
---

# Credential-Waiting Promotion Guide

How a first-release provider moves from `credential_waiting` toward live.
Promotion is evidence-driven at BOTH layers:

* **Adapter (build-time) state** — the registry re-resolves each provider's
  state from source, and `ReadinessDimensions` validators refuse any state the
  evidence does not support. You cannot type a higher state; you must produce
  the evidence.
* **Tenant (runtime) state** — per-(tenant, provider, environment, capability)
  lifecycle state is persisted in `capability_activation_states` and moves
  ONLY through the machine-enforced `CapabilityLifecycleAuthority`
  (`services/capabilities/lifecycle.py`): strictly single-step promotions,
  fail-closed evidence/credential/entitlement preconditions, every transition
  recording actor, reason, evidence references, and the bound credential
  version. Credential rotation demotes to `credential_supplied`; revocation
  demotes to `revoked`.

## The ladder

```
credential_waiting (20) -> credential_supplied (40) -> connection_validated (50)
    -> sandbox_validated (60) -> partner_live (70)
```

(`replay_validated` (30) is the credential-free structural proof rung for
adapter certification; ranks are spaced by 10 and only relative order is
contractual — see `packages/shared/contracts/readiness-vocabulary.json`.)

`production_ready` is a SEPARATE claim layered on top — never inferred from
structure, and never an enum state.

## Gate at each rung (enforced by readiness.py + checks.py)

| Target | Required evidence | Also enforced by `check_honest_status` |
|---|---|---|
| `replay_validated` | `replay_validated=True` | a declared `fixture_schema_version` or `ctx['replay_evidence']` |
| `sandbox_validated` | `sandbox_validated=True` (implies `replay_validated`) | live evidence (`ctx['live_evidence']` or `last_certified_at`) |
| `partner_live` | `live_validated=True` (implies `credential_supplied`) | live evidence present |
| `production_ready` | `live_validated AND security_reviewed` (+ `externally_audited` if `requires_external_audit`) | — |
| `pilot_ready` | `code_complete AND infra_defined AND replay_validated` | — |

## Tenant promotion procedure (runtime API)

1. `PUT /v1/providers/credentials/{provider}/slots/{slot}` — submit the
   credential (write-only), then `POST …/test` and `POST …/activate`.
2. `POST /v1/capabilities/activation/{provider}/{capability}/promote` with
   `target_state`, `environment`, `evidence_refs` — the authority refuses
   rung-skipping, unresolvable evidence, a missing ACTIVE credential version,
   or a missing entitlement.
3. Observe state + full history at
   `GET /v1/capabilities/activation/{provider}/{capability}`.
4. Suspend/resume via the corresponding endpoints; operators can
   emergency-suspend cross-tenant via `/v1/kyber/capabilities/activation/…`.

## Adapter promotion procedure (build-time evidence)

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
