---
title: Local Development
slug: operations/local-development
section: operations
visibility: I
audience: [dev-junior, dev-senior, ops]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# Local Development

A developer should be able to clone the repo, configure `.env` from the
examples, and run the backend and both frontends locally. Aether and Kyber
always call the real FastAPI backend. Local in-memory repositories are empty
until real actions create data or an explicit backend demo seed is requested.

## Install dependencies

```bash
# Python (backend + tooling)
pip install uv && uv pip install --system -e ".[dev,security,backend,agent]"

# Node workspaces (frontends + shared)
npm ci --ignore-scripts
```

## Configure environment

```bash
cp .env.example .env
cp frontend/aether/.env.example frontend/aether/.env
cp frontend/kyber/.env.example frontend/kyber/.env
```

All optional systems default off. The frontend environment name and backend URL
are required even in local development; tests inject an explicit `test`
environment.

## Run the apps

```bash
make serve-backend                       # FastAPI on :8000
cd frontend/aether && npm run dev        # Aether (tenant) on :5175
cd frontend/kyber  && npm run dev        # Kyber (operator) on :5174
```

The examples set `VITE_AETHER_ENV=local` and `VITE_KYBER_ENV=local` with a live
local `VITE_API_BASE_URL`. Missing or invalid configuration stops application
startup instead of falling back. The deprecated `local-live` spelling maps only
to `local`, emits a warning, and cannot activate mocks.

Local authentication uses a real backend development session. That route exists
only in the local/test backend and is not mounted in staging or production; the
browser does not mint reusable tokens.

## Empty, unavailable, and demo startup

`make dev` never inserts demonstration records. With an empty backend, a
successful API response renders a truthful empty state. If the backend is
stopped or a dependency fails, the affected route renders unavailable/error;
it must not render fixture data or a successful empty state.

The backend demo-seed phase provides the explicit workflow:

```bash
make dev-demo
make demo-status
make demo-verify
make demo-reset
```

`dev-demo` is intentionally distinct from normal startup. A separate CLI cannot
modify repositories held inside another process's memory, so in-memory demo
mode invokes the seed engine in-process through its explicit seed-on-start path.
PostgreSQL mode uses the shared database. Seed and reset are always refused in
production; staging requires an explicit demo policy and tenant allowlist.

## Legacy mock-worker cleanup

Aether and Kyber run a scoped migration before making API requests. It
unregisters only registrations whose script URL is the legacy
`mockServiceWorker.js` and removes only legacy mock/MSW caches. It does not
unregister unrelated service workers or broadly clear local storage. If a
browser still intercepts calls, close all old application tabs, reload the new
build, and inspect Application > Service Workers for the legacy script.

## Feature flags for local exploration

To exercise the newer surfaces locally, enable their flags in `.env` before
starting the backend:

```bash
AETHER_DATA_QUALITY_ENABLED=true
KYBER_INTELLIGENCE_QUALITY_ENABLED=true
```

## Tests, lint, docs

```bash
# Backend (root suite is what CI runs)
python -m pytest tests/ -n auto

# Frontends
cd frontend/aether && npm run typecheck && npm test
cd frontend/kyber  && npm run typecheck && npm run test:component && npm run test:integration && npm run test:e2e

# Docs validation + generation
make validate-frontmatter
make extract-docs
python scripts/sync_docs.py
python scripts/docs_drift.py --strict
python scripts/validate_contracts.py

# Lint
python -m ruff check .
npm run lint
```

See [Deployment & Hosting Readiness](DEPLOYMENT-HOSTING-READINESS.md) and the
[Productization Checklist](PRODUCTIZATION-CHECKLIST.md).
