---
title: Migrations
slug: ops-migrations
section: operations
visibility: I
audience: [dev-senior, ops]
status: experimental
since_version: "0.1.0"
source_files:
  - infra/local/docker-compose.yml
  - services/api/alembic/README
  - services/api/alembic/env.py
  - services/api/entrypoint.sh
related: [ops-local-development, enterprise/deployment-readiness]
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
---

# Migrations

The API database schema is managed with Alembic. Migration scripts live in
`services/api/alembic/versions/`; each migration declares its revision,
`down_revision`, `upgrade()`, and `downgrade()` behavior.

## Apply migrations to a local database

For the repository's local Compose PostgreSQL, start PostgreSQL and run the
one-shot migration service:

```bash
docker compose -f infra/local/docker-compose.yml up -d postgres
docker compose -f infra/local/docker-compose.yml --profile migrate run --rm migrate
```

For a local PostgreSQL database used directly from the host, run Alembic from
`services/api` with `DATABASE_URL` set:

```bash
cd services/api
DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/DATABASE' ../../.venv/bin/alembic upgrade head
DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/DATABASE' ../../.venv/bin/alembic current
```

The configured URL must target the intended database. Do not copy a staging or
production URL into a local development shell. Alembic normalizes PostgreSQL
URLs for the synchronous migration driver; migrations require a reachable
PostgreSQL database and are not applied by the in-memory repository mode.

## Inspect history and status

Use `alembic current` to see the applied revision and `alembic history
--verbose` to inspect the revision chain. Before changing a migration, confirm
that its `down_revision` joins the intended current head and that the full
repository migration graph has one head.

The API container applies migrations only when started with
`RUN_MIGRATIONS=1`. In the local Compose file, the `migrate` profile sets this
for its one-shot job. Ordinary backend startup is not itself evidence that the
database schema is at head; use the migration job or an explicit Alembic status
check.

## Migration safety

- Prefer additive, backward-compatible schema changes. Use a staged migration
  for destructive changes and retain compatibility until consumers have moved.
- Avoid long blocking table rewrites; use online DDL or a backfill process when
  table size or lock behavior warrants it.
- New required columns need a safe default or a separately verified backfill.
- Exercise both upgrade and downgrade on a disposable PostgreSQL database
  where the migration permits it. Review the actual `downgrade()` semantics;
  a downgrade can discard data and is not a general production rollback plan.
- For shared or production environments, follow the deployment migration plan,
  approved backup/restore procedure, and environment-specific rollout gates.

## Revision naming and rollback

Use the established date-and-purpose pattern, for example
`20260713_card_linked_payments`. To test a reversible step locally, run
`alembic downgrade -1` followed by `alembic upgrade head` against the same
disposable database. Do not use this as a production rollback command without
an explicit reviewed recovery plan.

See [Local Development Operations](local-development.md) for the local stack
and [Deployment Readiness](DEPLOYMENT-READINESS.md) for rollout context.
