---
title: Local Development Operations
slug: ops-local-development
section: operations
visibility: I
audience: [dev-junior, dev-senior, ops]
status: experimental
since_version: "0.1.0"
source_files:
  - AGENTS.md
  - Makefile
  - apps/aether-web/.env.example
  - apps/aether-web/package.json
  - apps/kyber-web/.env.example
  - apps/kyber-web/package.json
  - config/environments/.env.local.example
  - infra/local/docker-compose.yml
  - package.json
  - pyproject.toml
  - services/api/actions/agent/deployment_routes.py
  - services/api/actions/agent_marketplace/graph_state_check.py
  - services/api/actions/agent_marketplace/identity_binding.py
  - services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py
  - services/api/alembic/versions/20261011_agent_delegated_to_namespace.py
  - services/api/config/settings.py
  - services/api/main.py
  - services/api/repositories/repos.py
related: [ops-migrations, reliability/operations]
canonical_owner: platform@aether
estimated_read_minutes: 7
toc_depth: 3
---

# Local Development Operations

Use the repository root for the commands below. Local development has two
backend modes: a host-run API that uses in-memory repositories when
`DATABASE_URL` is unset, and the Docker Compose stack, which uses local
PostgreSQL. The Aether and Kyber web apps call the FastAPI backend; they do not
share backend memory or create application data by themselves.

## Prerequisites and setup

- Python 3.10 or newer.
- Node.js and npm for the web workspaces.
- Docker with the Compose plugin and Make for the container-backed stack.

Install the Python and JavaScript dependencies from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev,backend,agent]"
npm ci
source .venv/bin/activate
```

Create local environment files from the checked-in examples:

```bash
cp config/environments/.env.local.example .env
cp apps/aether-web/.env.example apps/aether-web/.env.local
cp apps/kyber-web/.env.example apps/kyber-web/.env.local
```

Keep `AETHER_ENV=local`. The host-run API can use in-memory repositories with
`DATABASE_URL` unset. The Compose backend uses the local PostgreSQL service and
requires a local-only `JWT_SECRET` in the root `.env`; choose a development
value and never reuse a staging or production secret. Optional provider and
billing integrations remain disabled unless you configure them for a specific
local task.

## Start the backend

### Host-run API with in-memory repositories

Run the API from the root checkout:

```bash
make serve-backend
```

The API listens on `http://localhost:8000`. This mode has no PostgreSQL
dependency when `DATABASE_URL` is unset. Its in-memory state belongs to that
process and disappears when it stops.

### Docker Compose with local PostgreSQL

Apply pending migrations before starting the API for the first time or after
pulling a change that adds a migration:

```bash
docker compose -f infra/local/docker-compose.yml up -d postgres
docker compose -f infra/local/docker-compose.yml --profile migrate run --rm migrate
```

Then start the default local stack:

```bash
make dev
```

The default stack runs PostgreSQL and the backend API. It does not start the
optional streaming, analytics, observability, notebook, or legacy services;
use the documented `make dev-*` profile targets in the root Makefile when a
task needs one of them. Check the API with `http://localhost:8000/v1/health`
and inspect service output with:

```bash
docker compose -f infra/local/docker-compose.yml logs -f postgres backend
```

`make dev-down` stops the local containers without deleting the PostgreSQL
volume. Avoid `docker compose down -v` unless you intentionally want to erase
the local database volume and all data in it.

## Start the web apps

In separate terminals, from the repository root:

```bash
npm run dev --workspace=apps/aether-web
npm run dev --workspace=apps/kyber-web
```

Aether runs at `http://localhost:5175`; Kyber runs at
`http://localhost:5174`. The example app environment files point to the local
API at port 8000. Keep `VITE_AETHER_ENV` and `VITE_KYBER_ENV` set to `local`.

## Empty data and demo data

Normal `make dev` startup does not seed demonstration records. An empty
repository should display an empty state; an unavailable backend should
display an unavailable/error state. Neither condition should be replaced with
fixture records or represented as successful empty data.

To explicitly start the local backend with the versioned demo dataset, use
`make dev-demo`. Check the seed ledger with `make demo-status`, verify the
manifest and records with `make demo-verify`, and use `make demo-reset` only
with its required tenant-and-namespace confirmation. Demo seeding and reset are
guarded against production use. See the Makefile targets and demo-seed
implementation for the exact tenant and namespace configuration.

## Migrations

The API schema is managed with Alembic. For Compose-backed local PostgreSQL,
use the `migrate` service shown above. For a host PostgreSQL database, set
`DATABASE_URL` to that local database and run Alembic from `services/api`:

```bash
cd services/api
DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/DATABASE' ../../.venv/bin/alembic upgrade head
DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/DATABASE' ../../.venv/bin/alembic current
```

Use only a local development database for these commands. Review each
migration’s downgrade before rolling it back; database downgrade or volume
deletion can remove data. See [Migrations](migrations.md) for migration
conventions and the repository’s migration workflow.

## Checks while developing

Run the smallest checks for the files you changed. Examples:

```bash
cd services/api && ../../.venv/bin/python -m pytest tests/path/to/test_file.py -q
npm test --workspace=apps/aether-web
npm test --workspace=apps/kyber-web
```

For source changes, documentation ownership, PR verification, and the
distinction between focused checks and final PR evidence, follow
[Contributing](CONTRIBUTING.md) and the root `AGENTS.md`.

## Explore agent telemetry locally

Agent deployment registration, Kyber telemetry diagnostics, and graph
projection are feature-gated and default off. To exercise those paths, set the
following in the root `.env` before starting the API or Compose backend, then
restart it:

```dotenv
AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED=true
KYBER_EXTERNAL_AGENT_TELEMETRY_ENABLED=true
AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED=true
```

With PostgreSQL-backed Compose, apply migrations first using the steps above.
The registry flag mounts the tenant deployment API and identity-binding route;
the Kyber flag mounts the operator diagnostics, including the independent
read-only graph-state check; and the graph flag enables graph projection for
new eligible observations. These flags do not seed demo records or authorize
unreviewed external actions. Bind a deployment to a canonical tenant Agent
explicitly, and use the Operations Runbook to distinguish source-reported
activity, delegation-scope evaluation, outbox recovery, and persisted graph
state. Host-run in-memory state disappears when the API process stops.
