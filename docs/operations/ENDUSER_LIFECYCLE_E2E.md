---
title: End-User Lifecycle E2E Runbook
slug: operations/enduser-lifecycle-e2e
section: operations
visibility: I
audience: [ops, dev-senior, ai]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---
# End-User Lifecycle E2E Runbook

Runbook for the Playwright acceptance suites that exercise the integrated
End-User Lifecycle tenant app end to end. The suites live at
`frontend/aether/src/test/e2e/lifecycle-{A,B,C,D,E}-*.spec.ts` (plus the shared
`lifecycle.harness.ts`) and are the executable acceptance spec for the lifecycle
IA — see `docs/plans/ENDUSER_LIFECYCLE_PHASES.md` §7 and
`docs/source-of-truth/AETHER_END_USER_LIFECYCLE.md` §9.

They are **integration-environment suites**: each is a serial journey over one
seeded scenario tenant through real connect → sync → readiness → surface flows.
They are gated so that, without the integration environment's seeded tenants,
they skip with a self-explanatory reason instead of timing out.

---

## 1. When this runs

- R4 lifecycle acceptance (after WS-1..WS-6 have merged through the R3
  integration queue and the backend is seeded).
- Full CI is **not** expected to run these against real providers; ordinary
  developer runs must expect the suites to skip (they require the env-var gate).

---

## 2. Prerequisites

1. WS-1..WS-6 merged and the tenant app + backend running locally
   (`frontend/aether` dev server on `http://localhost:5175`; backend seeded).
2. `connectors_enabled` test flag ON for the connect flows (activation and
   Settings → Integrations connect must be enabled in the test env).
3. Seeded scenario tenants with reset starting state (see §4).
4. Env vars from §3 exported to the Playwright process.
5. Playwright browsers installed for `frontend/aether`
   (`npx playwright install --with-deps` once per machine, from
   `frontend/aether`).

---

## 3. Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `E2E_TENANT_EMAIL` | Shared fallback | Tenant login email when no suite-specific pair is set |
| `E2E_TENANT_PASSWORD` | Shared fallback | Tenant login password when no suite-specific pair is set |
| `E2E_TENANT_EMAIL_A` … `_E` | Optional | Suite-specific tenant email (overrides the shared pair for that suite) |
| `E2E_TENANT_PASSWORD_A` … `_E` | Optional | Suite-specific tenant password |
| `E2E_CAMPAIGN_UUID` | Suite E only | Canonical Aether campaign UUID the Suite-E seed review resolves to |

Each suite uses its own tenant so the suites can run in any order and in
parallel. If a suite-specific pair is absent the suite falls back to the shared
pair. Suite E additionally skips without `E2E_CAMPAIGN_UUID`.

**Gate semantics (by design):** a suite skips (not fails) when its tenant pair is
unset. A skipped suite is the honest developer default; CI that intends real
runs must export the vars.

---

## 4. Tenant seed preconditions (reset before each run)

| Suite | Tenant starting state the seed must provide |
|---|---|
| A | **Incomplete** (first-time) tenant: no activation intent yet, no connected commerce/advertising — so A1 lands on `/activation`. Commerce (Shopify) + advertising (Meta Ads) available to connect. |
| B | **Activated, commerce-connected** tenant (Campaign 360 has data), Google Ads **not yet connected** (contextual add path available). |
| C | **Activated** tenant; Communications group present (comms cohort derived from catalog); Klaviyo not yet connected. |
| D | **Activated** tenant whose Google Ads connection's credential the seed has **REVOKED** (so the row renders Needs attention with impact). |
| E | **Activated** tenant whose seed includes at least one **open/ambiguous mapping review** plus the canonical `E2E_CAMPAIGN_UUID` the review resolves to. |

Runs are not idempotent across the serial journey: a suite that already
connected/activated/resolved will fail honest assertions on re-run. **Reset the
tenant seed between runs.**

---

## 5. Running

From `frontend/aether` (the config `testDir` is `./src/test/e2e`, base URL
`http://localhost:5175`, `VITE_AETHER_ENV=test`):

```bash
# All five lifecycle suites (explicit list — the bare `lifecycle` positional also
# over-matches the unrelated onboarding.spec.ts in this repo, so it is not used)
npx playwright test lifecycle-A-ecommerce-first-tenant lifecycle-B-returning-expansion \
  lifecycle-C-communications lifecycle-D-credential-recovery lifecycle-E-mapping-exception

# One suite
npx playwright test lifecycle-A-ecommerce-first-tenant

# One suite with UI trace on failure
npx playwright test lifecycle-D-credential-recovery --trace on
```

Equivalently `npm run e2e -- lifecycle-A-ecommerce-first-tenant`.

**Expectation:** with the R3/R4 environment + seeds, all five suites pass.
Without the env vars, all suites skip with
`requires E2E_TENANT_EMAIL/E2E_TENANT_PASSWORD (R3/R4 integration env: WS-1..WS-6
merged, seeded backend)` — that is a correct, honest result for a non-integration
run.

---

## 6. What each suite proves

| Suite | Data-truth / acceptance point |
|---|---|
| A | Incomplete tenant → `/activation` → commerce intent → Shopify Connected (never Ready) → Meta Ads → initial sync (Syncing) → Complete → enters workspace → Campaigns resolved; Settings → Integrations shows both Connected — no fabricated Ready |
| B | Campaign 360 contextual "Add advertising" → Settings/Integrations advertising section → connect Google Ads → account discovery/selection → sync → returns to Campaign 360 |
| C | Communications group lists the derived cohort (Klaviyo + sendgrid/customerio/mailchimp) → connect Klaviyo → sync → comms facts reachable from Campaign 360 |
| D | Revoked credential renders Needs attention with impact disclosed + Reconnect CTA (never Ready) → reconnect restores Connected then Ready only from evidence |
| E | Campaign-quality readiness discloses open mapping reviews → Mapping Review → resolve via `#campaign-id-input` → review leaves the open queue and lists under resolved |

---

## 7. Troubleshooting

**All suites skip.**
Env gate not met: export `E2E_TENANT_EMAIL` / `E2E_TENANT_PASSWORD` (or the
`_A.._E` pairs). Check with `echo ${E2E_TENANT_EMAIL:?unset}`.

**`npx playwright test lifecycle` also runs `onboarding.spec.ts`.**
The bare `lifecycle` positional over-matches the unrelated onboarding suite in
this repo (8 tests, not env-gated, need a Playwright browser install). Use the
explicit five-file list from §5, or add `--grep-invert` for onboarding.

**Suite E skips alone.**
`E2E_CAMPAIGN_UUID` unset — export the canonical campaign the seed review
resolves to.

**Suite A fails at A1 (tenant does not land on `/activation`).**
The tenant seed was not reset to *incomplete*. Reset the seed (an already-
activated tenant routes to the workspace root).

**Connect/sync steps time out.**
`connectors_enabled` is OFF in the test env, so connect surfaces stay dormant.
Enable the flag for the run env, then re-reset tenant seeds.

**"Connected" never advances / Ready never appears.**
Readiness is evidence-derived by design; a suite that asserts Ready requires the
sync/health path to have produced evidence. Confirm the backend worker executed
the sync (not just the optimistic UI).

**Flaky account picker (Suite B).**
Account discovery is async after credential grant; the suite polls the picker
(20s). If it still fails, confirm the seeded Google Ads test account set is
non-empty and discoverable.

---

## 8. Related docs

- `docs/source-of-truth/AETHER_END_USER_LIFECYCLE.md` — canonical vocabulary,
  routes, state projection, markers the suites assert.
- `docs/plans/ENDUSER_LIFECYCLE_PHASES.md` — program plan (§7 acceptance).
- `frontend/aether/src/test/e2e/lifecycle.harness.ts` — gates, routes, copy,
  markers.
