---
title: Frontend QA
slug: operations/frontend-qa
section: operations
visibility: I
audience: [dev-senior, ops, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Frontend QA

QA audit across the three apps: **Aether** (tenant), **Kyber** (operator), and
**Demo**. All run against the real FastAPI backend; a clean backend is empty.

## Apps & surfaces

| App | Port | Key surfaces |
| --- | --- | --- |
| Aether | 5175 | onboarding, profile/graph, recommendations, decisions/actions, outcome ledger, playbooks, **integrations/connectors**, audit exports, value review, usage & plan, security & governance, system status, **data quality** |
| Kyber | 5174 | mission, tenants, implementation, customer success, **revops**, security & governance, reliability, **intelligence quality**, **connector health**, packages, deployment readiness, GTM/sales |
| Demo | 5177 | SDK + no-SDK ingestion → graph → reco → decide → act → outcomes → Kyber view |

## Audit checklist (status)

- [x] **Routes/nav**: every nav entry resolves to a routed page; no dead ends.
  Aether nav = inline `NavItem`s; Kyber nav = `NAV_ITEMS` (single source).
- [x] **Empty/loading/error**: pages use `@aether/ui` `LoadingState` / `EmptyState`
  / `ErrorState`; data hooks handle all three.
- [x] **Permission gating**: Kyber operator surfaces are operator-gated; Aether
  shows only current-tenant data; Kyber aggregate views are tenant-anonymous.
- [x] **Live-empty**: normal local startup uses the backend and shows successful
  empty or unavailable states without browser fixtures or MSW interception.
- [x] **Failure truth**: backend/network failure is visibly unavailable and
  never becomes empty-success or a successful local mutation.
- [x] **Tests**: Aether vitest, Kyber vitest (unit/component/integration) +
  Playwright e2e smoke, Demo vitest render. Run via `npm run test:frontend` /
  `test:e2e`.
- [ ] **Mobile/tablet + a11y**: sanity only; full responsive + a11y pass is
  deferred to a production designer (see [UX Handoff Notes](UX-HANDOFF-NOTES.md)).

## Run

```bash
npm run test:frontend     # aether + kyber + demo vitest
npm run test:e2e          # kyber Playwright smoke
python scripts/validate_frontend_data_truth.py
```

See [UX Handoff Notes](UX-HANDOFF-NOTES.md) and [Demo App UX](DEMO-APP-UX.md).
