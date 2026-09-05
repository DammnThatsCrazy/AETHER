---
title: Web Ecosystem — Shell Architecture and Domain Model
slug: architecture/web-ecosystem-shells
section: architecture
visibility: I
audience: [architect, dev-senior, exec, ops]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
estimated_read_minutes: 12
toc_depth: 3
---

# Web Ecosystem — Shell Architecture and Domain Model

This document is the source of truth for the public web architecture across the
Olympus Labs product family. It fixes the product nomenclature, the domain
architecture, the shell taxonomy, the design-system and motion contract, and
the authentication boundary between the public product and the protected
tenant environment. It is the reference the other web docs restate; if a page
contradicts it, this document wins and that page is wrong.

Companion material:

- [Brand system](../brand-system/README.md) — identity, tokens, semantics.
- [Web ecosystem phases](../plans/WEB_ECOSYSTEM_PHASES.md) — gap analysis and the
  phased implementation program.
- `docs/source-of-truth/KYBER_*.md` — Kyber (internal operator application)
  security, sessions, and workforce identity contracts.

## 1. One product family, many independent shells

Olympus Labs, Aether, and Kyber form **one product family**: a single brand, a
single design system, and a single motion philosophy — delivered as **several
independently deployed application shells**. They are never collapsed into one
application. Each shell owns its brand chrome, navigation, layout, global
context, search, overlays, motion budget, accessibility behavior, and session
concerns. Application features are composed *inside* a shell and inherit that
shell's chrome and motion contract.

### 1.1 Canonical nomenclature

Only the following names are valid for the product family. No deprecated or
coined product names may be reintroduced.

| Name | Role | Boundaries |
| --- | --- | --- |
| **Olympus Labs** | The company — parent, owner, and operator of Aether. | Corporate identity and attribution layer. |
| **Aether** | The customer-facing relationship intelligence platform: public marketing, authentication routes, and the protected tenant application. | Customer-facing. |
| **Kyber** | Olympus Labs' **private internal operator application** — the console Olympus runs to operate Aether. | **Never customer-facing. Never linked from public marketing. Never presented as an Aether product.** |

Kyber is an Olympus Labs application for the Olympus workforce. Everyone who
signs into it is an Olympus principal, never an Aether tenant (see
`docs/source-of-truth/KYBER_SESSIONS_AND_SCOPES.md`). Web properties and
marketing that a customer can reach must present only Olympus Labs and Aether.

### 1.2 One registered domain family

All public properties live under a single registered Olympus Labs domain
family. Deployment to these origins is a later phase (see
[docs/plans/WEB_ECOSYSTEM_PHASES.md](../plans/WEB_ECOSYSTEM_PHASES.md)); the
table below is the domain model, with the current repository workspace and
build status for each surface.

| Origin | Surface | Audience | Workspace | Status |
| --- | --- | --- | --- | --- |
| `olympuslabs.com` | Olympus Labs corporate marketing (company, products, research, principles, security, careers, legal) | Public | `frontend/olympus-marketing` | Phases 1–2 + 6 content; **code-complete, not deployed** ([deploy contract](../deployment/WEB_ECOSYSTEM_DEPLOYMENT.md)) |
| `aether.olympuslabs.com` | Aether public marketing **including the auth routes** (`/login`, `/signup`, `/forgot-password`) | Public | `frontend/aether-marketing` | Phases 1–4 + 6 content; **code-complete, not deployed** ([deploy contract](../deployment/WEB_ECOSYSTEM_DEPLOYMENT.md)) |
| `app.olympuslabs.com` | Protected Aether tenant application | Authenticated Aether tenants | `frontend/aether` | Existing |
| `kyber.olympuslabs.com` | Kyber — Olympus Labs' internal operator application | Olympus workforce only | `frontend/kyber` | Existing |
| `docs.olympuslabs.com` | Documentation | Public | `frontend/docs` | Existing |
| `status.olympuslabs.com` | Status | Public | — | Planned |

The authentication routes belong to the **Aether public** surface
(`aether.olympuslabs.com`), not to the tenant origin. The public experience
owns the threshold; the tenant application owns the protected session.

## 2. Shell-first architecture

A **shell** is a deployed application skeleton that persists across routes and
owns everything that must not restart between navigations: brand chrome,
primary navigation, layout regions, global search/command context, overlays and
toasts, the shared motion budget, accessibility landmarks, and session state.
Routes and features mount inside a shell.

### 2.1 Shell taxonomy

| Shell | Public? | Primary purpose | Emotional model | Repository |
| --- | --- | --- | --- | --- |
| **Olympus Marketing** | Yes | Corporate site; the parent's face and the place Aether is introduced | Assured, editorial, calm | `frontend/olympus-marketing` |
| **Aether Marketing** | Yes | Product marketing for Aether; behaves like a read-only intelligence application | Precise, confident, application-like | `frontend/aether-marketing` |
| **Aether Tenant App** | No (authenticated) | The protected Aether product | Focused, fluent, trustworthy | `frontend/aether` |
| **Kyber** | No (internal) | Olympus Labs' private operator application | Authoritative, dense, calm under pressure | `frontend/kyber` |
| **AuthLayout** | Yes | The threshold inside the Aether public experience | Quiet, single-task, low noise | `frontend/aether-marketing` |
| **Docs Shell** | Yes | Documentation | Neutral, searchable, precise | `frontend/docs` |

AuthLayout is a first-class *layout* rather than a shell: it renders inside the
Aether public experience but drops the marketing navigation and decoration so
the threshold between public product and tenant environment is intentionally
quiet.

### 2.2 What a shell owns

- **Brand chrome and identity lockups** from `@olympus/brand` manifests,
  rendered through `@aether/ui` (no copied or redrawn SVG).
- **Navigation and route layout** — including mobile navigation, skip links,
  and landmark structure.
- **Global context** that must persist across routes (search, command,
  workspace/tenant context in the tenant shells).
- **Overlays, toasts, and motion budget** — a shell does not restart its
  persistent visual substrate on route change.
- **Accessibility behavior** (focus management, reduced-motion handoff, aria
  landmarks) and **session chrome** (sign-in/sign-out affordances).

Feature code does not own shell chrome. Two marketing applications may share
layout *grammar* (container widths, type rhythm, surface recipes) without
sharing identical layout; shared primitives live in `@aether/ui`, shell layout
stays local to the shell.

## 3. Brand hierarchy per shell

Attribution always states the true ownership relationship, but its visual
weight differs by audience.

| Surface | Rule |
| --- | --- |
| Corporate (`olympuslabs.com`) | Olympus Labs identity leads; Aether is presented as its product. |
| Aether public (`aether.olympuslabs.com`) | **"Aether by Olympus Labs."** Aether mark leads; a quiet Olympus Labs attribution sits beside it. |
| Aether tenant app (`app.olympuslabs.com`) | Aether identity leads; Olympus Labs branding is **secondary** inside the product environment. |
| Kyber (`kyber.olympuslabs.com`) | **"Olympus Labs · Kyber"** — Olympus Labs ownership is explicit because Kyber is an Olympus application, not an Aether product. |

The lockups and responsive reduction rules are defined in
[brand-system](../brand-system/README.md) and implemented in
`packages/brand/src/identity/`. When a header composes a product mark and its
owner attribution, the two are separate sibling elements — never nested
anchors.

## 4. Design system and motion contract

### 4.1 Design tokens

One token set serves every shell. Canonical sources:

| Concern | Source |
| --- | --- |
| Color, surface, elevation, borders, focus, radius, spacing | `packages/brand/src/tokens/` and `frontend/shared/src/styles/tokens.css` (CSS variables) |
| Typography | Geist (product sans), Geist Mono (IDs, structured data, code, operational labels) |
| Motion | `packages/brand/src/motion/` |
| Responsive behavior | `packages/brand/src/responsive/` |
| Surface recipes | `packages/brand/src/surfaces/` |

Marketing and auth surfaces render on the **light** token theme (`html
class="light"`); the Aether tenant application defaults to `dark`. Both consume
the same CSS variable layer. Marketing applications reuse the shared Tailwind
preset (`@aether/ui/tailwind.preset`) and the control primitives in
`@aether/ui`. Marketing layout primitives (`.mkt-*`) are app-local per shell in
Phase 1; extraction into the shared grammar is tracked, not assumed.

### 4.2 Motion is meaning

Motion is not decoration; it is a communication channel. Every animation
answers one of four questions:

- **Orient** — where am I, and what changed?
- **Explain** — why did that happen?
- **Confirm** — did my action land?
- **Continuity** — how is the new state related to the old?

The duration/easing vocabulary and recipes live in
`packages/brand/src/motion/`. Reduced motion is a first-class concern, not an
afterthought: marketing sites, auth, and the tenant product respect the
user's reduced-motion preference and never substitute decorative ambient
motion for state truth. Per-shell motion budgets are enforced by the shell,
not invented per-feature.

## 5. Authentication boundary

### 5.1 The public-to-private threshold

The threshold between public product and protected tenant environment lives in
the **Aether public** experience (`frontend/aether-marketing`), rendered by
**AuthLayout**:

- `aether.olympuslabs.com/login`
- `aether.olympuslabs.com/signup`
- `aether.olympuslabs.com/forgot-password`

AuthLayout is deliberately the quietest surface in the system: no decorative
or ambient motion, minimal chrome, focused on the single task of getting the
right principal into the right environment.

**Phase 4 state:** the auth routes are real, accessible *entry* forms, and
their job is the public→private handoff — never in-place authentication. The
public marketing origin does not hold sessions; tenant sessions, cookies, and
credentials stay scoped to the origin that owns them (§5.2). Each form
collects and validates a workspace email (and, at signup, a name), then moves
the browser to the matching Aether application route carrying the input as
prefill only:

- `aether.olympuslabs.com/login` →
  `app.olympuslabs.com/login?email=…`
- `aether.olympuslabs.com/signup` →
  `app.olympuslabs.com/signup?name=…&email=…`
- `aether.olympuslabs.com/forgot-password` →
  `app.olympuslabs.com/login?email=…`

The tenant application accepts that prefill — its login and signup pages read
`?email` / `?name` once to fill the first step — and owns everything after:
sign-in, workspace provisioning, invites, billing, and password recovery all
complete on the application origin. The public threshold never sends a
password-reset email and never claims to have signed anyone in; recovery is
entered from the application sign-in, where a reset stays scoped to the
environment that holds the credentials. `src/lib/handoff.ts` in
`frontend/aether-marketing` is the single module authorized to build
application-origin handoff URLs, and no public page writes a tenant
credential, cookie, or session anywhere. Shell and footer navigation point
Sign in and Start building at these public entry routes rather than jumping
straight to the application.

### 5.2 Boundaries that never change

- **No broad parent-domain cookies.** A cookie set on `.olympuslabs.com` would
  be readable across every product surface. Session and tenant cookies stay
  scoped to the origin that owns them (`app.olympuslabs.com` for the tenant
  app, `kyber.olympuslabs.com` for Kyber).
- **Server-enforced authorization.** The client may hint at state; it never
  grants authority. Tenant scoping and capability decisions are decided and
  enforced by the backend (see the Kyber and tenant-access source-of-truth
  docs).
- **Logout is per-environment.** Signing out of the tenant application does not
  sign out an Olympus operator's Kyber session, and vice versa. Each surface
  clears only its own origin-scoped session.
- **Kyber is never reachable from public marketing.** No public page links to
  `kyber.olympuslabs.com`, and no customer-facing flow routes an Aether tenant
  into an Olympus operator console.

## 6. Content and truth principles

Public web content follows the same truth standard as the product:

- **SEO/SSG-ready.** Marketing routes carry a descriptive `<title>` and meta
  description per page; a prerender/SSG layer is a later-phase target.
- **Truthful status language.** Build-state chips, capability availability, and
  integration status use the real states (`credential_required`,
  `sandbox_validated`, `partner_live`, `degraded`, and so on). A page never
  implies a capability is fuller than it is.
- **No fabricated evidence.** No invented case studies, quotes, logos, or
  metrics. Illustrative scenarios are labeled as product scenarios.
- **No empty buzzwords.** Claims like "AI-powered" carry no meaning unless a
  page says what the system does, what it understands, and what it cannot do.
- **Kyber stays internal.** Customer-facing material presents Olympus Labs and
  Aether only.

## 7. Repository map and registration

| Path | Role | Registered in |
| --- | --- | --- |
| `packages/brand` | Framework-free tokens, identity manifests, motion, responsive, iconography (`@olympus/brand`) | npm workspaces |
| `frontend/shared` | React/ui layer and shared styles (`@aether/ui`) | npm workspaces |
| `frontend/olympus-marketing` | Olympus Labs corporate shell (`@olympus/olympus-marketing`) | npm workspaces, `bump_version.py`, `config/test_suites.yaml` |
| `frontend/aether-marketing` | Aether public shell + AuthLayout (`@aether/aether-marketing`) | npm workspaces, `bump_version.py`, `config/test_suites.yaml` |
| `frontend/aether` | Protected Aether tenant app | npm workspaces |
| `frontend/kyber` | Kyber internal operator app | npm workspaces |
| `frontend/docs` | Docs shell | npm workspaces |

The two marketing workspaces are npm workspace members, participate in the
root `typecheck`/`test`/`build` gates, carry the platform version via
`bump_version.py`, and are declared as test suites in
`config/test_suites.yaml`. Their tests run under Vitest with the same jsdom
setup and `@aether/shared` aliasing as the other frontend workspaces.

## 8. Phase map

The current implementation phase of each shell, the gap analysis, and the
Phases 1–7 program are tracked in
[docs/plans/WEB_ECOSYSTEM_PHASES.md](../plans/WEB_ECOSYSTEM_PHASES.md). This
document changes when the architecture changes — not when a phase lands.
