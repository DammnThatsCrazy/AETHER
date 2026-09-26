# Handoff: unified Olympus Labs + Aether site (one Vite app)

## Overview
Merge the five frontend apps (`frontend/olympus-marketing`, `frontend/aether-marketing`, `frontend/docs`, `frontend/status`, `frontend/aether`) into **one Vite + React app at `frontend/site`**, deployed as **one Amplify app** on branch `main` and served on two domains:

| Domain | Serves |
|---|---|
| `olympuslabsml.com` | Olympus Labs company pages |
| `aether.olympuslabsml.com` | Aether marketing, docs, status, contact, legal, and the logged-in portal at `/app` |

Old per-surface domains 301 to their new paths (see `amplify-redirects.json`). The old apps are **deleted after cutover** (see Cutover).

Decisions locked with the product owner:
- Vite everywhere. No Astro.
- Marketing + docs routes are **prerendered** to static HTML at build (SEO). `/app` stays a client SPA.
- Auth: **Amplify Auth (Cognito)** with Google, Apple, Slack, Microsoft federated IdPs + email/password.
- Payment: **Stripe Elements inside `/app/signup`** — never redirect off-page.
- Status: live from the existing health endpoint + a **new 90-day history endpoint**.
- Docs: all 45 pages ship in the first cut. Content stays in components (from `docs-content.js`), not MDX.
- Analytics: keep `frontend/aether-marketing/src/lib/analytics.ts` as-is.
- Environments: `main` only.

## About the design files
Everything in `designs/` is a **design reference built in HTML** (`*.dc.html` files open directly in a browser; `support.js` is only the preview runtime). They show intended look, copy and behavior. **Do not ship them.** Recreate them in `frontend/site` using the repo's React + Tailwind patterns and `packages/shared`.

## Fidelity
**High-fidelity.** Colors, type, spacing, copy and interactions are final. Recreate pixel-accurately. Where a DC hard-codes a hex value, map it to the token table below.

## Product rules (from CLAUDE.md — enforce in copy and UI)
- Aether **observes** agents. It never approves, blocks or dispatches agent actions. Agent activity uses observe verbs: *seen, recorded, mark reviewed, flag, open in graph*. Never *approve / decline / allow / execute* for agent actions.
- Human review is limited to changes to the graph itself: imports, identity merges, deletions.
- Sentence case everywhere; no emoji; identifiers in Geist Mono.

---

## Route map

### olympuslabsml.com (host-matched; same build)
| Route | Design file | Prerender |
|---|---|---|
| `/` | Olympus Home.dc.html | yes |
| `/company` | Olympus Company.dc.html | yes |
| `/principles` | Olympus Principles.dc.html | yes |
| `/research` | Olympus Research.dc.html | yes |
| `/stories` | Olympus Stories.dc.html | yes |
| `/contact` | Contact.dc.html (Olympus variant header) | yes |
| `/legal/*` | Legal.dc.html | yes |

### aether.olympuslabsml.com
| Route | Design file | Prerender |
|---|---|---|
| `/` | Aether Home.dc.html (embeds Profile 360, Relationship Explorer) | yes |
| `/how-it-works` | Aether How It Works.dc.html | yes |
| `/connections` | Aether Connections.dc.html | yes |
| `/pricing` | Aether Pricing.dc.html | yes |
| `/security` | Aether Security.dc.html | yes |
| `/procurement` | Aether Procurement.dc.html | yes |
| `/contact` | Contact.dc.html | yes |
| `/docs` → `/docs/overview` | Docs.dc.html + docs-content.js | yes |
| `/docs/:page` (45 pages, below) | Docs.dc.html | yes |
| `/status` | Status.dc.html | shell only; data client-side |
| `/legal/*` | Legal.dc.html | yes |
| `/app/signin`, `/app/signup`, `/app/*` | Aether Portal.dc.html | **no** (SPA) |
| 404 | Not Found.dc.html | yes (`404.html`) |

**Host routing:** one router; a `useSite()` hook reads `window.location.hostname` (and build-time host during prerender) and selects the Olympus or Aether route table + shell (`Site Header.dc.html` / `Site Footer.dc.html` have both variants). Cross-host links are absolute URLs.

### Docs pages (all 45; ids = URL slugs)
- **About Aether:** overview, why-aether, product-structure, how-it-works, features, governance
- **For your role:** role-executives, role-growth, role-data, role-developers, role-security, role-analysts
- **Concepts:** signals, profiles, relationships, sources, connectors, journeys, lenses, imports, exports, communications, tenants, evidence-states
- **Get started:** start-here, quickstart-web, quickstart-ios, quickstart-android, quickstart-react-native, quickstart-backend
- **SDKs:** sdk-overview, sdk-web, sdk-ios, sdk-android, sdk-react-native, sdk-privacy
- **Reference:** ingestion-api, events, connector-catalog, imports-api, data-exchange-api, api-conventions
- **Help:** faq, troubleshooting, changelog

Port `docs-content.js` to `frontend/site/src/content/docs.ts` (typed; same `sections[] → pages[]` shape). Tabs = sections; left nav = pages; every page must render real content (no empty tabs).

### Redirects (in `amplify-redirects.json`)
- `docs.olympuslabsml.com/*` → `aether.olympuslabsml.com/docs/*` (301)
- `status.olympuslabsml.com/*` → `aether.olympuslabsml.com/status` (301)
- Old portal host → `/app/*` (301). **Confirm the old portal hostname** in Amplify before cutover; the file assumes `app.olympuslabsml.com`.
- `/signin`, `/signup` → `/app/signin`, `/app/signup`
- `/app/*` → `/app/index.html` (200 rewrite, SPA)
- everything else unmatched → `404.html`

---

## Build + deploy

### Amplify
Use `amplify.yml` in this folder as the **new root `/amplify.yml`** (single application, `appRoot: frontend/site`). Attach both custom domains to this one Amplify app. Headers (incl. CSP) are in the spec; Cognito and Stripe origins are allow-listed. Replace `${VITE_API_ORIGIN}` / `${VITE_STATUS_API_URL_ORIGIN}` with real origins at build (or move CSP to `customHttp.yml` generated in CI).

### Prerendering
- `vite build` for the SPA, then a prerender step (e.g. `vite-plugin-prerender` or `vite-react-ssg`) over the route list above for **both hosts**, output to `dist/olympus/**` and `dist/aether/**`, with an Amplify host-based rewrite choosing the folder. Simpler alternative: build twice with `VITE_SITE=olympus|aether` into two output dirs and map domains to them.
- Each prerendered page: unique `<title>`, meta description, canonical URL, **OG image per page** (1200×630, generated at build from the page H1 on the Stone background with the correct mark).
- Generate `sitemap.xml` (per host) and `robots.txt`. `robots.txt` disallows `/app/`.

### Env vars (`frontend/site/.env.example`)
| Var | Use |
|---|---|
| `VITE_API_URL` | Aether API base |
| `VITE_STATUS_API_URL` | existing health endpoint (see Status) |
| `VITE_STATUS_HISTORY_URL` | new 90-day history endpoint |
| `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_CLIENT_ID`, `VITE_COGNITO_DOMAIN`, `VITE_COGNITO_REGION` | Amplify Auth |
| `VITE_STRIPE_PUBLISHABLE_KEY` | Stripe Elements |
| `VITE_SITE_OLYMPUS_URL`, `VITE_SITE_AETHER_URL` | absolute cross-host links |
Carry over the existing `VITE_STATUS_DOCS_URL` / `VITE_STATUS_AETHER_MARKETING_URL` from `frontend/status/src/config.ts`, now defaulting to `/docs` and `/`.

---

## Screens — key behavior

Exact layout, copy, hex values and states are in each DC; the notes below cover what isn't obvious from the file.

### Olympus pages
Stone surface. Olympus Arch mark. Home uses tabbed bento sections (Company / Principles / Research / Contact) with clickable relationship explainers (H→H, H→A, A→A, A→H). Buttons graphite, not blue.

### Aether Home
Hero + Profile 360 (interactive profile card: sources with brand logos, relationships to people / syndicates / agents, two campaign-tied journeys with CAC and conversion rate, agent actions shown as **observed**) + Relationship Explorer. Port `Profile 360` and `Relationship Explorer` as standalone components; they're reused in `/app`.

### Pricing
Plans from `services/backend/shared/plans/catalog.py` (Alpha free, Beta, Gamma self-serve; Epsilon, Omicron, Omega enterprise → contact). Self-serve / Enterprise tab switch. Same plan data feeds `/app/signup` — share one `plans.ts` module.

### Docs
Tabbed sections, left page nav, content pane, per-section accent glyph + color. Search across page titles. Connector catalog page shows every provider with its brand logo (`assets/brand/*.svg`).

### Status
- **Current state:** `GET ${VITE_STATUS_API_URL}` → `{ status, components: { [name]: { status } } }` (already parsed by `componentsFromPayload` in `frontend/status/src/main.tsx` — reuse that logic).
- **History (new, backend work):** `GET ${VITE_STATUS_HISTORY_URL}?days=90` →
  `{ components: [{ name, days: [{ date: "YYYY-MM-DD", status: "operational"|"degraded"|"outage"|"no_data", uptime_pct: number|null }] }], incidents: [{ id, title, status, started_at, resolved_at|null, components: [] }] }`
- Render 90 bars per component: green operational, amber degraded, red outage, **stone `no_data` (distinct from zero)**. Components are collapsible accordions. Missing URL → "Status unavailable" empty state, never fake green.

### Contact
Single focused column form. Submit to the existing demo-request handler (`frontend/olympus-marketing/src/components/demo-request-form.tsx`).

### `/app` — sign in, sign up, setup (Aether Portal.dc.html)
Flow: **sign up + plan + payment on one card → 7-step setup → Home**. Returning users land where they left off.
- **Sign up:** account fields, then plan picker below. Alpha → account created → setup. Paid → Stripe **Payment Element** appears in the same card; button shows spinner while processing; errors inline with retry or "switch to Alpha"; "Powered by Stripe" mark; receipt-emailed note. Create a Stripe subscription server-side (`services/backend/shared/billing/stripe_client.py`), confirm client-side, never navigate away.
- **SSO:** Google, Apple, Slack, Microsoft buttons with brand marks → Cognito hosted-UI federated sign-in (`signInWithRedirect({ provider })`), return to `/app`.
- **Setup steps (all required, Import and Invite skippable):** Goal (incl. "Something else" free text) → Connect (searchable logo grid of all connectors; any number; no per-connector fees; each opens an in-page consent dialog "Allow Aether to access {provider} data" with per-scope checkboxes, read-only) → Import (CSV / JSON / JSONL ≤ 32 MB; auto column mapping in a small modal; full import tools only after setup) → SDKs (pick one or more of Web, iOS, Android, React Native, Server; **one key per SDK**; keys hidden until "Reveal", scramble-reveal ~700 ms; per-SDK "Send test" row: listening → received / error with "Troubleshoot ↗" to `/docs/troubleshooting`; Continue unlocks after one success) → Invite (live email validation: green / red ring; role chips) → First profile (assembles source by source; dark slate card) → Done.
- **Shell after setup:** sidebar shows only Setup + Settings until first event/profile; then Home, Explore, Profiles, Data, Settings. Setup wizard disappears once complete.
- **Plan limits:** never block, only warn. Soft red inline nudge with "See Beta" that opens the same in-page card form. Settings → Plan uses the same form.

---

## Design tokens
Load `_ds/…/colors_and_type.css` values into `tailwind.config.ts` `theme.extend`:

| Token | Hex |
|---|---|
| stone-50 (page) | `#f5f4f1` |
| stone-100 (card) | `#eceae5` |
| stone-200 (hover) | `#e2e0da` |
| line | `#d8d6d0` |
| raised (white card) | `#ffffff` / `#fbfaf8` |
| ink | `#1a1a1e` |
| graphite-body | `#4a4945` |
| slate | `#6b6a65` |
| ash | `#9c9b95` |
| graphite base / raised / hover / hairline | `#111114` / `#1a1a1e` / `#1f1f24` / `#2a2a2f` |
| bone (text on dark) | `#e8e6e1` |
| cobalt / cobalt-ink | `#3a6896` / `#2d5373` |
| steel | `#5a85a8` |
| ochre / ochre-ink | `#c9975a` / `#8a6433` |
| sage / sage-ink | `#6b9a7c` / `#4f8466` |
| ember (error, nudge) | `#b5564a` / `#9c4439` |

Primary buttons are **graphite `#1a1a1e`**, never blue. Accents carry color on glyphs, chips, meters, status and CTAs.

- **Type:** Geist (UI) + Geist Mono (ids, code, keys, status logs). Display 64/500/−1.92px · H-XL 40/500/−0.8 · H-LG 28/500/−0.56 · H 22/500/−0.33 · Body 14 · Body-sm 13 · Caption 12 · Label 11/500/+0.04em uppercase.
- **Spacing:** 4 px grid; section gaps 48–64 px.
- **Radius:** controls 6–10, cards 12–16, dialogs 18, pills 999 (softened from the base 4 px per product direction).
- **Shadows:** floating only (dialogs `0 24px 64px #1a1a1e2e`; lifted tile hover `0 6px 18px #1a1a1e12`).
- **Motion:** `cubic-bezier(0.22,1,0.36,1)`; 120 / 200 / 320 ms; no bounce; respect `prefers-reduced-motion`. No loading skeletons on marketing pages.

## Assets
`designs/assets/` — Olympus Arch and Aether Layers marks + lockups; `assets/brand/*.svg` provider logos (Stripe, Google, Apple, Slack, Microsoft, HubSpot, Shopify, Salesforce, Klaviyo, Zendesk, Segment, Google Ads, Google Analytics, Meta, Instagram, X, Intercom, PostHog, Jira, Linear, Phantom, …). Put them in `frontend/site/public/`. Third-party marks: use each provider's official brand guidelines at build.

## Acceptance checklist
- [ ] All routes in the route map render on the right host; all 45 docs pages have content
- [ ] Prerendered HTML for marketing + docs; `/app` SPA rewrite works on deep links
- [ ] Old domains 301 correctly; `404.html` served for unknown paths
- [ ] `sitemap.xml` per host; `robots.txt` blocks `/app/`
- [ ] Unique title / description / canonical / OG image per page
- [ ] CSP passes with Stripe Elements + Cognito; no console CSP violations
- [ ] Sign up Alpha → setup; paid → in-page payment → setup; payment failure retry path
- [ ] SSO for Google, Apple, Slack, Microsoft
- [ ] Status shows live state + 90-day bars; `no_data` visually distinct; no fake green when endpoint is missing
- [ ] Agent activity copy uses observe verbs only
- [ ] WCAG 2.2 AA: contrast, focus rings, keyboard nav (tabs, dialogs, accordions), dialog focus trap, form labels and error announcements

## Cutover
1. Build `frontend/site` behind the Amplify default domain; run the checklist.
2. Attach `olympuslabsml.com` + `aether.olympuslabsml.com` to the new Amplify app; add old hosts as redirect-only domains.
3. Verify 301s and Cognito callback URLs (add `https://aether.olympuslabsml.com/app` to allowed callbacks and sign-out URLs).
4. After 7 days clean: delete `frontend/olympus-marketing`, `frontend/aether-marketing`, `frontend/docs`, `frontend/status`, `frontend/aether` and their per-app `amplify.yml` / `customHttp.yml` / `amplify-redirects.json`; remove their Amplify apps.

## Files
- `amplify.yml` — single-app build spec (replaces root `/amplify.yml`)
- `amplify-redirects.json` — redirects and rewrites
- `designs/*.dc.html` — design references (open in a browser)
- `designs/docs-content.js` — all docs content
- `designs/assets/` — marks and provider logos
