# KYBER — Aether Command Surface

Kyber is Aether's internal operator control surface. It provides leadership and operators with macro-to-micro visibility across the Aether platform.

## What is Kyber?

A hybrid of:
- Executive mission control
- Operational cockpit
- Graph atlas (Noesis)
- Agent command center
- Diagnostics console
- Review and approval surface
- Replay/lab environment

## Quick Start

```bash
# From repo root
npm install

# Start against the local backend
cd frontend/kyber
VITE_KYBER_ENV=local VITE_API_BASE_URL=http://localhost:8000 \
  VITE_AETHER_ENDPOINT=http://localhost:8000 npm run dev
```

## Pages

| Page | Purpose |
|------|---------|
| Mission | Executive dashboard with health, alerts, brief, and recommended actions |
| Live | Real-time event stream with filtering and severity markers |
| Noesis | Graph workspace — topology, clusters, paths, overlays, replay |
| Entities | 360-degree views for customers, wallets, agents, protocols, contracts, clusters |
| Command | Controller roster, objectives, schedules, CHAR status |
| Diagnostics | System health, dependencies, circuit breakers, lag metrics |
| Review | Approval workflows with diffs, evidence, rationale, audit trail |
| Lab | Fixture browser, replay, API inspection, data transforms, export |

## Runtime Environments

- **local**: Connected to local Aether services
- **staging**: Connected to staging infrastructure
- **production**: Read-only observer posture by default

Kyber never manufactures operational data in the browser. A successful empty
backend response renders an empty state; request failures render unavailable.

## Tech Stack

- React 19 + TypeScript (strict)
- Vite 6
- Tailwind CSS 4 with tokenized theme
- Recharts (charts)
- Cytoscape.js (graph visualization)
- Zod (runtime validation)
- Vitest (unit/component/integration tests)
- Playwright (e2e smoke tests)

## Scripts

```bash
npm run dev          # Start dev server
npm run build        # Production build
npm run typecheck    # TypeScript check
npm run lint         # ESLint
npm run test         # Unit tests
npm run test:e2e     # Playwright smoke tests
npm run test:all     # All test suites
```

## Relationship to Playground

The existing `playground/` is a developer-facing SDK demo. Kyber is the internal operator surface. They coexist independently. Future work may extract shared components from Kyber for a customer-facing demo app.

See also: [ARCHITECTURE.md](./ARCHITECTURE.md), [AUTH.md](./AUTH.md), [ENVIRONMENT.md](./ENVIRONMENT.md)
