---
title: Demo App
slug: operations/demo-app
section: operations
visibility: I
audience: [exec, buyer, dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Demo App

`@aether/demo` (`frontend/demo`, port 5177) is a closed, synthetic, fully-seeded
demo environment that tells the complete Aether value story end to end. It runs
**entirely on MSW fixtures in `local-mocked` mode — no backend required** — and
is built with the same stack as the tenant/operator apps (Vite + React 19 +
`@aether/ui`).

## The story

> SDK or no SDK → connect Aether → generate graph intelligence → surface
> recommendations → make decisions → take action → observe outcomes → prove value.

The app shows both ingestion paths (SDK: Web/iOS/Android; no-SDK: connector +
signed webhook + import), then Graph/Profile360 → recommendation families → the
OODA loop → decisions/actions/dispatch → outcomes/ledger → playbooks/ROI →
value review → data quality, and a toggle to the **Kyber operator view** of the
same demo tenant (aggregate-only).

## Run

```bash
cp frontend/demo/.env.example frontend/demo/.env
npm run dev --workspace=@aether/demo     # http://localhost:5177
npm run test --workspace=@aether/demo
npm run build --workspace=@aether/demo
```

`VITE_DEMO_ENV=local-mocked` starts the MSW worker before render. An ingestion
simulator posts to a mocked `/v1/ingest/events` so the SDK/no-SDK buttons work
offline.

## Data & seeding

All data is synthetic and lives in `src/data/fixtures.ts`. The app is
fixture-driven, so `demo:seed` / `demo:reset` are local no-ops (reload to
restore). An optional backend seed endpoint (`AETHER_DEMO_SEED_ENABLED`, off by
default) is a documented future activation step. See [Demo Data](DEMO-DATA.md),
[Demo Walkthrough](DEMO-WALKTHROUGH.md), and [Demo Sales Script](DEMO-SALES-SCRIPT.md).
