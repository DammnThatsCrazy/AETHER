"""Aether Gateway — Readiness probe.

Aggregates infrastructure checks behind GET /ready and GET /v1/ready:

- ``database``    — asyncpg pool responsive (in-memory backend passes in local)
- ``migrations``  — DB alembic_version matches the repo's alembic head(s);
                    head revisions are computed once from disk and the DB
                    revision is cached in-process for 30 s
- ``cache``       — Redis / in-memory cache health
- ``event_bus``   — Kafka / in-memory producer health
- ``workers``     — per-role health of the worker roles this process hosts
- ``auth_config`` — non-local only: JWT secret loaded and non-default
                    (values are never echoed)

Worker health is graded, not advisory. A worker role declared release-critical
in ``services/runtime/roles.py::RELEASE_CRITICAL_ROLES`` fails the whole probe;
any other role's failure leaves the probe ready and marks only its own
capability unavailable. Absence of a signal for a role this process is supposed
to host counts as a failure, never as health.

Response shape:
    {"ready": bool, "environment": "...",
     "checks": {name: {"status": "ok"|"degraded"|"failed"|"skipped",
                       "detail": "..."}},
     "capabilities": {capability: {"available": bool, "state": "...",
                                   "role": "...", "release_critical": bool,
                                   "detail": "..."}}}

``degraded`` is emitted only by the ``workers`` check and does not fail the
probe; every other check is ready only on ``ok`` or ``skipped``.

The report never contains secrets or stack traces; failure details are
limited to exception class names and terse descriptions.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from config.settings import Environment
from shared.logger.logger import get_logger

logger = get_logger("aether.gateway.readiness")

# Check statuses that do not block readiness. "degraded" is worker-scoped: a
# non-release-critical capability is unavailable, which is reported to callers
# through the capabilities map but must not block a rollout.
_READY_STATUSES = ("ok", "skipped", "degraded")

# ── module-level caches ──────────────────────────────────────────────────────

_MIGRATION_DB_CACHE_TTL_S = 30.0

# Alembic head revision(s): pure file I/O, computed once per process.
_head_revisions: Optional[frozenset[str]] = None

# (monotonic timestamp, version_num) of the last successful DB revision read.
_db_revision_cache: tuple[float, Optional[str]] = (0.0, None)


def _alembic_script_dir() -> str:
    # services/gateway/readiness.py → <backend root>/alembic
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend_root, "alembic")


def _alembic_head_revisions() -> frozenset[str]:
    """Compute (once) and cache the repo's alembic head revision(s)."""
    global _head_revisions
    if _head_revisions is None:
        from alembic.script import ScriptDirectory

        script = ScriptDirectory(_alembic_script_dir())
        _head_revisions = frozenset(script.get_heads())
    return _head_revisions


async def _database_revision(pool: Any) -> Optional[str]:
    """Read alembic_version.version_num with a 30 s in-process cache."""
    global _db_revision_cache
    ts, cached = _db_revision_cache
    if cached is not None and (time.monotonic() - ts) < _MIGRATION_DB_CACHE_TTL_S:
        return cached
    version = await pool.fetchval("SELECT version_num FROM alembic_version")
    if version is not None:
        _db_revision_cache = (time.monotonic(), str(version))
        return str(version)
    return None


async def _resolve_pool() -> Any:
    """Resolve the shared asyncpg pool (None = in-memory repositories)."""
    from repositories.repos import get_pool

    return await get_pool()


# ── check helpers ────────────────────────────────────────────────────────────

def _ok(detail: str) -> dict[str, Any]:
    return {"status": "ok", "detail": detail}


def _failed(detail: str) -> dict[str, Any]:
    return {"status": "failed", "detail": detail}


def _skipped(detail: str) -> dict[str, Any]:
    return {"status": "skipped", "detail": detail}


def expected_worker_roles(settings: Any) -> frozenset[str]:
    """The worker roles this API process is itself responsible for supervising.

    Mirrors the lifespan's own gating in ``main.py``: a pure ``api`` process
    supervises nothing (its worker fleet runs as separate tasks and is gated by
    those tasks' own readiness surface), an ungated process runs every worker,
    and a role or execution group runs the roles it expands to.

    Narrowed to the roles that own supervised *loop* specs, because those are
    the only ones the lifespan registers: a consumer-attached role's receive
    loop is registered by ``run_role``, not here, so demanding one in this
    process would fail a probe over work this process never had. Roles that do
    show up in the supervisor regardless are still evaluated —
    :func:`evaluate_worker_readiness` unions expected with observed.
    """
    # Late import: ``services.runtime`` pulls in the whole worker spec builder,
    # which the request path has no reason to load at gateway import time.
    from services.runtime.roles import ROLE_TO_SPEC_NAMES, WORKER_ROLES, roles_in

    runtime = getattr(settings, "runtime", None)
    role = getattr(runtime, "aether_role", "all") or "all"
    if role == "api":
        return frozenset()
    hosted = (
        roles_in(role)
        if getattr(runtime, "worker_roles_enabled", True)
        else WORKER_ROLES
    )
    return frozenset(r for r in hosted if ROLE_TO_SPEC_NAMES.get(r))


# ── report ───────────────────────────────────────────────────────────────────

async def readiness_report(
    registry: Any,
    supervisor: Any,
    settings: Any,
) -> tuple[bool, dict[str, Any]]:
    """Build the readiness report. Returns (ready, response payload)."""
    checks: dict[str, dict[str, Any]] = {}
    is_local = settings.env == Environment.LOCAL

    # ── database (mirrors dependencies/providers.py registry.health_check) ──
    pool: Any = None
    pool_error: Optional[str] = None
    try:
        pool = await _resolve_pool()
    except Exception as exc:
        pool_error = type(exc).__name__
    if pool is not None:
        try:
            await pool.fetchval("SELECT 1")
            checks["database"] = _ok("postgresql pool responsive")
        except Exception as exc:
            checks["database"] = _failed(f"query failed: {type(exc).__name__}")
    elif pool_error is not None:
        checks["database"] = _failed(f"pool unavailable: {pool_error}")
    elif is_local:
        checks["database"] = _ok("in-memory repositories (local)")
    else:
        checks["database"] = _failed("connection pool unavailable in non-local environment")

    # ── migrations ──────────────────────────────────────────────────────────
    if is_local or pool is None:
        checks["migrations"] = _skipped("local environment or no database pool")
    else:
        try:
            heads = _alembic_head_revisions()
            db_revision = await _database_revision(pool)
            if db_revision is None:
                checks["migrations"] = _failed("alembic_version table missing or empty")
            elif db_revision in heads:
                checks["migrations"] = _ok(f"database at head {db_revision}")
            else:
                checks["migrations"] = _failed(
                    f"database at {db_revision}, expected head(s) {sorted(heads)}"
                )
        except Exception as exc:
            checks["migrations"] = _failed(f"migration check error: {type(exc).__name__}")

    # ── cache ───────────────────────────────────────────────────────────────
    try:
        cache_healthy = await registry.cache.health_check()
        if cache_healthy:
            checks["cache"] = _ok(f"mode={getattr(registry.cache, 'mode', 'unknown')}")
        else:
            checks["cache"] = _failed("cache backend unreachable")
    except Exception as exc:
        checks["cache"] = _failed(f"cache check error: {type(exc).__name__}")

    # ── event bus ───────────────────────────────────────────────────────────
    try:
        bus_healthy = await registry.producer.health_check()
        if bus_healthy:
            checks["event_bus"] = _ok(f"mode={getattr(registry.producer, 'mode', 'unknown')}")
        else:
            checks["event_bus"] = _failed("event producer unreachable")
    except Exception as exc:
        checks["event_bus"] = _failed(f"event bus check error: {type(exc).__name__}")

    # ── workers (release-critical roles fail the probe) ─────────────────────
    from services.runtime.supervisor import evaluate_worker_readiness

    worker_health = evaluate_worker_readiness(supervisor, expected_worker_roles(settings))
    capabilities: dict[str, Any] = worker_health["capabilities"]
    if not worker_health["roles"]:
        # This process hosts no worker role and none turned up unannounced.
        # Nothing is being claimed about the fleet: the worker tasks answer for
        # themselves on their own readiness surface (run_role.py).
        checks["workers"] = _skipped("this process supervises no worker roles")
    else:
        critical = worker_health["critical_failures"]
        degraded = worker_health["degraded_roles"]
        if critical:
            status = "failed"
            detail = f"release-critical role(s) unavailable: {', '.join(critical)}"
        elif degraded:
            status = "degraded"
            detail = f"non-critical role(s) unavailable: {', '.join(degraded)}"
        else:
            status = "ok"
            detail = f"{len(worker_health['roles'])} worker role(s) available"
        checks["workers"] = {
            "status": status,
            "detail": detail,
            "roles": worker_health["roles"],
            "critical_failures": critical,
            "degraded_roles": degraded,
            "workers": supervisor.status() if supervisor is not None else {},
        }

    # ── communications subsystem (§21) ──────────────────────────────────────
    # A dedicated comms dimension: storage reachability + comms-required worker
    # dependency (a dead projector/relay fails comms readiness) + backlog. Never
    # fails on a single tenant's credential — that truth is per-connector.
    try:
        from services.comms.readiness import comms_subsystem_readiness
        checks["communications"] = await comms_subsystem_readiness(
            pool=pool, worker_capabilities=capabilities, is_local=is_local,
        )
    except Exception as exc:
        checks["communications"] = _failed(
            f"comms readiness error: {type(exc).__name__}"
        )

    # ── auth config (non-local only; never echo values) ─────────────────────
    if is_local:
        checks["auth_config"] = _skipped("local environment")
    else:
        jwt_secret = getattr(getattr(settings, "auth", None), "jwt_secret", "") or ""
        if jwt_secret and jwt_secret != "change-me-in-production":
            checks["auth_config"] = _ok("jwt secret configured")
        else:
            checks["auth_config"] = _failed("jwt secret missing or default")

    # ── aggregate (every check counts) ──────────────────────────────────────
    ready = all(check.get("status") in _READY_STATUSES for check in checks.values())
    report = {
        "ready": ready,
        "environment": settings.env.value,
        "checks": checks,
        "capabilities": capabilities,
    }
    return ready, report
