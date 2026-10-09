"""Real-stack revocation fence for provider raw-record writes.

A tenant data-rights grant is checked when a provider record is admitted and the
record is written to Bronze a moment later. A revocation that commits in that gap
must not leave the record retained. The fence is a per-grant PostgreSQL advisory
lock: raw-record writers hold it shared across the final grant re-read and the
Bronze insert, and ``DataRightsGrantRepository.revoke`` takes it exclusively
inside its transaction.

The scenarios live in
``services/backend/tests/provider_runtime/rights_fence_scenarios.py`` and also run
in memory (``test_rights_revocation_fence.py``); here they run against real
pooled asyncpg connections so the lock, not asyncio scheduling, serializes them.

Skips (never fails) when DATABASE_URL is unset, so AETHER_ENV=local and
``make ci-check`` are unaffected. Runs under
.github/workflows/production-equivalent-ci.yml, where migrations are applied
first (``bronze_provider_records`` and the data-rights tables must exist).
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "backend"
SCENARIOS = BACKEND_ROOT / "tests" / "provider_runtime" / "rights_fence_scenarios.py"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_BACKEND_PREFIXES = (
    "config", "services", "shared", "middleware", "dependencies", "repositories",
)


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


@contextmanager
def fresh_backend():
    """Freshly-imported backend modules, evicted again on exit.

    Mirrors the other real-stack tests so ``repositories.repos._pool`` is built
    from the CURRENT DATABASE_URL.
    """
    _evict_backend()
    try:
        spec = importlib.util.spec_from_file_location("rights_fence_scenarios", SCENARIOS)
        scenarios = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = scenarios  # dataclasses resolve annotations via sys.modules
        spec.loader.exec_module(scenarios)
        repos = importlib.import_module("repositories.repos")
        data_rights = importlib.import_module("services.integrations.data_rights.service")
        repository = importlib.import_module("services.integrations.data_rights.repository")
        yield scenarios, repos, data_rights, repository
    finally:
        sys.modules.pop("rights_fence_scenarios", None)
        _evict_backend()


def _require_real_stack() -> str:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        pytest.skip(
            "DATABASE_URL not set — the revocation fence is only proven against a "
            "real Postgres (see .github/workflows/production-equivalent-ci.yml)"
        )
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        pytest.skip("asyncpg not installed — cannot exercise the real-pool path")
    return database_url


async def _cleanup(database_url: str, tenant_id: str) -> None:
    import asyncpg

    try:
        conn = await asyncpg.connect(database_url)
    except Exception:
        return
    try:
        await conn.execute("DELETE FROM bronze_provider_records WHERE tenant_id = $1", tenant_id)
        # Grant events are append-only by trigger; grants are left in place and are
        # tenant-scoped to a unique per-run tenant.
    finally:
        await conn.close()


def _run_scenario(name: str) -> None:
    database_url = _require_real_stack()

    async def main() -> None:
        with fresh_backend() as (scenarios, repos, data_rights, repository):
            # The grant repository is in-memory under AETHER_ENV=local by design;
            # hand it the real pool explicitly so the lock under test is Postgres's.
            service = data_rights.DataRightsService(
                repository.DataRightsGrantRepository(pool_provider=repos.get_pool)
            )
            assert await repos.get_pool() is not None, "expected a real asyncpg pool"
            tenant = scenarios.new_tenant()
            env = scenarios.Env(service=service, tenant=tenant)
            try:
                await getattr(scenarios, name)(env)
            finally:
                await _cleanup(database_url, tenant)

    asyncio.run(main())


def test_revocation_waits_for_an_in_flight_write():
    _run_scenario("revocation_waits_for_an_in_flight_write")


def test_a_write_after_a_committed_revocation_is_denied():
    _run_scenario("a_write_after_a_committed_revocation_is_denied")


def test_no_record_is_retained_after_revocation_returns():
    _run_scenario("no_record_is_retained_after_revocation_returns")
