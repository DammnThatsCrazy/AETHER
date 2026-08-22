---
title: Demo Data
slug: operations/demo-data
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Demo Data

Demo data is synthetic, explicit, and backend-owned. Aether, Kyber, and the Demo
App read it through the real FastAPI contracts and canonical repositories. No
normal frontend may manufacture operational records, intercept requests with a
browser mock worker, or treat a failed request as an empty dataset.

## Default behavior

`make dev` and normal backend/frontend startup never seed data. A fresh
repository therefore produces a healthy but unpopulated system:

- a successful collection response with no records renders an empty state;
- a missing entity uses the canonical not-found response;
- a timeout, authorization failure, malformed response, or dependency failure
  renders unavailable/error, not empty;
- unobserved scores, financial values, health, and timestamps remain
  unavailable rather than becoming zero, healthy, or current.

## Explicit seed and reset contract

The versioned backend seed service is the only canonical synthetic-data source.
Its command surface is:

```bash
make demo-seed
make demo-status
make demo-verify
make demo-reset
make dev-demo
```

These commands invoke the backend seed service and must not be replaced by
frontend scripts that mutate browser memory. Every seeded record is
traceable to a dataset version, seed run, namespace, demo tenant, creation time,
and source domain. Re-running the same dataset is idempotent.

Dataset `v1` includes representative repository-backed tenant, user, entity,
campaign, connector, usage-evidence, intelligence-quality, import,
investigation, alert, payment, settlement, and agentic-commerce records.
Aether, Kyber, and the Demo App disclose seeded tenants only from the
authenticated `/v1/demo-seed/status` response.

Reset requires an explicit tenant, namespace, and confirmation. It removes only
records owned by that seed namespace, preserves non-seeded records, records an
audit event, and verifies tenant isolation. Production always refuses seed and
reset. Staging refuses them unless an explicit staging-demo policy and tenant
allowlist are configured.

## Local in-memory limitation

A separate CLI process cannot change repositories held in another backend
process's memory. The seed engine refuses to write the durable runs/reviews
domains into a process-local in-memory store from the CLI — that would be a
parallel copy the backend API never reads. In-memory demo startup therefore
must invoke the seed engine in-process through the explicit `dev-demo` /
seed-on-start path, or set `AETHER_ALLOW_INMEMORY_SEED=1` to acknowledge the
in-memory path for test/dev. Normal startup remains unseeded. Durable
PostgreSQL/Redis environments use the shared database and durable store through
the ordinary seed CLI.

Local and test demo operations also refuse a non-loopback `DATABASE_URL` — the
`AETHER_ENV` string alone must not gate a shared database. Set
`AETHER_ALLOW_NONLOCAL_DB=1` to explicitly allow a non-local target.

See [Demo App](DEMO-APP.md).
