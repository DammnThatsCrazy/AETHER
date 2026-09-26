# frontend/site

One Vite + React app for both public sites:

| Host | Site |
|---|---|
| `olympuslabsml.com`, `staging.olympuslabsml.com` | Olympus Labs company pages |
| `aether.olympuslabsml.com`, `aether.staging.olympuslabsml.com` | Aether marketing, docs, status, contact, legal, portal (`/app`) |

`src/site/site.ts` picks the site from the hostname. A build-time `VITE_SITE`
wins, then `?site=olympus|aether`, so one preview domain can show either site.

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
