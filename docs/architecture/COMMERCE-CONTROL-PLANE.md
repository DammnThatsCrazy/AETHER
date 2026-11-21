---
title: Agentic Commerce — Control Plane (Retired)
slug: api/commerce-control-plane
section: reference
visibility: P
audience: [architect, dev-senior]
status: deprecated
since_version: 0.1.0
source_files:
  - services/api/value/x402/routes.py
  - services/api/value/x402/settlement_observer.py
  - services/api/value/x402/verification.py
  - services/api/value/x402/provenance.py
  - services/api/value/x402/commerce_store.py
  - services/api/value/x402/commerce_models.py
  - services/api/governance/diagnostics/routes.py
canonical_owner: commerce@aether
estimated_read_minutes: 2
toc_depth: 3
source_hashes:
  "services/api/governance/diagnostics/routes.py": "sha256:bb2f2366e46d79164868bb2df1315e1c41d704f48f0ed4d04f4ceb68039a02b9"
  "services/api/value/x402/commerce_models.py": "sha256:50dbf80d7699ccdfcd5206d94a2dadc33ae73c1c06caac80da23e953320e282a"
  "services/api/value/x402/commerce_store.py": "sha256:c55caae3f9e9f81830f493b729c8bc5ef8ba1f4f6244628c7059580e429f216e"
  "services/api/value/x402/provenance.py": "sha256:fe227df986d4c03f770d97d6236bc4c5c5ee4410db66415dd38b7a697779d556"
  "services/api/value/x402/routes.py": "sha256:66e7776f519b954f6202966ec0091cc5e97e20808701f819b901a22cc46e01b3"
  "services/api/value/x402/settlement_observer.py": "sha256:46522979888495ad174b1dae683766579b6376561b456c0c2138fd43316f7a1d"
  "services/api/value/x402/verification.py": "sha256:61d0ae47bd75ad4b8c1285d75a42501e381149502b8a0db44d79c34963b03757"
---

# Agentic Commerce — Control Plane (Retired)

**Status:** retired by [ADR-012](decisions/ADR-012-observation-only-everywhere.md).
Aether is observation-only: it no longer runs an x402 paywall.

## What was removed

The control plane orchestrated `request → challenge → policy → approval →
verify → settle → entitle → grant → fulfill` with Aether as the gate. All of it
is gone:

- the HTTP 402 challenge middleware and protected-resource registry;
- spend policies, pricing and the mandatory approval workflow
  (`/v1/approvals`), entitlements (`/v1/entitlements`) and access grants;
- the tenant signer authority and the settlement tracker, its reconciliation
  worker and the commerce sweepers;
- commerce metering of challenge, payment and access stages;
- the `COMMERCE_CONTROL_PLANE_ENABLED` flag and the Kyber approval queue.

## What remains

| Surface | Behaviour |
|---|---|
| `POST /v1/x402/capture` | Records an x402 exchange a tenant's server observed. When the report carries a payment proof, `settlement_observer.py` verifies it on-chain and returns `settled`, `failed`, `pending`, `not_observable` or `conflicting`. |
| Settlement observer | The only authoritative x402 producer. Emits `COMMERCE_SETTLEMENT_COMPLETED` / `FAILED` as `x402.settlement_observer`; the lifecycle consumer projects them into `PaymentIntent` / `SettlementEvent`. A `pending` verdict records nothing terminal; reporting again re-checks the chain. |
| Verification engine | Unchanged on-chain checks (receipt status, matching transfer from payer to recipient of at least the amount, finality), using the tenant's own RPC credential. |
| Historical store | `commerce_store.py` and `commerce_models.py` keep records the control plane wrote. Agent 360, Workflow 360, analytics and `/v1/diagnostics/commerce/*` read them; erasure still covers them. |

Agent references on observed payments stay as reported until an identity
binding resolves them. There is no background re-check loop for pending
payments.
