---
title: End-User Lifecycle & Integration Management — Implementation Program
slug: plans/enduser-lifecycle-phases
section: architecture
visibility: I
audience: [architect, dev-senior, ai]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 15
toc_depth: 3
---

# End-User Lifecycle & Integration Management — Implementation Program

This is the implementation program for the **Aether Canonical End-User
Lifecycle & Integration Management Blueprint**: converting Aether's public
discovery and authentication front door plus its fragmented protected
implementation surfaces into one continuous customer lifecycle —

```text
Discover → Start → Connect → Resolve → Understand → Act → Measure → Expand → Connect
```

The governing spec was authored outside the repository and was **not present
in-repo when this program started**; this document records the gap between the
repository and that spec, is the current-state ledger, and orders the work into
phases. The spec itself will be captured as a source-of-truth doc
(`docs/source-of-truth/AETHER_END_USER_LIFECYCLE.md`) in the tail phase (§35).

**Program central finding: this is not greenfield.** The protected tenant app
already routes incomplete tenants into a live, server-backed activation machine
(`/activation`); `/integrations` renders a solid per-tenant connector manager;
mapping review is already exception-driven; and a derived `comms.*` cohort
(ADR-C11) already proves the "derive lists from one manifest" pattern the spec
wants generalized. The work is convergence and orchestration over existing
runtimes, not a rewrite — and it must preserve the repo's truthful-availability
posture (all providers are `credential_waiting`; connector + activation features
are flag-gated OFF by default).

---

## 1. Lane facts

| Field | Value |
|---|---|
| Branch | `feat/enduser-lifecycle-integration` |
| Base | `origin/main` @ `9620539f` (PR #607 — marketing shells + auth threshold + deployment) |
| Worktree | `/Users/osazehunt/aether-enduser-lifecycle` |
| Absorbs | `feat/unified-integration-control-plane` program (ADR-0001..0007, W0–W2 landed), refiled under this branch |
| Delivery model | Contract-first parallel workstreams — one orchestrator, isolated-worktree specialists, serialized integration queue |
| Gate | `make ci-check` after each integration point (canonical completion gate) |
| Flags | `connectors_enabled` (default OFF) and activation flags stay OFF through integration; surfaces must be honest at every step |

## 2. Grounded current state (Round 0 audit, 2026-09-05)

Verified deltas between spec assumptions and the repository as it actually is.
Paths relative to repo root.

1. **Activation exists but is SDK-plan-centric.** `/activation` is live
   (server-backed `/v1/activation/*` state machine: plan → SDKs → keys → test
   event → first value → complete); `TenantLanding` redirects incomplete tenants
   there. There is **no** `/activate`, **no** ActivationIntent/goals step, no
   connect-business/advertising/communications steps. `/onboarding` is a separate
   Onboarding Center (checklist, comms connect step, readiness scores).
2. **Campaign Sources connect is broken; the runtime is thinner than assumed.**
   `/campaign-intelligence/sources/connect` is unrouted (404) and the page header
   "Connect source" was a self-link (both removed in Round 0 triage). CampaignSource
   is a row in `measurement_connectors`; `connect_campaign_source` is a thin,
   non-idempotent write with no credential handling, no platform allow-list, no
   account discovery/selection, no sync trigger. The 7 ad connectors
   (`services/measurement/connectors/{google,meta,tiktok,linkedin,x,reddit,microsoft}_ads.py`)
   are implemented but never executed by any worker.
3. **No single catalog — 10+ provider id-spaces.** 21 registered connectors
   (`services/integrations/connectors/{registry,adapters}.py`), 7 measurement ad
   connectors, 51 shared/provider categories, 40 Olympus corpus
   (`services/provider_catalog`), payment rails, brand registry, social unions —
   plus ~7 hand-synced ad-platform lists. `shared/integration_contracts/catalog.py`
   derives a 29-entry manifest surface (pure projection). `experience_category`
   does not exist anywhere.
4. **Provider/capability identity contract already exists** (`ProviderIdentity` =
   `family.product.capability` in `shared/integration_contracts/identity.py`), but
   `shared/providers/registry.py` is name-only. Comms membership is already derived
   from `manifest_data_outputs` `comms.*` (ADR-C11).
5. **Spec §18.2 endpoints do not exist.** `/v1/integration-catalog`,
   `/v1/tenant-integrations`, `/v1/integration-readiness` are absent repo-wide.
   Real surfaces to compose: `/v1/integrations/connectors*`, `/v1/campaign-sources*`,
   `/v1/mapping-review`, `/v1/campaign-quality`, `/v1/measurement/*`,
   `/v1/activation/*`, `/v1/onboarding/*`, `/v1/tenant/readiness*`,
   `/v1/provider-connections` (flag-gated). A joined readiness engine does not
   exist; ingredient engines do (CredentialReadiness ladder, readiness-graph,
   sdk_health sub-scores, measurement freshness/mapping rates).
6. **Settings is one long page.** `/settings` holds API keys + SDK fleet +
   notification channels/prefs + webhooks as stacked sections; `/settings/notifications`
   re-renders the whole page. Account/security/billing/team/users are separate routes.
   No nested settings shell.
7. **Marketing source is only on `origin/main`.** `frontend/aether-marketing` +
   `frontend/olympus-marketing` (PR #607) are absent from older branches. Public
   integrations directory = hand-maintained static snapshot of the 21-connector
   registry ("DERIVED SNAPSHOT — NOT A LIVE QUERY"), all `credential_waiting`,
   pinned by an allowlist test. No provider/intent prefill exists (only name/email).
8. **Docs.** Spec §35 target docs are all missing. Two source-of-truth taxonomy
   docs (`CONNECTOR_TAXONOMY.md`, `CONNECTOR_LAKE_POLICY.md`) contradict code but
   pass CI (docs/source-of-truth is skip-listed in docs_drift). `CAPABILITY_MANIFEST.md`
   is a name collision (documents the SDK `/v1/config` manifest).
9. **Honest-but-dormant is the default posture.** All provider readiness is
   `credential_waiting`; feature flags OFF. The program is a lifecycle/IA/
   orchestration build — it must never advertise live capability it cannot
   demonstrate (§31 data truth).

## 3. Program structure

### 3.1 Rounds

| Round | Scope | Parallelism |
|---|---|---|
| R0 | Lane + baseline + absorb + triage (this commit) | solo |
| R1 | Contract spine (WS-0): Phase 0 + PR A | flagship solo, sub-agents |
| R2 | Fan-out WS-1..WS-6 (Phases 2–8 / PR B–G) | **all concurrent** (isolated worktrees) |
| R3 | Integration waves (ordered merges WS-1→…→WS-6) | serialized integration queue |
| R4 | Lifecycle acceptance (E2E A–E, a11y/data-truth, release) | solo |

### 3.2 Workstreams (Round 2 fan-out)

| WS | Blueprint phase / PR | Scope | Depends |
|---|---|---|---|
| WS-0 | Phase 0 + PR A | Taxonomy ADR + canonical identity/alias map + `experience_category` + inventory lock + one-catalog contract + tenant projection endpoints + parity/drift tests + FE hooks/types | R0 |
| WS-1 | Phase 2 / PR B | Settings nested shell; `/settings/integrations` (+ experience-category sections); health/status projection; legacy redirects; rehome API/SDK/webhooks/notifications | WS-0 |
| WS-2 | Phase 3 / PR C | Advertising connect workflow: credential grant → account discovery/select → CampaignSource auto-link (idempotent) → sync state; reconnect/disable; multi-account model; id/field drift | WS-0 |
| WS-3 | Phase 4 / PR D | Intent-driven activation (ActivationIntent, recommended categories), connect business/advertising/communications steps reusing WS-1/WS-2 components, tracking step reuse, sync + readiness views, durable completion + save/resume, `/activate`→`/activation` | WS-0, WS-1, WS-2 |
| WS-4 | Phase 5+6 / PR E | Joined readiness projection over existing engines; coverage; contextual CTAs with `?return=`; empty-state + error/degraded UX; quality context badges | WS-0, WS-1, WS-2 |
| WS-5 | Phase 7 / PR F | Public directory refresh generator or live derive; category-vocabulary convergence; whitelisted provider-intent handoff; cross-workspace drift tests | WS-0 |
| WS-6 | Phase 8 / PR G tail | Deprecations; spec source-of-truth capture (§35 docs); FRONTEND-ARCHITECTURE/WEB_ECOSYSTEM updates; E2E lifecycle suites A–E; a11y/data-truth acceptance; fix stale taxonomy docs | all (scaffold early, finalize last) |

Communications generalization (Phase 5) and multi-account (§20) fold into
WS-1/WS-2/WS-3; the comms cohort is already derived, so remaining work is
presentation + connect-flow reuse.

### 3.3 Ownership and merge discipline

- **One writer per file.** The lease map in
  `docs/integration-control-plane/FILE_OWNERSHIP.yaml` is extended per workstream;
  WS-0-owned contract files freeze after R1 (change only via ADR).
- Router/settings/nav/`endpoints.ts` are shared destinations → owned by the
  integration queue, never written by two workstreams in the same wave.
- Every workstream ends scoped-gate-green (vitest/typecheck/its validators)
  before requesting integration; the orchestrator runs full `make ci-check`
  after each merge.
- New test modules are namespaced to avoid the root-tests basename-collision
  class fixed in `7b69a028`.
- `connectors_enabled` stays OFF through R3; surfaces remain honest
  (loading/empty/unavailable/credential-required/syncing/ready/degraded) throughout.

## 4. Canonical contracts (R1 spine deliverables)

1. **Identity.** Canonical key = `family.product.capability`. Alias map resolves
   boundary collisions (`x_ads`↔`twitter_ads`, `ga4`↔`google_analytics`, shopify
   decommissionable-vs-brand, snapchat/pinterest alias-only) without renaming
   runtime id spaces.
2. **One customer catalog = derived projection** over authoritative runtimes
   (the `catalog.py` pattern generalized + tenant state). Never a second storage
   model. Shared TS generated from backend (`integration-consent.json` twin
   pattern) so tenant FE and marketing consume identical ids.
3. **`experience_category`** — additive enum: `advertising_campaigns`,
   `commerce_revenue`, `crm_customer`, `communications_lifecycle`,
   `analytics_behavior`, `social_community`, `customer_support`, `work_operations`.
4. **State model.** `ConnectionState` (30 members + legal transitions) is the
   machine; customer states (§7.1 of the spec) and "Connected ≠ Ready" are a
   projection onto ConnectionState + CredentialReadiness.
5. **Endpoints (new, additive):** `GET /v1/integration-catalog`,
   `GET /v1/tenant-integrations[/{id}]`, and the connect/accounts/sync/reconnect/
   disable mutations, plus `GET /v1/integration-readiness` as a projection over
   existing engines.
6. **Route plan (compatibility):** `/integrations` → `/settings/integrations`
   (redirect during compatibility); `/campaign-intelligence/sources/connect`
   removed (already triaged); `/activate` → `/activation`; fix
   `/settings/notifications`; marketing `/integrations` unchanged (separate origin).

## 5. Telemetry (canonical event names, R1 code)

`public.integration_viewed`, `public.signup_started`, `public.signup_handoff`,
`app.signup_completed`, `activation.started`, `activation.intent_selected`,
`activation.integration_opened/connected/failed`, `activation.account_selected`,
`activation.sdk_verified`, `activation.initial_sync_started/completed`,
`activation.readiness_reached`, `activation.completed`,
`integration.add_started/completed`, `integration.reconnected`,
`integration.disabled`, `integration.removed`, `integration.sync_manual`,
`integration.error_viewed`, `integration.recovery_started/completed`.
No secrets in telemetry. Track funnel: marketing→signup→auth→activation→first
data→graph-ready→first insight.

## 6. UX copy invariants (§33/§34)

Public, activation and Settings must share one vocabulary: **Integrations,
Connect, Manage, Advertising, Commerce & Revenue, Customer & CRM,
Communications, Analytics & Behavior, Connected, Needs attention, Ready,
Syncing.** Engineering tokens (CampaignSource, ConnectorConfig, secret_ref,
provider manifest, sync-source) stay internal unless an advanced surface
requires them.

## 7. Acceptance (E2E lifecycle suites)

- **A — e-commerce + ads first-time tenant:** signup → activate → connect
  Shopify → connect Meta Ads → verify SDK → initial sync → readiness → enter
  Aether → Campaigns resolved; Profiles receive commerce/profile evidence.
- **B — returning expansion:** Campaign 360 → contextual add advertising →
  Settings/Integrations → connect Google Ads → select account → sync → return.
- **C — communications:** Settings/Integrations → Communications → connect
  Klaviyo → sync → Campaign 360 + Profile 360 comms facts present.
- **D — credential recovery:** revoked → degraded → impact disclosed →
  reconnect → health restored.
- **E — mapping exception:** ambiguous ad campaign → readiness review →
  Mapping Review → resolve → Campaign 360 canonical identity updates.

## 8. Risks

1. No single id vocabulary → alias map + drift tests; canonical-forward only.
2. Ad sync runtime is dormant → orchestration + honest states; live ad sync is a
   follow-on, never fabricated freshness.
3. Flags default OFF → test harnesses enable flags explicitly.
4. Marketing source only on origin/main → R0 base is origin/main (done).
5. Parallel collisions on shared FE files → lease map + ordered merges.
6. Docs gates/skip-list → WS-6 owns; stale taxonomy docs fixed by real review,
   never blind-stamped (CLAUDE.md).
7. Prior control-plane program state → absorbed (this branch); ADR-0001..0007
   retained as ancestors; count fields refreshed against the certification matrix.

## 9. R2 WS-6 tail ledger (Phase 8 / PR G + spec capture + acceptance, 2026-09-05)

Tail-of-round-2 status for WS-6 (owner `ws6`, lease `docs/integration-control-plane/FILE_OWNERSHIP.yaml` →
`r2_ws6_tail`). WS-1..WS-5 remain in-flight in their own isolated worktrees; their
tails are queued for the R3 serialized integration wave. R1 (contract spine) was
recorded GREEN 72/0 at the R1 head this lane is cut from (`a32f63a0`).

**Completed in this tail:**

1. **Connector-taxonomy TS mirror generated (R1/WS-0 handoff honored).**
   `scripts/generate_connector_taxonomy.py` derives
   `packages/shared/connector-taxonomy.ts` from
   `Backend Architecture/aether-backend/shared/integration_contracts/catalog.py`
   (`ALL_MANIFESTS` four-group union) + `experience.py` — pure mirror, never
   hand-edited; the six-layer descriptor enums from `base.py` are preserved
   verbatim by the generator. Regenerate with
   `python scripts/generate_connector_taxonomy.py` (supports `--check`).
2. **Parity/honesty contract tests** (namespaced, `tests/contracts/`):
   `test_integration_catalog_twin_parity.py`,
   `test_integration_catalog_readiness_honesty.py`,
   `test_integration_catalog_experience_grouping.py`.
3. **Lifecycle E2E suites A–E** (`frontend/aether/src/test/e2e/`,
   `lifecycle-A-…` … `lifecycle-E-…` + shared `lifecycle.harness.ts`), gated on
   `E2E_TENANT_EMAIL[_A.._E]`/`E2E_TENANT_PASSWORD[_A.._E]` so they skip honestly
   without the R3/R4 integration env.
4. **Spec capture (§35).** `docs/source-of-truth/AETHER_END_USER_LIFECYCLE.md`
   authored (the previously in-repo-absent governing spec — resolves the §1 gap).
   Stale `CONNECTOR_TAXONOMY.md` + `CONNECTOR_LAKE_POLICY.md` fixed by real review
   against `base.py`/`catalog.py` (fictional `IDENTITY_BRIDGE`/`AGENT_TOOL`,
   `ALLOWED`/`BLOCKED` policies removed). `docs/source-of-truth/README.md` index
   extended.
5. **Operations runbook** `docs/operations/ENDUSER_LIFECYCLE_E2E.md` (env vars,
   seed preconditions, run commands, skip semantics, troubleshooting).
6. **`docs/FRONTEND-ARCHITECTURE.md`** reviewed against the `frontend/aether/src`
   e2e additions and re-stamped (no body change — additive test surfaces only).

**router.tsx decision (leased, additive-only):** no WS-6 change. The tenant
router is an orchestrator/shared destination; legacy-route deprecations
(`/integrations` → `/settings/integrations`, `/activate` → `/activation`) belong
to the R3 integration merges that land WS-1/WS-3's settings/activation surfaces.
WS-6's suites target routes the R2 surfaces own and exercise them only under the
R3/R4 integration env.
