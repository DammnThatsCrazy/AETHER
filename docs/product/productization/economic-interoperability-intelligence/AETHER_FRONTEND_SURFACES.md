---
title: Aether Frontend Surfaces
slug: productization/economic-interoperability-intelligence/aether-frontend-surfaces
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [apps/aether-web/src/components/domain-intelligence.tsx, apps/aether-web/src/pages/stablecoins/stablecoins-page.tsx, apps/aether-web/src/pages/stablecoins/stablecoin-asset-page.tsx, apps/aether-web/src/pages/derivatives/derivatives-page.tsx, apps/aether-web/src/pages/derivatives/derivatives-account-page.tsx, apps/aether-web/src/pages/interop/interop-page.tsx, apps/aether-web/src/pages/interop/interop-message-page.tsx]
canonical_owner: platform@aether
source_hashes:
  "apps/aether-web/src/components/domain-intelligence.tsx": "sha256:818c565120a52371d5cd7416e94ba22f8f3e2ca72b580c01527392352759e48e"
  "apps/aether-web/src/pages/derivatives/derivatives-account-page.tsx": "sha256:030d32d90e9f36507d8c878f198bc657ac218b81f9b31d14e073ecac214eda8b"
  "apps/aether-web/src/pages/derivatives/derivatives-page.tsx": "sha256:2959331a1bfd86f16cde7df5d895c7eb1d4daa2e250b5483fab53b07ecc71487"
  "apps/aether-web/src/pages/interop/interop-message-page.tsx": "sha256:bf46716815880b9fe976741fc5b8ea082ac04af6a6a336443d3c41ceff5ae6a0"
  "apps/aether-web/src/pages/interop/interop-page.tsx": "sha256:fc196e5096138bae2c3f41f577604c029fd37dc4d5be7742d77b807cd3b1f397"
  "apps/aether-web/src/pages/stablecoins/stablecoin-asset-page.tsx": "sha256:fee2b7c5db892e57cb0a1e1171fe42d31553878a0e7097b6e11823e830c1bdda"
  "apps/aether-web/src/pages/stablecoins/stablecoins-page.tsx": "sha256:55a6c9bf8e268c8a9206e6d0b3720390ab32268d73fe17a6e2bc752da68d1d34"
---

# Aether Frontend Surfaces

Six pages (routes registered in `app/router.tsx`):

| Route | Page |
|---|---|
| `/stablecoins` | Assets, peg valuations (depeg badges), flow aggregates |
| `/stablecoins/:assetId` | Deployments + recent observations with finality |
| `/derivatives` | Accounts, linked venues (link by wallet proof, read-only key, venue OAuth or tenant push; sync, disconnect, revoke), positions, P&L snapshots, reconciliation variances |
| `/derivatives/propagation` | Compute and save propagation runs over linked members; saved runs show whether they are out of date and can be recomputed |
| `/derivatives/oauth/return` | Landing page that redeems a venue OAuth state once |
| `/derivatives/accounts/:accountId` | Orders, fills, positions for one account |
| `/interoperability` | Messages, paths, providers with honest ImplementationStatus |
| `/interoperability/messages/:messageId` | Lifecycle timeline, delivery attempts, asset legs |

Conventions:

- Data via `lib/api/endpoints.ts` groups parsing the raw
  `{items, count}` responses (these routes do not use the APIResponse
  envelope).
- Feature-flagged-off backends 404 → shared `NotEnabledOrError` renders
  an honest "not enabled" EmptyState (`components/domain-intelligence.tsx`).
- Independent endpoint reads keep independent loading and failure states. A
  successful primary read cannot turn a failed valuation, flow, position,
  reconciliation, path, or observation read into a measured zero.
- Evidence disclosures identify backend/provider provenance and preserve the
  units returned by the source. Unlike assets are not converted, netted, or
  summed in the browser.
- Stablecoin finality, interoperability lifecycle labels, derivatives P&L, and
  reconciliation states are reported observations, not Aether execution,
  settlement, current-price, or global-reconciliation guarantees.
- Provider readiness comes from the backend implementation status;
  credential-gated and scaffolded adapters are not presented as live.
- Every page states its no-execution boundary in the header copy.
- Page tests mock the endpoints module (existing connectors-page pattern).
