# Backend demo seed core

This package owns Aether's explicit synthetic dataset. Domain records are
written through the same `BaseRepository` implementations read by normal APIs.
The only schema-specific SQL is the Alembic-managed seed-run ledger, ownership
sidecar, and reset-audit evidence; these are seed metadata and have no canonical
domain service.

The v1 checksum covers stable logical identifiers, payloads, and anchor-relative
time offsets. Rendered timestamps use the seed invocation's single anchor and
do not affect idempotency.

Runtime integration:

- `main.py` mounts `build_demo_seed_status_router()` behind normal backend
  authentication in every environment.
- `main.py` mounts `build_demo_seed_mutation_router()` only when `AETHER_ENV`
  is `local` or `test` and `AETHER_DEMO_ROUTE_TOKEN` is set.
- Durable PostgreSQL commands:
  `python -m services.demo_seed.cli seed|status|verify|reset`.
- An in-memory backend must seed in-process, via the authenticated loopback
  router or an explicit `AETHER_DEMO_SEED_ON_START=true` startup path.
- Normal startup never seeds. The explicit seed-on-start path refuses
  staging/production.

## v1 representative coverage

The manifest uses existing API read repositories for tenant metadata, users,
entities, campaigns, connector configuration (without credentials), metering
evidence, intelligence-quality scores, import sessions, investigations,
operator alerts, economic resources and payment intents/events, plus commerce
protected resources, policies, facilitators, approvals, settlements, and
entitlements.

Graph mutations, API-key creation, targeting snapshots, agent objectives/runs,
and review batches are deliberately not seeded in this core dataset. Their
current canonical write services either generate non-injectable identifiers,
have no namespace-safe reset operation, or require external graph/event
dependencies. Adding generic tables or bypassing those services would violate
seed idempotency and reset isolation; those domains remain blocked until their
canonical contracts accept stable IDs and expose provenance-scoped deletion.
