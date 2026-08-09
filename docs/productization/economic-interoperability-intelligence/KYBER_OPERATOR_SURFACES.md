---
title: Kyber Operator Surfaces
slug: productization/economic-interoperability-intelligence/kyber-operator-surfaces
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - frontend/kyber/src/pages/stablecoins/kyber-stablecoins-ops-page.tsx
  - frontend/kyber/src/pages/derivatives/kyber-derivatives-ops-page.tsx
  - frontend/kyber/src/pages/interop/kyber-interop-ops-page.tsx
canonical_owner: platform@aether
last_synced_commit: "41c79d4"
---

# Kyber Operator Surfaces

Three ops pages against `/v1/admin/kyber/{stablecoins,derivatives/runtime,interop}`
(operator-gated backend; audited actions), flag-gated client-side by
`kyberStablecoinOps` / `kyberDerivativesOps` / `kyberInteropOps`
(default OFF; `FlagGate` renders an honest disabled state):

| Route | Capabilities |
|---|---|
| `/stablecoins/ops` | Registry status + seed-from-x402, finality checkpoints, reconciliation + unresolved-observation review |
| `/derivatives/ops` | Adapter fleet (honest ImplementationStatus + read-only credential badges), checkpoints, stream gaps, variances, conformance trigger |
| `/interoperability/ops` | Provider health + checkpoint lag, correlation health, security-policy drift, per-provider operational-state surface, governed-scan trigger (credential-gated providers refuse honestly — 409 until an RPC client is wired) |

Zod schemas in `lib/schemas/economic-ops.ts` parse the raw
`{items, count}` admin payloads with passthrough rows so provider-specific
fields render verbatim.
