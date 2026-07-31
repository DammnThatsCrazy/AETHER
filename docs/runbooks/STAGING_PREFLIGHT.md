---
title: Runbook — Staging Preflight & Readiness
slug: runbooks/staging-preflight
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 7
toc_depth: 2
source_files:
  - scripts/staging_preflight.py
  - scripts/lib/preflight_env.py
  - scripts/lib/preflight_results.py
  - Backend Architecture/aether-backend/services/gateway/readiness.py
last_synced_commit: "d11ce69"
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
  (`changeme`/`dev-secret`/`test-secret`/…), Redis configured. This is the
  load-bearing check (`scripts/lib/preflight_env.py`).
- **db** — asyncpg `SELECT 1`, alembic head-vs-`alembic_version` parity, and a
  migration-vs-runtime table-shape parity probe. *(Skipped in `--dry-run`.)*
- **redis** — `redis.asyncio` PING. *(Skipped in `--dry-run`.)*
- **http** — `/v1/health` + `/v1/ready` green. *(Only with `--base-url`.)*
- **contracts / version** — contract checks and `scripts/bump_version.py --check`.

Each check yields a `CheckResult` (`scripts/lib/preflight_results.py`); the run
exits 0 only if **all** pass.

### Modes

| Command | Use |
|---|---|
| `staging_preflight.py --env-file deploy/staging.env` | validate a real env file |
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
  `AETHER_ALLOW_INMEMORY_STORE`, pin explicit non-wildcard CORS origins. Do not
  add the value to the allowlist to pass.
- **`db` fails "database at X, expected head(s) …".** Migrations are not applied.
  Run `alembic upgrade head` (or deploy with `RUN_MIGRATIONS=1`) and re-run.
  A **table-shape parity** failure means a table's runtime shape diverged from
  its migration — investigate before deploying; this guards the JSONB-vs-real
  column split.
- **`db`/`redis` fail "unreachable".** Networking/credentials to the datastore.
  Fix connectivity; these are hard, non-skippable outside `--dry-run`.
- **`--dry-run` self-test fails.** The gate itself regressed (a fixture or a
  check changed). Fix the check/fixture — do NOT skip the dry-run in CI.

## Readiness — `GET /v1/ready`

The booted service's own health gate (`services/gateway/readiness.py`), public
(no auth), returning **200 when ready, 503 when not**, with a per-check map that
never echoes secret values. Checks:

- **database** — pool responsive (in local: in-memory repos report ok).
- **migrations** — DB `alembic_version` is one of the repo's alembic head(s);
  heads are computed once from disk, the DB revision cached ~30 s. *(Skipped in
  local / no pool.)*
- **cache**, **event_bus** — backends reachable.
- **workers** — per-role health of the worker roles *this process supervises*.
  Graded by criticality, declared in
  `Backend Architecture/aether-backend/services/runtime/roles.py`:
  - a role in `RELEASE_CRITICAL_ROLES` (`outbox-relay`, `stream-worker`,
    `identity-worker`, `graph-writer`) reports `failed` and flips `ready` false;
  - any other role reports `degraded` — `ready` stays true and only that role's
    capability is marked unavailable;
  - a role this process should supervise but cannot see reports `unknown`, which
    counts as unavailable. Absence of a signal is never treated as health.
  A pure `api` task supervises no roles, so this check is `skipped` there and the
  worker fleet is gated by the worker tasks' own endpoints (see below).
- **auth_config** — non-local only; JWT secret present and not the default.

`ready` is the AND of every check being `ok`, `skipped`, or `degraded`
(`degraded` is emitted only by `workers`). The response also carries a top-level
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
