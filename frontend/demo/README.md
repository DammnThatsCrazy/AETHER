# Aether Demo App (`@aether/demo`)

A closed, synthetic, fully-seeded demo environment that tells the complete Aether
value story: **SDK or no SDK → connect Aether → graph intelligence →
recommendations → decisions → actions → outcomes → prove value**, plus the Kyber
operator view of the same demo tenant.

- Runs entirely on MSW fixtures in `local-mocked` mode — **no backend required**.
- Port `5177`. Built with Vite + React 19 + `@aether/ui` (matches aether/kyber).

```bash
cp .env.example .env        # VITE_DEMO_ENV=local-mocked
npm run dev --workspace=@aether/demo   # http://localhost:5177
npm run test --workspace=@aether/demo
```

Synthetic data lives in `src/data/fixtures.ts`. `demo:seed` / `demo:reset` are
no-ops locally (the app is fixture-driven); see `docs/DEMO-DATA.md`. The optional
backend demo seed endpoint is gated by `AETHER_DEMO_SEED_ENABLED` (off by
default). See `docs/DEMO-APP.md` and `docs/DEMO-WALKTHROUGH.md`.
