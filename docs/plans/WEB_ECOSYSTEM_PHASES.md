---
title: Web Ecosystem — Phased Implementation Program
slug: plans/web-ecosystem-phases
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Web Ecosystem — Phased Implementation Program

This is the implementation program for the Olympus Labs + Aether + Kyber web
ecosystem: the shell-first architecture, domain model, auth threshold, and
design-system contract defined in
[docs/source-of-truth/WEB_ECOSYSTEM_SHELLS.md](../source-of-truth/WEB_ECOSYSTEM_SHELLS.md).
This document records the gap between the repository and that architecture,
orders the work into phases, and is the ledger for what has shipped.

Completion of the whole program is gated by the repository's canonical gate
(`make ci-check`), not by this document.

## 1. Gap analysis

The repository already had a mature shared foundation and three product
applications. The gaps against the target architecture were the two public
marketing shells, the public authentication threshold, and nomenclature drift
in docs.

| Area | Repository state before this program | Gap to the target architecture |
| --- | --- | --- |
| Shared foundation | `packages/brand` (`@olympus/brand`) tokens/identity/motion/responsive; `frontend/shared` (`@aether/ui`) React layer + shared CSS/Tailwind preset | None — mature and reused |
| Olympus corporate site | None | **Missing** — build `frontend/olympus-marketing` |
| Aether public marketing | None (aether login/signup live only inside the tenant app) | **Missing** — build `frontend/aether-marketing`, move auth threshold into the public experience |
| Aether tenant app | `frontend/aether` | Present; must receive Olympus-branding-secondary rule and later SSG/auth migration |
| Kyber | `frontend/kyber` (internal operator app) | Present; docs mis-described it as "Aether's operator product" — restated to Olympus Labs' private internal operator application |
| Auth boundary | Forms lived only in the tenant app; no public threshold layout | **Missing** — `AuthLayout` + `/login` `/signup` `/forgot-password` threshold routes in the Aether public shell |
| Docs/nomenclature | Brand-system docs framed Kyber as an Aether product | Restated Kyber ownership and the multi-shell hierarchy |
| Registration | Workspaces/typecheck/test/test-registry enumerated literal apps | Add the two marketing workspaces to every registration surface |
| Domains | No public origins deployed | `olympuslabs.com`, `aether.olympuslabs.com`, `app.olympuslabs.com`, `kyber.olympuslabs.com`, `docs.olympuslabs.com`, `status.olympuslabs.com` (deployment phases) |

## 2. Phase map

Phases are ordered so each phase leaves the ecosystem deployable and the
foundation decisions are locked before surface count grows.

| Phase | Deliverable | Workspaces | Entry/exit criteria |
| --- | --- | --- | --- |
| **1 (done)** | Shell + domain foundation: Olympus Marketing and Aether Marketing scaffolds, AuthLayout threshold, shared `Button asChild`, registration, source-of-truth + program docs, Kyber nomenclature restate | `olympus-marketing`, `aether-marketing`, `frontend/shared` | Both new workspaces typecheck, test, and build; registry coverage validator green; docs regenerate |
| **2 (done)** | Editorial depth + SSG/SEO foundation for both marketing shells | `olympus-marketing`, `aether-marketing` | Full editorial content per section copy; per-route meta; prerender/SSG layer; lighthouse budgets |
| **3 (done)** | Capability-deep pages and signature interactions (platform families, solutions, integrations directory, developers selector) | `aether-marketing` | Each capability page states problem/inputs/understanding/output/governance/limitations; truthful availability states |
| **4 (done)** | In-public authentication entry: real AuthLayout forms, genuine public→private handoff with prefill, origin-scoped session rules | `aether-marketing`, `frontend/aether` | Public threshold collects email/name and hands off to the application origin with `?email` / `?name` prefill; tenant login/signup accept the prefill; the public origin stores no tenant credential, cookie, or session; no parent-domain cookie |
| **5 (done)** | Deployment configuration + honest state: origin-ready `vercel.json` security/headers, `.env.example` env contract, opt-in analytics module (inert by default), deploy-contract doc recording exactly what is and is not live | `olympus-marketing`, `aether-marketing` | Code-complete and validated; no live origin, TLS, analytics property, or status page claimed until an infra phase deploys them |
| **6 (done)** | Motion + design-system polish: shared motion tokens across CSS shells, marketing-shell motion budgets (micro/standard utilities), reduced-motion parity, branding-validator enforcement, motion-is-meaning audit | all shells + `packages/brand` | Shell-level motion budgets enforced by validator + hermetic tests; no decorative ambient motion in apps/auth |
| **7 (done)** | Program acceptance: accessibility audit, content truth audit, release posture | `olympus-marketing`, `aether-marketing` | Audit must-fix claims fixed; should-fix applied or dispositioned; union `make ci-check` green; docs synced. `make release-gate` stays red **by design** — no public surface is deployed, and release readiness is an infra phase, not a claim this program makes (see Phase 7 acceptance below) |

### Implementation priority

Phase 1 locks the architecture decisions (shells, domains, tokens, auth
boundary) and must land first — it is the current changeset. Phases 2 and 3
build the customer-visible marketing depth next, ahead of Phase 4 in-public
authentication entry, because public depth and truthful content are
prerequisites to hosting the sign-in entry on the public surface. Phase 5 deployment follows auth only
where the surfaces they carry are ready; `frontend/aether`, `frontend/kyber`,
and `frontend/docs` deploy independently when their phase content is ready.

## 3. Phase 1 — shipped in this changeset

Phase 1 is complete and verified.

### 3.1 New workspaces

**`frontend/olympus-marketing`** (`@olympus/olympus-marketing`, port 5178) —
Olympus Labs corporate shell:

- Persistent header (skip link, `OlympusLockup` home link, Primary nav,
  Contact + Explore Aether actions, mobile disclosure), footer with company /
  products / legal columns and the "Aether by Olympus Labs" attribution line.
- Editorial home page and section pages for `/company`, `/products`,
  `/products/aether`, `/research`, `/principles`, `/security`, `/careers`,
  `/contact`, `/legal/*` — each rendered from `src/content/sections.ts` with
  honest `phase` build-state copy.
- Build-state chip on every section so no page implies more completeness than
  exists.

**`frontend/aether-marketing`** (`@aether/aether-marketing`, port 5179) — Aether
public shell + the authentication threshold:

- Persistent shell whose behavior reads like a read-only intelligence
  application; header composes the Aether mark and a quiet Olympus Labs
  attribution as sibling elements (no nested anchors), Primary nav, Docs /
  Sign in / Start building actions.
- Home page carrying the thesis and the five-step loop
  Connect → Resolve → Understand → Act → Measure, capability families,
  governance band, and the Olympus Labs ownership band.
- Section pages for `/platform`, `/solutions`, `/developers`,
  `/integrations`, `/security`, `/pricing`, `/resources`, `/company`.
- `AuthLayout` — the quiet threshold layout — and the `/login`, `/signup`,
  `/forgot-password` threshold routes. Each is an honest Phase 1 page that
  states where real sign-in lives and hands off to `app.olympuslabs.com`.

### 3.2 Shared and registration changes

- `frontend/shared/src/components/button.tsx`: additive `asChild` support so
  shared `Button` can style a route `Link` or an external anchor without
  duplicating the design system in each shell.
- Root `package.json`: both workspaces added to `workspaces`, the `typecheck`
  chain, and `test:frontend`.
- `scripts/bump_version.py`: both `package.json` paths added to `PACKAGE_JSONS`
  (platform version 8.12.0).
- `config/test_suites.yaml`: `frontend-olympus-marketing` and
  `frontend-aether-marketing` suites added.
- Brand tokens: **no token additions.** The existing brand token layer
  (color/surface/elevation/border/focus/typography/motion) already covers
  marketing and auth surfaces; marketing layout primitives (`.mkt-*`) stay
  app-local per shell, and extraction into a shared grammar is tracked in the
  architecture doc rather than done early.

### 3.3 Verification

- `tsc --noEmit` clean for both new workspaces; full monorepo `npm run
  typecheck` exits 0.
- Vitest green: olympus-marketing shell test, aether-marketing shell + auth
  threshold tests, and the shared `@aether/ui` suite (115 tests) with the
  `Button asChild` change.
- Production `vite build` clean for both marketing workspaces.
- `scripts/validate_test_suite_coverage.py` green with both suites registered.

## 4. Phase 7 — program acceptance (shipped 2026-09-03)

Phase 7 ran two read-only audits over the customer-visible web surfaces — a
content-truth audit and an accessibility (WCAG 2.1 AA) audit — then applied the
findings the program owns and recorded the honest release posture.

### 4.1 Audits run

- **Content-truth audit** (both marketing shells + auth threshold): checked every
  claim of a live surface, capability, integration, metric, customer, and legal
  posture against what the repository can substantiate.
- **Accessibility audit**: automated (axe) plus manual review of landmarks,
  headings, focus order/management, link affordances, form errors, color
  contrast, and reduced-motion behavior on the marketing shells and auth pages.
- The content corpus was otherwise **disciplined**: connectors are all
  registry-backed with real availability states, no fabricated metrics or case
  studies, no Kyber leakage into public copy, no legal overclaims. Findings
  below are the exceptions, not the norm.

### 4.2 Must-fix findings — fixed

- **M1 — status page claimed as live.** Olympus `/contact` and `/legal`
  asserted a real-time status page and linked
  `status.olympuslabs.com` (a **planned** origin with no workspace, per the
  [deploy contract](../deployment/WEB_ECOSYSTEM_DEPLOYMENT.md)). Copy now states
  the page is in planning and is not published; the fabricated link cards were
  removed and the tests that asserted them were corrected.
- **M2 — sign-up funnel jumped straight to the application.** The home hero and
  every CTA band's "Start building" pointed at `app.olympuslabs.com/signup`,
  bypassing the public `/signup` threshold that owns the marketing→application
  entry (WEB_ECOSYSTEM_SHELLS §5.1). All of those CTAs now route through the
  marketing `/signup` threshold, and the CTA/hero/signup copy and signup meta
  carry an explicit "not yet generally available" availability qualifier.

### 4.3 Should-fix findings — applied

- **Content truth:** Olympus `/contact` support copy conditionalized (S1); Aether
  `/company` ownership clause restated as "the platform Olympus Labs builds for
  customers and partners" (S2); Aether `/pricing` and `/resources` plan-table /
  interactive-tool / resource-catalog claims reframed as availability-framed —
  detailed tables and the estimator ship with general availability (S3).
- **Accessibility:** inline validation errors now announce via `role="alert"`
  (A2); color-only text links gained an underline + offset affordance across the
  brand-byline attribution, inline links, auth link lists, and footer/utility
  text links (C1); `<main>` landmarks are focus targets (`tabIndex={-1}`,
  outline suppressed) and route changes move focus to the new page's main for
  both marketing shells and the auth layout, skipping the initial load (A1/A3/A4).
- **Contrast (K1):** the shared light muted text token (~3:1) fails AA at the
  small sizes the marketing shells use it at. The tenant apps keep the shared
  value; each marketing shell overrides `--color-text-muted` locally (to
  `#655f57`, ≥4.5:1 on every light marketing surface). Retained as a
  recommendation: the shared token could carry a small-text-safe value when the
  design system next revises the muted role.

### 4.4 Informational audit notes — disposition

Remaining notes (read-first platform framing on `/platform`, present-tense
"how it works" product copy, muted-vs-secondary hierarchy) are recorded as
launch-copy work: every marketing page needs a copy pass at general
availability anyway (status-page reactivation, live hand-off re-enablement),
and the current honest posture is deliberate.

### 4.5 Release posture

`make release-gate` remains **red by design**: no public origin is deployed,
there is no live TLS, analytics property, or status page, and no production
scorecard area is claimed. This program's gate is `make ci-check` (green on the
Phase 7 union); deployment and go-live belong to an infra phase, not to this
marketing program.

## 5. Ledger

| Date | Phase | Result |
| --- | --- | --- |
| 2026-09-02 | 1 | Shell + domain foundation shipped; docs restated; gate run clean |
| 2026-09-02 | 2 | Editorial depth, per-route head, prerender/SSG layer shipped for both marketing shells; gate run clean |
| 2026-09-02 | 3 | Capability-deep pages + signature interactions shipped on the Aether marketing shell; gate run clean |
| 2026-09-03 | 4 | In-public authentication entry shipped: real AuthLayout forms + genuine public→private handoff with prefill; origin-scoped session rules; docs updated; gate run clean |
| 2026-09-03 | 5 | Deployment config + honest state shipped (code-complete, not deployed): origin-ready vercel.json security/headers, .env.example env contract, opt-in analytics surface (inert by default), deploy-contract doc with an explicit status gap; GA4 script-endpoint exemption added to the branding validator; validated on the combined P5+P6 union gate |
| 2026-09-03 | 6 | Motion + design-system polish shipped: shared motion tokens surfaced into both marketing CSS shells, ~40 color-transition sites tokenized to micro/standard budget utilities, branding-validator decorative-motion detector + marketing scan roots, hermetic motion-budget tests in both shells; validated on the combined P5+P6 union gate |
| 2026-09-03 | 7 | Program acceptance shipped: content-truth + accessibility audits; must-fix claims corrected (no live status page claimed, sign-up funnel routed through the public /signup threshold with availability framing); should-fix content + a11y + contrast fixes applied; release posture documented (release-gate stays red by design until an infra phase deploys); validated on the P7 union gate |

When a phase lands, this row is updated here and in the architecture doc's
phase map. Source-linked docs are synced only after review
(`python scripts/docs_drift.py --update`).
