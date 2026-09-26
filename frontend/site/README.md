# frontend/site

One Vite + React app for both public sites:

| Host | Site |
|---|---|
| `olympuslabsml.com`, `staging.olympuslabsml.com` | Olympus Labs company pages |
| `aether.olympuslabsml.com`, `aether.staging.olympuslabsml.com` | Aether marketing, docs, status, contact, legal, portal (`/app`) |

`src/site/site.ts` picks the site from the hostname. A build-time `VITE_SITE`
wins, then `?site=olympus|aether`, so one preview domain can show either site.

Links between the two sites are absolute. `VITE_SITE_OLYMPUS_URL` and
`VITE_SITE_AETHER_URL` set their origins; without them a staging host links to
its staging pair and every other host links to production. The tab icon
follows the resolved site.

Geist and Geist Mono are vendored in `src/assets/fonts` (SIL OFL 1.1) rather
than installed from npm, whose `geist` package requires Next.js as a peer.

It replaces `frontend/olympus-marketing`, `frontend/aether-marketing`,
`frontend/docs`, `frontend/status` and `frontend/aether` after cutover.

## Design handoff

`design/` is the handoff this app implements: `design/README.md` (route map,
tokens, behavior, acceptance checklist) and `design/designs/*.dc.html`
(reference designs that open in a browser). The references are never built or
shipped. Decisions that differ from the handoff:

- Sign-in stays on Auth0 (the handoff assumed Cognito).
- The site launches on the staging hosts first, then production.
- The old apps and folders are removed only after cutover plus seven days.

## Commands

```bash
npm run dev --workspace=frontend/site    # http://localhost:5180/?site=olympus
npm test --workspace=frontend/site
npm run build --workspace=frontend/site
```
