# Aether Demo App (`@aether/demo`)

The Demo App presents Aether's tenant and operator story against the same
backend-owned records used by Aether and Kyber. It is not an alternate browser
backend and must not own a canonical operational fixture dataset.

- Port `5177`; Vite + React 19 + `@aether/ui`.
- A normal local start is live and empty. The app calls the configured FastAPI
  backend and renders loading, successful-empty, populated, and unavailable
  states distinctly.
- Synthetic records exist only after an explicit backend seed operation. Seed
  and reset are refused in production; staging requires an explicit demo policy
  and tenant allowlist.
- Demo disclosure comes from backend tenant/provenance metadata, never from a
  frontend environment flag.

```bash
cp .env.example .env
npm run dev --workspace=@aether/demo   # http://localhost:5177
npm run test --workspace=@aether/demo
```

The versioned backend seed pipeline and its `demo-seed`, `demo-reset`,
`demo-status`, and `demo-verify` commands are the sole operational demo-data
path. Until that pipeline is available, use the Demo App only for UI development
against a live backend; do not restore browser fixtures or no-op seed scripts.
See `docs/DEMO-DATA.md`, `docs/DEMO-APP.md`, and
`docs/DEMO-WALKTHROUGH.md`.
