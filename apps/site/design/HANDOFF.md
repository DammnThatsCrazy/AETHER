# Handoff: Olympus Labs & Aether marketing, docs and portal surfaces

## Overview
Two connected sites plus an account portal, built around one story.

- **Olympus Labs** (company): typographic, minimal, no product detail. Says what the company believes and points to Aether.
- **Aether** (product): marketing site, docs, status, and a sign-up / onboarding portal. Story is **Connect → Understand → Explore → Act**.
- **Vocabulary**: one plain-language vocabulary across marketing, product and docs. Technical terms ("canonical contracts" etc.) only appear in docs Reference and the Glossary's technical column.

## About the design files
The `.dc.html` files in this bundle are **design references created in HTML**. They are prototypes that show the intended look and behavior. They are **not production code to copy**. Recreate them in the target codebase's existing environment (React, Next, Astro, Vue, etc.) using its routing, component and data patterns. If no environment exists, pick a static-friendly framework (Next.js or Astro + React islands is a good fit: mostly static pages, a few interactive widgets, one stateful portal).

How to read a `.dc.html` file: markup is in `<x-dc>`, logic is the `class Component` in the trailing `<script type="text/x-dc">`, props are declared in that tag's `data-props`. `{{ x }}` holes are values from `renderVals()`; `<sc-for>`/`<sc-if>` are loops and conditionals; `<dc-import name="X">` mounts `X.dc.html`. Styles are inline. Treat all of this as a spec, not an architecture to keep. Open any file in a browser (with `support.js` beside it) to see it live.

## Fidelity
**High-fidelity.** Final colors, type, spacing, copy and interactions. Recreate pixel-accurately, mapping values to the codebase's tokens. Copy is final and should be used verbatim.

## Design system (binding)
Olympus / Aether Design System v2.0. Tokens live in `_ds/.../colors_and_type.css` (CSS variables) and fonts in `_ds/.../fonts/`. The pages mostly use literal hex values that match these tokens. In the implementation, use the variables.

Rules the pages follow. Keep them:
- **Sentence case** everywhere. No title case, no exclamation marks, no emoji.
- **Blue is interaction, gold is intelligence, everything else is stone.** The four layer colors (Cobalt #3a6896, Steel #5a85a8, Ochre #c9975a, Sage #6b9a7c) are for the Aether mark, plus data-viz accents in the scene and symbol key. They are not a UI accent palette.
- **Hairline borders, not shadows.** Shadows only on floating surfaces (menus, modals). Buttons have no shadow.
- **No gradients, no backdrop blur in chrome.** Chrome is opaque.
- **Motion ≤ 320ms**, ease `cubic-bezier(0.22, 1, 0.36, 1)`. 120ms for color/focus, 200ms for fade/translate. No bounce, no parallax. `prefers-reduced-motion` collapses all to 0.01ms and stops the scene autoplay.
- Primary button once per visible area.
- Identifiers in Geist Mono, never wrapped (`prf_7k2m`, `0x1a2b…3c4d`).
- Status words lowercase: healthy, degraded, unhealthy, unknown.
- Unicode glyphs are the icon set (◈ ◉ ⬢ ⬡ ⌘ ⚙ ✓ → ↔ ↑ ● ▲ ■ ○ ✉ ⇪ ≡). Do not replace them with SVG icon packs.
- Dark "Graphite" sections (`data-theme="dark"`, bg #111114, text #e8e6e1, never pure white) sit between Stone sections on marketing pages for contrast. Docs are Graphite throughout.

### Known deviations to fix during implementation (not intended design)
1. Primary CTAs on pages are Graphite (#1a1a1e on #f5f4f1). The brand's primary is **Signal Blue #2563eb** (hover = accent-hover). Use the DS `Button` primary.
2. Some headings in dark sections use hard-coded colors. Use `--fg` tokens.
3. Components are hand-built inline. In the real codebase mount the DS components (`Button`, etc.) rather than re-implementing.
4. Verify no `backdrop-filter` is introduced in header/menus.

## Design tokens

### Color: Stone (light, default)
| Token | Hex | Use |
|---|---|---|
| page | #f5f4f1 | page background, header |
| raised / card | #eceae5 | cards, secondary buttons |
| hover | #e2e0da | hover on raised |
| menu surface | #fbfaf8 | dropdown panel |
| line | #d8d6d0 | borders |
| line-subtle | #e8e6e1 | nested rules |
| ink | #1a1a1e | primary text |
| body-muted | #4a4945 | lead paragraphs |
| slate | #6b6a65 | secondary text |
| ash | #9c9b95 | tertiary, radio border |

### Color: Graphite (dark sections, docs, Kyber)
| Token | Hex |
|---|---|
| base | #111114 |
| raised | #1a1a1e |
| hover | #1f1f24 |
| line | #2a2a2f |
| bone (text) | #e8e6e1 |
| muted text | #a09f99 |
| faint text | #7d7c77 |

### Accents
Signal Blue #2563eb (interaction, focus ring). Link default #3a6896, hover #2d5373. Stat accents on Aether home: #2d5373, #4f7a5e, #8a6433, #7d6538. Menu glyph colors: #3a6896, #4f8466, #5a85a8, #8a6433, #a8783e, #a3473c, #7d6538. Portal plan colors: Alpha #6b9a7c, Beta #3a6896, Omega #c07f6f.

### Type: Geist (sans) and Geist Mono
| Role | Size | Weight | Tracking |
|---|---|---|---|
| Hero h1 (Aether home) | clamp(48px, 7vw, 88px) | 500 | −0.045em, line-height 0.96 |
| Hero h1 (inner pages) | clamp(44px, 6.4vw, 84px) | 500 | −0.045em, 0.96 |
| h2 (section) | clamp(32px, 4.4vw, 56px) | 500 | −0.032em, 1.02 |
| Lead | 17–18px | 400 | line-height 1.55–1.6, max-width ~500px |
| Body | 14–15px | 400 | |
| Nav / button | 13–14px | 500 | |
| Label | 11px | 500 | +0.04em, uppercase |
| Stat numeral | 32px | 500 | −0.04em |
Use `text-wrap: balance` on headings and `pretty` on paragraphs.

### Spacing / layout
4px base. Page max-width 1200px with 24px side padding. Prose max 720px. Header 56px high, sticky, 1px bottom border. Section vertical padding clamp(48px, 7vw, 96px) (marketing) and clamp(64px, 9vw, 112px) (dark). Gaps: 8px (button/chip groups), 24px (hero stacks). Hero grids use `repeat(auto-fit, minmax(min(100%, 440px), 1fr))` so they stack under ~900px.

### Radius
4 (controls, inputs), 6 (buttons, panels, menu items), 8 (menus, modals, docs cards), 12 (featured/hero cards, scene frame), 999 (pills, avatars).

### Buttons
Min-height 44px (hero) / 36px (header). Padding 0 20px (hero) / 0 14px (header). 1px border, radius 6.
- Primary: bg #1a1a1e → hover #2e2e34 (pages today; switch to Signal Blue, see deviations).
- Secondary: bg #eceae5, border #d8d6d0 → hover bg #e2e0da, border #c9c7c0.
- Tertiary: text link with → glyph in mono, hover color #3a6896.
- Focus: 1px Signal Blue ring. Press: no scale.

### Shadow
Menus only: `0 12px 32px rgba(26,26,30,0.10), 0 2px 6px rgba(26,26,30,0.05)`. Modal scrim rgba(17,17,20,0.6).

## Global chrome

### Site Header (`Site Header.dc.html`)
Props: `brand`: `aether` | `olympus`; `active`: top-level label to highlight.
- Left: logo + wordmark. Aether: layers mark 22px + "Aether" 17px/500, then "by Olympus Labs" (12px, #6b6a65, underlined link to Olympus Home). Olympus: arch mark 18px + "Olympus Labs" 16px/500.
- Center nav (≥1080px): items with optional dropdown. Hover opens (mouse enter/leave), click toggles, Esc and outside-click close. Panel: 300px (360px if >5 items), padding 6, bg #fbfaf8, border #d8d6d0, radius 8, menu shadow, fade/translate 4px in 200ms. Each menu item is a 2-column grid: glyph (mono 13px, colored) + label 13px/500, with a one-line question beneath in 12px #6b6a65.
- Right: Aether has "Sign in" (text), "Request a pilot" (secondary), "Get started" (primary). Olympus has "Contact" (secondary) and "Explore Aether" (primary).
- <1080px: 44×44 menu button (≡ / ✕). Panel lists each top item with → and its children as a wrapped row of links, and stacks the CTAs at 44px height.

Aether nav: Platform (Overview, How it works, Graph, Profiles, Journeys, Lenses, Agents, Value and risk) · Applications (Customer intelligence, Revenue intelligence, Agent intelligence, Communications, Risk and trust, Operations) · Connect (Connectors, SDKs, APIs and webhooks, Imports) · Developers (Documentation, Quickstarts, API reference, Glossary, Status) · Pricing.
Olympus nav: Technology (Overview, Records and relationships) · Applications · Aether · Research · Company (About, Principles, Proof, Contact).
Menu item questions are the copy under each label. See the `raw` array in the file.

### Site Footer (`Site Footer.dc.html`)
Shared by all marketing pages. Read the file for columns and links.

## Shared interactive components

### Aether Scene (`Aether Scene.dc.html`)
The signature animated diagram: **disconnected → connected**. 640×620 viewBox-style canvas (nodes positioned in a ~600×440 coordinate space).
Props: `story`: customer | agent | value; `stage` (0–3, fixed) ; `autoplay` (default true); `rotate` (cycle stories); `controls`; `dark`; `stages` (comma list, default "0,1,2,3"); `interval` (ms, default 2800).
- Four stages per story: 0 fragmented records, 1 recognized (one center profile), 2 related (journey order and timing), 3 lens applied. Each story has a subtitle per stage, a lens name, node list (id, kind, source system, identifier, label, [x,y], credit, time), connection list (dashed = inferred) and reveal sequence. All data is in `data()`. Reuse it verbatim as the data model.
- Node kinds: center, system, agent, human, org, value (each has a glyph and color).
- Autoplay pauses on hover/focus (`hold`) and when reduced motion is on. Controls let the user step through stages and pick the story.
- Used on Aether Home, How It Works, Customer Intelligence, Feature Page, Olympus Technology.

### Profile 360 (`Profile 360.dc.html`)
One customer's full profile. Prop `ios` (boolean) renders an iOS-style header and bottom tab bar. On Aether Home it sits inside an iPhone frame (`ios-frame.jsx` is a design-only bezel; rebuild or use the platform's device-frame component). Size 560×720 standalone.

### Relationship Explorer (`Relationship Explorer.dc.html`)
Interactive graph, 1100×620, with selectable nodes (state `t`, default `h2a`). Used inside docs and platform pages.

## Screens
Each is a full page. Header + footer are shared unless noted. Exact copy is in the files. Below is purpose, structure and key content. All pages carry OG/Twitter meta (image path under `assets/og/`, 1200×630).

### Aether Agents
- File: `pages/Aether Agents.dc.html`
- Title: Agents — Aether
- Purpose: Aether records who created whom, who instructed whom, who had authority, and what resulted.
- H1: "Observe every agent, and who orchestrated it."
- Sections (h2): "Seven questions you can always answer." · "How Aether knows what it knows." · "People and AI, working together." · "Record one agent action. See its full history."

### Aether Applications
- File: `pages/Aether Applications.dc.html`
- Title: Applications — Aether
- Purpose: One technology, many applications: customer, revenue, agent, communications, risk, and operations intelligence.
- H1: "What can you do with Aether?"
- Sections (h2): "Same Aether. Different questions."

### Aether Connect
- File: `pages/Aether Connect.dc.html`
- Title: Connect — Aether
- Purpose: How does Aether connect to my systems? Connectors, SDKs, APIs, webhooks, imports, and agent integrations.
- H1: "Connect the tools you already use."
- Sections (h2): "Where is your data?" · "Apps you already use" · "Your websites and apps" · "Your servers and other services" · "Past data" · "Connect as many tools as you like. No per-integration fees."

### Aether Customer Intelligence
- File: `pages/Aether Customer Intelligence.dc.html`
- Title: Customer intelligence — Aether
- Purpose: Aether recognizes the relationship between every customer event and provides one explainable history.
- H1: "See every customer’s full story."
- Sections (h2): "Watch eight records turn into one story." · "Follow a customer from first click to purchase." · "Connect your tools, and you can see:"

### Aether Detail Page
- File: `pages/Aether Detail Page.dc.html`
- Title: Details — Aether
- Purpose: Privacy, governance, deployment, connectors, SDKs, APIs, and imports, explained plainly.
- Sections (h2): "Good to know"
- Notes: Template driven by ?p=. Question as h1, steps, "Good to know". Content object keyed by connectors, sdks, apis, imports, privacy, governance, deployment.

### Aether Feature Page
- File: `pages/Aether Feature Page.dc.html`
- Title: Platform — Aether
- Purpose: Graph, Profiles, Journeys, Communications, Value, and Risk — one model, many ways to understand it.
- Sections (h2): "What you can do"
- Notes: Template driven by ?f=. Question as h1, Scene visualization, "What you can do".

### Aether Home
- File: `pages/Aether Home.dc.html`
- Title: Aether — See how everything connects
- Purpose: Aether connects people, agents, activity, relationships, and value into one continuously updated understanding.
- H1: "See how everything connects."
- Sections (h2): "Something happened. Aether works out what it means." · "Connect. Understand. Explore. Act." · "Ask a question. Get a clear answer." · "One product. Very different stories." · "Everything about one customer, in one view." · "Endless applications." · "Read as much or as little as you need." · "Connect your tools. See who’s who, what happened, and how it all fits together."
- Notes: Entry. Hero (h1 + lead + 3 CTAs + Scene in a 12px-radius frame), stat strip (4 stats), dark story section, connect/understand/explore/act steps, Profile 360 inside an iPhone frame, applications, docs teaser, closing CTA.

### Aether How It Works
- File: `pages/Aether How It Works.dc.html`
- Title: How Aether works
- Purpose: Connect, recognize, relate, understand, act — how Aether produces understanding from activity.
- H1: "How Aether works."
- Sections (h2): "Something happened. Aether works out:" · "The same steps, in technical detail." · "Connect one tool and watch your first customer come together."

### Aether Lenses
- File: `pages/Aether Lenses.dc.html`
- Title: Lenses — Aether
- Purpose: Same graph. Different perspective. Apply, combine, and save lenses over everything Aether knows.
- H1: "Same data. Different perspective."
- Sections (h2): "A perspective, not another dashboard." · "See a new perspective."

### Aether Platform
- File: `pages/Aether Platform.dc.html`
- Title: Platform — Aether
- Purpose: One model. Multiple ways to understand it. The Aether platform: connect, understand, explore, act.
- H1: "One picture. Many ways to look at it."
- Sections (h2): "Connect one tool. See the puzzle pieces come together."

### Aether Portal
- File: `pages/Aether Portal.dc.html`
- Title: Aether
- Purpose: Sign in or create an Aether account, connect your first tool, and see your first customer come together.
- Notes: No site chrome. Sign-in/up, plans, onboarding, workspace. See Portal section.

### Aether Pricing
- File: `pages/Aether Pricing.dc.html`
- Title: Pricing and packages — Aether
- Purpose: Choose how you want to start with Aether. Plans for individuals, teams, and enterprises, with no per-integration fees.
- H1: "Choose how you want to start."
- Sections (h2): "What you’re paying for"
- Notes: Plan cards (Alpha→Omega) with included limits and connector tiers; what you are paying for; CTAs per plan type (self-serve vs security review).

### Aether Procurement
- File: `pages/Aether Procurement.dc.html`
- Title: Procurement — Aether
- Purpose: How Aether is bought, billed, reviewed, and deployed — and what to request at each step.
- H1: "Everything your review will ask for."
- Sections (h2): "Five steps from first call to live." · "Pricing, billing, and pilots." · "Tell us what your process needs."

### Aether Scene
- File: `pages/Aether Scene.dc.html`
- Notes: Component, see above.

### Aether Security
- File: `pages/Aether Security.dc.html`
- Title: Security — Aether
- Purpose: Data separation, consent, access keys, human approval, and audit trails are part of how Aether stores data.
- H1: "Safety is built in, not bolted on."
- Sections (h2): "Six protections on every record." · "Three kinds of key. Each does only its job." · "Your data stays yours." · "Run it where you need it." · "What Olympus Labs won’t build." · "Ask for what your review needs."

### Aether Trust
- File: `pages/Aether Trust.dc.html`
- Title: Trust — Aether
- Purpose: Can I trust Aether with my environment? Tenant isolation, consent, agent authority, deployment, procurement, and status.
- H1: "Can you trust Aether with your data?"
- Sections (h2): "Three lines Aether never crosses." · "Everything your security team will ask." · "Run it where you need it."

### Contact
- File: `pages/Contact.dc.html`
- Title: Contact
- Purpose: Pick a topic and add a sentence or two. It reaches the right person.
- Sections (h2): "Request received"

### Docs
- File: `pages/Docs.dc.html`
- Title: Aether docs
- Purpose: Guides, task walkthroughs, SDKs, and reference for understanding, connecting, and building with Aether.
- H1: "This page is not public"
- Notes: No site chrome. See Docs section.

### Glossary
- File: `pages/Glossary.dc.html`
- Title: Glossary — Aether docs
- Purpose: Every Aether term in three forms: plain language, product meaning, and technical meaning.
- H1: "What the words mean."
- Sections (h2): "Engineering terms, translated."

### Legal
- File: `pages/Legal.dc.html`
- Title: Legal — Olympus Labs
- Purpose: Privacy and terms for Olympus Labs and Aether.

### Not Found
- File: `pages/Not Found.dc.html`
- Title: Page not found
- Purpose: This page doesn’t exist. Try one of these instead.
- H1: "This page doesn’t exist."

### Olympus Applications
- File: `pages/Olympus Applications.dc.html`
- Title: Applications — Olympus Labs
- Purpose: One technology, many kinds of work: commercial, human-agent, autonomous, trust, operational, and economic systems.
- H1: "One technology. Many kinds of work."
- Sections (h2): "Seeing your own use case?"

### Olympus Company
- File: `pages/Olympus Company.dc.html`
- Title: Company — Olympus Labs
- Purpose: Olympus Labs is a research and engineering company building technology that helps people and AI work together.
- H1: "Building for a world where people and AI work together."
- Sections (h2): "How Olympus works" · "Talk to the team."

### Olympus Home
- File: `pages/Olympus Home.dc.html`
- Title: Olympus Labs — Intelligence for connected systems
- Purpose: Olympus Labs develops technology that helps organizations understand how people, software, agents, systems, relationships, and value interact.
- H1: "Help your systems understand each other."
- Sections (h2): "Your tools keep records. They miss the relationships." · "Meet Aether." · "Built for teams where people and AI work side by side." · "Start with a question you can’t answer today."
- Notes: Typographic hero, minimal centered sections, "Meet Aether" hand-off. No product detail.

### Olympus Principles
- File: `pages/Olympus Principles.dc.html`
- Title: Principles — Olympus Labs
- Purpose: Five principles that decide what Olympus Labs builds, how it treats data, and where people stay in control.
- H1: "Five rules."
- Sections (h2): "Ask how any of these is enforced."

### Olympus Research
- File: `pages/Olympus Research.dc.html`
- Title: Research — Olympus Labs
- Purpose: The open problems Olympus Labs is working on, and what it takes for research to ship.
- H1: "Hard questions, worked on in the open."
- Sections (h2): "Before anything ships, it needs four things." · "Working on one of these?"

### Olympus Stories
- File: `pages/Olympus Stories.dc.html`
- Title: Proof — Olympus Labs
- Purpose: Has this actually worked? What every Olympus Labs proof shows, and how to become a proof partner.
- H1: "Has this actually worked?"
- Sections (h2): "Every story shows" · "Be the first proof partner."

### Olympus Technology
- File: `pages/Olympus Technology.dc.html`
- Title: Technology — Olympus Labs
- Purpose: Connected intelligence: entities, activity, relationships, time, authority, and value — continuously understood.
- H1: "Technology that sees the whole picture."
- Sections (h2): "What most tools see. What Olympus sees." · "Simple on the surface. Detailed when you need it." · "Aether puts it into practice."

### Profile 360
- File: `pages/Profile 360.dc.html`
- Notes: Component, see above.

### Relationship Explorer
- File: `pages/Relationship Explorer.dc.html`
- Notes: Component, see above.

### Site Footer
- File: `pages/Site Footer.dc.html`
- Notes: Component, see above.

### Site Header
- File: `pages/Site Header.dc.html`
- Notes: Component, see above.

### Status
- File: `pages/Status.dc.html`
- Title: Aether service status
- Purpose: Live status of Aether and the systems it depends on.
- Sections (h2): "■Delayed data intake for batch imports" · "Past incidents"

### Symbol Key
- File: `pages/Symbol Key.dc.html`
- Title: Symbol key — Aether
- Purpose: What every symbol and line style means across Aether, in the product and in these docs.
- H1: "One small alphabet."


## Interactions and behavior
- **Navigation**: plain links between pages. Query params carry context: `Aether Feature Page?f=graph|profiles|journeys|value`, `Aether Detail Page?p=connectors|sdks|apis|imports|…`, `Docs?page=<id>`, `Contact?brand=aether|olympus&type=pilot`, `Aether Portal?mode=signin|signup&plan=<id>`. Anchors: `Aether Applications#revenue|#communications|#risk|#operations`, `Olympus Technology#views`. In the real app, map these to real routes (`/platform/graph`, `/connect/sdks`, `/docs/<id>`).
- **Header menus**: see Site Header.
- **Scene**: see component.
- **Hover**: buttons step one rung darker (never opacity-only); links go to #3a6896/#2d5373; menu items bg #eceae5. 120ms.
- **Responsive**: fluid down to ~360px. Grids use auto-fit/minmax, hero columns stack, header switches at 1080px, touch targets ≥44px on mobile. Docs collapse the sidebar into a mobile nav (see Docs states).
- **Reduced motion**: all transitions/animations ~0, scene autoplay off.

### Docs (`Docs.dc.html` + `docs-content.js`)
Graphite, three-pane docs app: left nav by section, article, right "on this page". Content is a global `window.AETHER_DOCS` with `sections[]` (id, label, glyph, color, pages[]) and `pages{}` (id → title, body blocks). Layers: **Understand → Use → Connect → Build → Operate → Reference**; plus Get started, SDKs, role pages, task guides (seven), symbol key link and glossary. Move this to MDX or a CMS, one file per page, and keep ids as slugs. Aliases: `quickstart→quickstart-web`, `how→how-it-works`, `concepts→signals`.
UI states (switchable via `?state=`, with a debug bar that is design-only, hide with `?bar=0`): `page`, `search`, `no-results`, `mobile-nav`, `private`. "Not public" explains that customer-only/internal pages are excluded from nav, search, and sitemap. Prev/next cards at article end.

### Portal (`Aether Portal.dc.html`)
Stateful, Graphite/Stone hybrid restyled to brand. Flow stages: `signup` / `signin` → plan + payment (non-Alpha plans need card) → onboarding `goal → connect → … ` (STEPS array) → workspace with Profile 360. Detail:
- Plans (Alpha free, Beta $299/mo, …, Omega custom/"Request a review"), goals, connectors (CONNS with minimum plan), consent scopes per connector (SCOPES) are all in the script constants. Reuse as seed data.
- Persistence: `localStorage` key `aether.journey.v3` stores account, email, name, plan, stage, step, done, goal. Returning user lands on sign-in. `?mode=signup` forces signup. `?plan=` preselects.
- Payment, auth and connection are **simulated** with timeouts (`pay()`, `busy` spinner). Replace with real auth, billing and OAuth.
- Upgrade flow: `upgrade` state, card needed if target rank > current.

### Contact, Status, Legal, 404
- Contact: topic picker + short message, success state "Request received". Params choose brand and type.
- Status: overall banner glyph + label (●/▲/■), per-service list, past incidents. Static sample data. Wire to a real status feed.
- Legal: privacy and terms from a `doc` object. Replace with counsel-approved text.
- Not Found: "This page doesn't exist." with links.

## Product claims to preserve (do not overstate)
- Deployment: only **shared cloud** and **dedicated** are marked available. Others (private cloud, on-prem) must not appear as available.
- Imports: only **CSV, JSON, JSONL** are live.
- Pricing: no per-integration fees. Connectors per plan as in Pricing/Portal data.
- Numbers on Aether Home stat strip (13 ready-made integrations, 4 SDKs: web, iOS, Android, React Native) must be kept in sync with the real connector list.

## State management
Mostly static. Stateful pieces: header menu/open state; Scene (story, stage, hold); Profile 360 (tab selection); Relationship Explorer (selected node); Docs (current page, search query, nav open, state); Portal (stage, step, plan, goal, account, payment, upgrade, connections); Pricing (billing toggle and plan details: see file); Contact (form + submitted). No data fetching in the designs. Real implementation needs: auth, billing, connector OAuth, docs search index, status feed, form submission endpoint.

## Assets
- `assets/logo-*.svg`, `lockup-*.svg`: official brand marks. Don't redraw or recolor.
- `assets/brand/*.svg`: third-party logos for the Connect page (Stripe, Shopify, HubSpot, Salesforce, Klaviyo, Segment, Slack, etc.). Confirm usage rights.
- `assets/og/*.png`: link-preview images, dark and headline-only, one per page (1200×630).
- Fonts: Geist and Geist Mono (latin woff2) in `_ds/.../fonts`.

## Files
- `pages/`: all `.dc.html` designs, `support.js` (runtime for opening them), `docs-content.js`, `ios-frame.jsx`.
- `assets/`: marks, brand logos, OG images.
- `_ds/`: tokens CSS, fonts, DS bundle and README.
- `github.md`: source repo mapping (`DammnThatsCrazy/AETHER`, `apps/site/design/designs`) and screen map to target files such as `src/pages/aether/*`, `src/pages/olympus/*`, `src/site/navigation.ts`, `src/site/plans.ts`, `src/site/connectors.ts`.
