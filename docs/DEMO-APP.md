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

`@aether/demo` (`frontend/demo`, port 5177) is the backend seed-status and
provenance console for the same persisted records consumed by Aether and Kyber.
It is built with Vite, React 19, and `@aether/ui`, but it is not a
fixture-backed substitute for the product.

## The story

> SDK or no SDK → connect Aether → generate graph intelligence → surface
> recommendations → make decisions → take action → observe outcomes → prove value.

The console shows authoritative seed status, dataset version, checksum,
namespace, run times, and inserted/idempotent counts, then links to the Aether
tenant and Kyber operator applications that render the operational records.

## Run

```bash
cp frontend/demo/.env.example frontend/demo/.env
npm run dev --workspace=@aether/demo     # http://localhost:5177
npm run test --workspace=@aether/demo
npm run build --workspace=@aether/demo
```

Configure the Demo App with an explicit live environment and backend URL. A
missing or invalid environment prevents normal application startup. The clean
local path is backend-backed and empty; use a real backend development session
for authentication.

## Data & seeding

The backend seed phase provides the versioned seed/status/verify/reset commands
documented in [Demo Data](DEMO-DATA.md). The frontend never seeds records. A
non-dismissible banner appears only when backend tenant metadata identifies the
selected tenant as seeded.

When the backend returns an empty collection, the Demo App shows a successful
empty state. When the backend cannot be reached or rejects a request, it shows
an unavailable/error state and does not display cached example records or
pretend a mutation succeeded.

Legacy Aether/Kyber mock workers are removed by a scoped startup migration that
unregisters only `mockServiceWorker.js` registrations and clears only
legacy-mock caches. It does not unregister unrelated service workers or clear
unrelated browser preferences.

See [Demo Data](DEMO-DATA.md), [Demo Walkthrough](DEMO-WALKTHROUGH.md), and
[Demo Sales Script](DEMO-SALES-SCRIPT.md).
