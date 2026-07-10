---
title: Aether Frontend Surfaces
slug: productization/economic-interoperability-intelligence/aether-frontend-surfaces
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - frontend/aether/src/pages/stablecoins/stablecoins-page.tsx
  - frontend/aether/src/pages/derivatives/derivatives-page.tsx
  - frontend/aether/src/pages/interop/interop-page.tsx
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Aether Frontend Surfaces

Six pages (routes registered in `app/router.tsx`):

| Route | Page |
|---|---|
| `/stablecoins` | Assets, peg valuations (depeg badges), flow aggregates |
| `/stablecoins/:assetId` | Deployments + recent observations with finality |
| `/derivatives` | Accounts, positions, P&L snapshots, reconciliation variances |
| `/derivatives/accounts/:accountId` | Orders, fills, positions for one account |
| `/interoperability` | Messages, paths, providers with honest ImplementationStatus |
| `/interoperability/messages/:messageId` | Lifecycle timeline, delivery attempts, asset legs |

Conventions:

- Data via `lib/api/endpoints.ts` groups parsing the raw
  `{items, count}` responses (these routes do not use the APIResponse
  envelope).
- Feature-flagged-off backends 404 → shared `NotEnabledOrError` renders
  an honest "not enabled" EmptyState (`components/domain-intelligence.tsx`).
- Every page states its no-execution boundary in the header copy.
- Page tests mock the endpoints module (existing connectors-page pattern).
