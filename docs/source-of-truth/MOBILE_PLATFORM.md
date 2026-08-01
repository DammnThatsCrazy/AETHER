---
title: Mobile Platform & Productization Baseplate
slug: mobile/platform
section: mobile
visibility: I
audience: [architect, security, ops]
status: alpha
---

# Mobile Platform & Productization Baseplate

This document is the architecture entry point for the mobile / cross-device continuity /
notification productization program. It describes the **seven-system baseplate** the desktop, iOS,
and Android clients consume through bounded, product-appropriate projections — and, just as
importantly, what the program **does not** build because it already exists.

The living program state, the classified reuse map, and the external-blocker registry are the
machine-readable companions to this page:

- `reports/mobile-productization/PROGRAM_STATE.yaml` — single-authority milestone + migration ledger
- `reports/mobile-productization/repo-baseline.json` — every system, classified reuse/extend/build
- `reports/mobile-productization/external-blockers.json` — credential/account/infra blockers
- `reports/mobile-productization/decision-log.md` — reuse statements + architectural decisions
- `config/credential_contracts.yaml` — credential registry (references the credential platform)

## Scope of this session (Commits 0–4)

The program is a multi-milestone train (C0–C9). This session delivers the **foundation baseplate +
shared mobile platform** (C0–C4). Full app feature surfaces, governed mobile actions, compliance /
distribution pipelines, and adversarial review (C5–C9) are **documented and staged, not built this
session**. The honest completion ceiling for C0–C4 without provider credentials or store accounts is
`CODE_COMPLETE_CREDENTIALS_BLOCKED` + `READY_FOR_LOCAL_INTEGRATED_DEMO`.

## The product boundary

The desktop products remain the complete workspaces. Mobile is an **intelligence companion**, not a
graph on a phone: it tells the user what changed, why it matters, shows the evidence, lets them ask
a bounded question or take a safe approved action, and hands the work back to the desktop without
losing context. Mobile deliberately does **not** reproduce full graph traversal, large report
construction, bulk administration, secret management, or arbitrary operational access.

## The seven-system baseplate

Build the stable baseplate once; do not build mobile-specific business truth, desktop-specific
notification truth, or client-specific action truth.

| # | Plane | Owner (authoritative) | Program posture |
|---|---|---|---|
| 1 | **Domain truth** | existing backend services (profiles, campaigns, graph, journeys, identity, Kyber ops, …) | reuse — no mobile calculation may diverge |
| 2 | **Exploration context** | `shared/exploration/ExplorationContextV1` (+ TS twin, URL-backed) | reuse — continuation references it |
| 3 | **Continuation plane** | `services/continuation/` (NET-NEW) | build — server-owned handoff linking desktop/mobile state |
| 4 | **Insight & notification plane** | `services/notification_intelligence/` | extend — brand canonical, add TS twins + coverage + mobile projection |
| 5 | **Governed action plane** | tenant services + `services/kyber/ops/` command plane | reuse — mobile adapts; no new mutation channel |
| 6 | **Identity & device plane** | `services/auth/` + `services/kyber/{identity,devices,sessions,access}/` | extend — native installations, push identity, attestation, revocation |
| 7 | **Release & activation plane** | credential platform + deployment profiles + `config/credential_contracts.yaml` | reuse + extend — a credential activates existing capability; it never unlocks unfinished code |

### Four separated concepts (do not collapse)

```
domain event  →  interpreted insight  →  attention decision  →  notification  →  delivery  →  user interaction
```

Not every fact becomes an insight; not every insight becomes a notification; not every notification
goes to every channel. Provider-accepted ≠ delivered ≠ opened ≠ read ≠ acknowledged ≠ resolved.

## Net-new surfaces built this session

- **Continuation plane** (C1) — `services/continuation/`, direct-SQL + alembic (the generic
  JSONB repository cannot do the required compare-and-swap). Stores references + a bounded
  selection + a revision, never a whole graph. Introduces the **backend selection token**
  (`continuation_selections`) that the in-code marker in
  `frontend/aether/src/features/noesis/exploration-context.ts` asks for.
- **Client-sync feed** (C1) — `services/client_sync/`, a durable append-only change log with a
  gapless per-scope cursor. `GET /v1/client-sync?cursor=` emits ten change types for read-state /
  continuation / saved-view / conversation / watchlist / incident / command-receipt / preference /
  session / installation changes. The deferred realtime replay is not relied upon.
- **Push & email adapters** (C3) — APNs, FCM, Web Push (VAPID), and email, each with a
  provider-shaped local fake and secrets held only in the credential platform; provider fakes are
  impossible in production.
- **Installation & push model** (C3) — extends the tenant session and Kyber device planes with
  native installations and push subscriptions; push tokens are encrypted and hashed, never logged.
  The tenant mobile gateway is mounted at `/v1/mobile` (`services/mobile/routes.py`, flag
  `settings.mobile.enabled`, default OFF → 404): `POST/GET /v1/mobile/installations`,
  `GET/DELETE /v1/mobile/installations/{id}`, `POST /v1/mobile/installations/{id}/subscriptions`.
  Registration forces `app_kind=aether`; only a token's `token_hash` is stored. The Kyber
  operator gateway is deferred to the Kyber-mobile milestone.
- **Deep-link resolution** (C3) — `POST /v1/mobile/deep-links/resolve` turns an opaque
  continuation id (the only thing a deep link carries — never PII or a graph) into a bounded,
  reference-only continuation projection. Resolution is **fail-closed**: an unknown / unowned /
  revoked installation and a cross-scope / cross-plane / expired continuation all collapse to the
  same `{"resolved": false, "reason": "unresolvable"}` body, so a caller cannot probe for
  continuations it does not own. A `restricted` continuation requires a stepped-up session
  (`step_up` permission on the tenant plane; the Kyber device-proof step-up is the operator plane,
  deferred). It reuses the continuation records as the payload store — the link never carries the
  data itself.
- **Mobile apps + shared packages** (C4) — `apps/aether-mobile`, `apps/kyber-mobile` (Expo +
  prebuild) and `packages/mobile-*`. C4 lands compiling app shells with auth / API / notification /
  continuation / sync clients and a navigation skeleton; full feature screens are C5–C6.

## Invariants

- Mobile claim / push / deep link / continuation id are **not** authorization.
- Tenant identity and Kyber workforce identity stay separate; an Aether token cannot call Kyber.
- Unknown ≠ zero; partial ≠ complete; stale ≠ live; demo ≠ production. Credentials-missing is
  neither implementation-incomplete nor production-ready.
- All new wire contracts use **snake_case** field names (the contract-parity scraper cannot capture
  camelCase); the logical camelCase names are frontend-mapped aliases.

## Gate discipline

Every new surface ripples into `make ci-check` registries — a single alembic head, a storage policy
per table, feature-surface classification per route, TS public-export boundaries, and a clean
generated-docs tree. Each milestone commit is driven to `make ci-check` green before the next
begins; the ripple registries are enumerated in `reports/mobile-productization/dependency-map.json`.
