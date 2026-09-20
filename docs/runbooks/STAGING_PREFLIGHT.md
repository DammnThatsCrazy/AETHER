---
title: Runbook — Staging Preflight & Readiness
slug: runbooks/staging-preflight
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 7
toc_depth: 2
source_files: [scripts/staging_preflight.py, scripts/lib/preflight_env.py, scripts/lib/preflight_dynamodb.py, scripts/lib/preflight_redis.py, scripts/lib/preflight_results.py, services/backend/services/gateway/readiness.py]
source_hashes:
  "scripts/lib/preflight_dynamodb.py": "sha256:412fa322a11832da710b26c2834a9d7f57a02e0b5451ea4336e7a599de1e41f9"
  "scripts/lib/preflight_env.py": "sha256:f2b8a4efc17d0923f5e3f844907e1c576ab3dbf368de35dc9edfca8094ec8012"
  "scripts/lib/preflight_redis.py": "sha256:418ac3a2e776cfb96572e3b78864a65e96c34c70cfdd838fb3a90b2bf18ee117"
  "scripts/lib/preflight_results.py": "sha256:ce8f40edac30f24e6be3a9840d43c906436059055525cb2fba8df44c5165da86"
  "scripts/staging_preflight.py": "sha256:961ec8e350c05fdb548801e946c27a7385f376331fffec6d5de6d8ea14557c84"
  "services/backend/services/gateway/readiness.py": "sha256:76a97f3b23bdbc35dfed9909b13fbc4de56c3e509e43ea950b60b8855d7c1c3e"
---

# Runbook — Staging Preflight & Readiness

Two fail-closed gates protect a staging/production deploy: the **preflight**
script (run before/at deploy) and the **`/v1/ready`** endpoint (run against the
booted service). A red gate blocks the deploy — that is the gate working. Never
weaken a check to get green; fix the environment.

## Preflight — `scripts/staging_preflight.py`

Validates the target environment before traffic. Checks:

- **env** — instantiates `Settings()` against the candidate env so the same
  fail-closed `__post_init__` guards run: `AETHER_ENV ∈ {staging,production}`,
  no in-memory store, no localhost/wildcard CORS, no placeholder secrets
  (`changeme`/`dev-secret`/`test-secret`/…), and a selected durable cache
  anchor. Staging uses `CACHE_BACKEND=dynamodb` plus
  `DYNAMODB_CACHE_TABLE`; Redis profiles use `REDIS_URL` or `REDIS_HOST`.
  This is the load-bearing check (`scripts/lib/preflight_env.py`). It also
  imports the complete backend API graph under the candidate environment so
  module-level durable-store or router construction failures are caught before
  ECS is woken.
- **db** — asyncpg `SELECT 1`, alembic head-vs-`alembic_version` parity, and a
  migration-vs-runtime table-shape parity probe. *(Skipped in `--dry-run`.)*
- **cache** — DynamoDB `DescribeTable` plus `ACTIVE`/`cache_key` schema
  validation for staging, or `redis.asyncio` PING for Redis profiles.
  *(Skipped in `--dry-run`.)*
- **http** — `/v1/health` + `/v1/ready` green. *(Only with `--base-url`.)*
- **contracts / version** — contract checks and `scripts/bump_version.py --check`.

Each check yields a `CheckResult` (`scripts/lib/preflight_results.py`); the run
exits 0 only if **all** pass.

### Modes

| Command | Use |
|---|---|
| `staging_preflight.py --env-file deploy/legacy-staging.env` | validate a real env file |
| `staging_preflight.py --base-url https://api.staging…` | add live HTTP readiness probes |
| `staging_preflight.py --dry-run` | self-test the gate itself (what CI runs) |
| `staging_preflight.py --json` | machine-readable report |

`--dry-run` is a **self-test of the gate**, not a certification of any live
environment: env/contract checks run against
`tests/fixtures/staging_preflight/valid.env` (must PASS) and `invalid.env` (must
FAIL — proving the gate fails closed). If the known-bad fixture stops failing,
the gate has regressed and the dry run fails. `--dry-run` rejects `--env-file` /
`--base-url` so a self-test can never masquerade as a live pass.

### Symptoms → actions

- **`env` fails "placeholder secret" / "in-memory store" / "CORS".** The env file
  carries a dev/default value. Replace the real secret, unset
  `AETHER_ALLOW_INMEMORY_STORE` and `AETHER_ALLOW_INMEMORY_JOURNEY_STORE`, pin
  explicit non-wildcard CORS origins. Do not add the value to the allowlist to
  pass.
- **`db` fails "database at X, expected head(s) …".** Migrations are not applied.
  Run `alembic upgrade head` (or deploy with `RUN_MIGRATIONS=1`) and re-run.
  A **table-shape parity** failure means a table's runtime shape diverged from
  its migration — investigate before deploying; this guards the JSONB-vs-real
  column split.
- **`db`/`cache` fail "unreachable".** Networking/credentials to the selected
  datastore. Fix connectivity; these are hard, non-skippable outside
  `--dry-run`.
- **`--dry-run` self-test fails.** The gate itself regressed (a fixture or a
  check changed). Fix the check/fixture — do NOT skip the dry-run in CI.

## Readiness — `GET /v1/ready`

The booted service's own health gate (`services/backend/services/gateway/readiness.py`), public
(no auth), returning **200 when ready, 503 when not**, with a per-check map that
never echoes secret values. Checks:

- **database** — pool responsive (in local: in-memory repos report ok).
- **migrations** — DB `alembic_version` is one of the repo's alembic head(s);
  heads are computed once from disk, the DB revision cached ~30 s. *(Skipped in
  local / no pool.)*
- **cache**, **event_bus** — backends reachable.
- **workers** — per-role health of the worker roles *this process supervises*.
  Graded by criticality, declared in
  `services/backend/services/runtime/roles.py`:
  - a role in `RELEASE_CRITICAL_ROLES` (`outbox-relay`, `stream-worker`,
    `identity-worker`, `graph-writer`) reports `failed` and flips `ready` false;
  - any other role reports `degraded` — `ready` stays true and only that role's
    capability is marked unavailable;
  - a role this process should supervise but cannot see reports `unknown`, which
    counts as unavailable. Absence of a signal is never treated as health.
  A pure `api` task supervises no roles, so this check is `skipped` there and the
  worker fleet is gated by the worker tasks' own endpoints (see below).
- **communications** — comms subsystem readiness (`services/backend/services/comms/readiness.py`):
  storage reachability, comms-required release-critical worker dependency (a dead
  ingestion projector via `stream-worker`, or a stopped `outbox-relay`, fails
  comms readiness), and webhook-inbox backlog (`degraded`, not `failed`). It is a
  subsystem signal, never per-tenant: a single tenant's revoked credential does
  not fail comms readiness — that truth is per-connector in the comms health card.
- **auth_config** — non-local only; JWT secret present and not the default.

`ready` is the AND of every check being `ok`, `skipped`, or `degraded`
(`degraded` is emitted by `workers` and `communications`). The response also carries a top-level
`capabilities` map — `{capability: {available, state, role, release_critical,
detail}}` — which is what to read when deciding whether a degraded environment
still serves the path you care about.

### Worker task endpoints

Worker processes (`python -m services.runtime.run_role <role>`) serve their own
health surface on `AETHER_WORKER_HEALTH_PORT` (default `8080`):

- `GET /healthz`, `GET /livez` — **liveness**: 200 while the process is up. This
  is the predicate an ECS container `healthCheck` should use. Pointing a
  container health check at the degraded signal makes ECS kill and replace a task
  that comes back equally degraded, and the deployment never settles.
- `GET /ready`, `GET /readyz`, `GET /v1/ready` — **readiness**: 503 when a
  release-critical role hosted by that task is unavailable, 200 otherwise, with
  the same `roles` / `capabilities` payload the gateway probe returns.

### Symptoms → actions

- **503 with `migrations` failed.** Same as preflight `db`: apply migrations. The
  deploy gate hits `/v1/ready`, so an unmigrated DB correctly blocks rollout.
- **503 with `database`/`cache`/`event_bus` failed.** The dependency is
  unreachable from the running container — fix connectivity/credentials; the
  service is intentionally refusing traffic.
- **503 with `workers` failed.** A release-critical role has no working
  supervised worker in that process. Read `checks.workers.critical_failures` for
  the role and `checks.workers.roles.<role>.detail` for why — `failed` (restart
  budget exhausted), `stale` (no heartbeat within 60 s), `stopped` (the worker
  returned), or `unknown` (nothing registered for a role this process claims).
- **`workers` shows `degraded` and `/v1/ready` is 200.** A non-release-critical
  role is down. This is intentional: the rollout is not blocked, but the
  capability named in `capabilities` is genuinely unavailable and needs the same
  investigation, just not the same urgency.
- **503 with `auth_config` failed.** The JWT secret is missing or still the
  default in a non-local env — set a real secret and restart.

## Escalation

If preflight and `/v1/ready` disagree (preflight green, readiness 503 or vice
versa), capture both reports (`--json` and the `/v1/ready` body) and escalate to
`platform@aether`. Do not deploy past a red gate or downgrade the deploy gate
from `/v1/ready` to `/v1/health`.
