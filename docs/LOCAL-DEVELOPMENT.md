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

A developer should be able to clone the repo, configure `.env` from the examples,
and run the backend and both frontends locally — with no external services
required, because local mode uses in-memory repositories (backend) and MSW mocks
(frontends).

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

All new systems default off; no secrets are required for local mocked mode.

## Run the apps

```bash
make serve-backend                       # FastAPI on :8000
cd frontend/aether && npm run dev        # Aether (tenant) on :5175
cd frontend/kyber  && npm run dev        # Kyber (operator) on :5174
```

Frontends default to `VITE_AETHER_ENV` / `VITE_KYBER_ENV = local-mocked`, which
starts the MSW worker before React renders. Set them to `local-live` to call the
backend at `VITE_API_BASE_URL`.

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
