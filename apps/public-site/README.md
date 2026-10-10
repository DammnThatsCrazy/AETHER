# apps/public-site

One Vite + React app for both public sites:

| Host | Site |
|---|---|
| `www.olympuslabsml.com`, `www.staging.olympuslabsml.com` | Olympus Labs company pages |
| `aether.olympuslabsml.com`, `aether.staging.olympuslabsml.com` | Aether marketing, docs, status, contact, legal, portal (`/app`) |

`src/site/site.ts` picks the site from the hostname. A build-time `VITE_SITE`
wins, then `?site=olympus|aether`, so one preview domain can show either site.
Production builds each site separately (`VITE_SITE=olympus` for `www`) because
each build prerenders its own pages.

Links between the two sites are absolute. `VITE_SITE_OLYMPUS_URL` and
`VITE_SITE_AETHER_URL` set their origins; without them a staging host links to
its staging pair and every other host links to production. The tab icon
follows the resolved site.

Geist and Geist Mono are vendored in `src/assets/fonts` (SIL OFL 1.1) rather
than installed from npm, whose `geist` package requires Next.js as a peer.

It replaces `apps/marketing-olympus`, `apps/marketing-aether`,
`apps/docs`, `apps/status` and `apps/aether-web` after cutover.

## Design handoff

`design/` is the handoff this app implements: `design/HANDOFF.md` (the current
surfaces handoff: pages, Signal Blue, copy and claim rules), `design/README.md`
(route map and acceptance checklist) and `design/designs/*.dc.html` (reference
designs that open in a browser). The references are never built or shipped.

Each page under `src/pages` and the shared widgets in `src/components` are the
design's markup with its inline styles kept verbatim; `src/design/runtime.ts`
turns them into React styles, hover classes and real links (`Docs.dc.html?page=x`
→ `/docs/x`, cross-site links absolute, the Portal → a pilot request on a
pilot-only build). `src/design/base.css` restores the browser and Design System
defaults the designs assume inside a `.dc` page root (Tailwind's preflight
resets them elsewhere). `src/design/page-meta.ts` holds each page's title,
description and link-preview image from the design helmets
(`src/assets/og/*.png`, 1200×630).

Provider logos are the reviewed marks in `packages/ui/brand` (served at
`/providers/<file>.svg`; see `docs/product/brand-system/providers.md`). Connect, the
docs connector catalog and the home count show all 21 integrations.

Decisions that differ from the handoff:

- Sign-in stays on Auth0 (the handoff assumed Cognito).
- The site launches on the staging hosts first, then production.
- The design's mock checkout is not built: plan choices go to sign-up in the
  product (`/app/signup?plan=`), or to a pilot request on a pilot-only build.
- Legal pages keep a "Draft for counsel" notice until counsel supplies the
  final text.
- The old apps and folders are removed only after cutover plus seven days.

## Prerendering and SEO

`npm run build` builds the client, then a server bundle of
`src/entry-server.tsx`, then runs `scripts/prerender.mjs`. That renders every
page of the build's site (`src/seo/pages.ts`) to `dist/<path>.html` (`/` →
`index.html`, `/platform/graph` → `platform/graph.html`) with its title,
description, canonical URL, Open Graph and Twitter cards, JSON-LD, and the
hover styles it registered. It also writes `404.html`, redirect pages for
retired Aether marketing URLs, `sitemap.xml` and `robots.txt`. A build whose
canonical origin is not production (staging) is `noindex` and disallows all
crawling. In the browser, `src/app/main.tsx` hydrates a page whose markup
matches its path and site; the hosting fallback's shell for any other path is
hidden by an inline guard and rendered fresh.

## Commands

```bash
npm run dev --workspace=apps/public-site    # http://localhost:5180/?site=olympus
npm test --workspace=apps/public-site
npm run build --workspace=apps/public-site
```
