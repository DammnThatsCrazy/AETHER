"""Unit tests for shared.rate_limit.quota_flush.QuotaFlusher.

Tests the Redis-to-Postgres flush logic using pure in-memory mocks.
No live Redis or database connection required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_STUBBED: list[str] = []
for _mod in ("jwt", "cryptography", "cryptography.hazmat",
             "cryptography.hazmat.primitives",
             "cryptography.hazmat.primitives.asymmetric",
             "cryptography.hazmat.primitives.asymmetric.ec",
             "cryptography.hazmat.bindings",
             "cryptography.hazmat.bindings._rust",
             "cryptography.hazmat._oid"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
        _STUBBED.append(_mod)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(scope="module", autouse=True)
def _remove_crypto_stubs():
    yield
    for mod in _STUBBED:
        sys.modules.pop(mod, None)
    for name in list(sys.modules):
        if name == "shared" or name.startswith("shared."):
            sys.modules.pop(name, None)

# flush_once does a dynamic `from repositories.repos import get_pool` —
# provide a module stub so we can swap get_pool per test via sys.modules.
import types as _types
_repos_mod = _types.ModuleType("repositories.repos")
_repos_mod.get_pool = AsyncMock()  # type: ignore[attr-defined]
sys.modules.setdefault("repositories", _types.ModuleType("repositories"))
sys.modules["repositories.repos"] = _repos_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flusher(redis=None):
    from shared.rate_limit.quota_flush import QuotaFlusher
    flusher = QuotaFlusher(redis_client=redis)
    return flusher


def _make_redis(keys: list[str], totals: dict[str, str], overages: dict[str, dict]):
    """Build a mock Redis client returning the supplied fixtures."""
    redis = AsyncMock()

    async def _scan(cursor, match, count):
        # Single-page scan: return cursor=0 (done) and all matching keys
        matching = [k for k in keys if _glob_match(match.rstrip("*"), k)]
        return (0, matching)

    redis.scan = _scan
    redis.get = AsyncMock(side_effect=lambda key: totals.get(key))
    redis.hgetall = AsyncMock(side_effect=lambda key: overages.get(key, {}))
    return redis


def _glob_match(prefix: str, key: str) -> bool:
    return key.startswith(prefix)


def _make_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_flusher_starts_without_redis():
    flusher = _make_flusher()
    assert flusher._redis is None
    assert flusher._table_ensured is False


def test_set_redis():
    flusher = _make_flusher()
    mock_redis = AsyncMock()
    flusher.set_redis(mock_redis)
    assert flusher._redis is mock_redis


@pytest.mark.asyncio
async def test_flush_once_returns_zero_with_no_redis():
    flusher = _make_flusher()
    result = await flusher.flush_once()
    assert result == 0


@pytest.mark.asyncio
async def test_flush_once_returns_zero_when_pool_unavailable():
    redis = AsyncMock()
    flusher = _make_flusher(redis=redis)

    with patch("shared.rate_limit.quota_flush.QuotaFlusher.flush_once") as mock_flush:
        # Simulate pool = None by testing _ensure_table path
        # We want to test the "pool is None" branch directly:
        pass

    # When get_pool returns None, flush should return 0
    with patch("repositories.repos.get_pool", new=AsyncMock(return_value=None)):
        result = await flusher.flush_once()
    assert result == 0


@pytest.mark.asyncio
async def test_flush_once_writes_single_key():
    keys = ["rl:quota:tenant1:2026-05"]
    totals = {"rl:quota:tenant1:2026-05": "5000"}
    overages = {"rl:overage:tenant1:2026-05": {"svc_a": "200"}}

    redis = _make_redis(keys, totals, overages)
    flusher = _make_flusher(redis=redis)
    flusher._table_ensured = True  # skip CREATE TABLE in this test

    pool, conn = _make_pool()

    with patch("repositories.repos.get_pool", new=AsyncMock(return_value=pool)):
        result = await flusher.flush_once()

    assert result == 1
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    # First arg is the SQL; positional args follow
    assert "INSERT INTO tenant_usage" in call_args[0]
    assert call_args[1] == "tenant1"   # tenant_id
    assert call_args[2] == "2026-05"  # billing_period
    assert call_args[3] == 5000        # total_requests
    assert call_args[4] == 200         # overage_total


@pytest.mark.asyncio
async def test_flush_once_writes_multiple_keys():
    keys = [
        "rl:quota:tenant1:2026-05",
        "rl:quota:tenant2:2026-05",
    ]
    totals = {
        "rl:quota:tenant1:2026-05": "100",
        "rl:quota:tenant2:2026-05": "200",
    }
    overages: dict[str, dict] = {}

    redis = _make_redis(keys, totals, overages)
    flusher = _make_flusher(redis=redis)
    flusher._table_ensured = True

    pool, conn = _make_pool()

    with patch("repositories.repos.get_pool", new=AsyncMock(return_value=pool)):
        result = await flusher.flush_once()

    assert result == 2
    assert conn.execute.call_count == 2


@pytest.mark.asyncio
async def test_flush_once_skips_malformed_keys():
    """Keys that don't match the regex pattern are silently skipped."""
    keys = ["rl:quota:not-a-valid-period", "rl:quota:tenant1:2026-05"]
    totals = {"rl:quota:tenant1:2026-05": "99"}
    overages: dict[str, dict] = {}

    redis = _make_redis(keys, totals, overages)
    flusher = _make_flusher(redis=redis)
    flusher._table_ensured = True

    pool, conn = _make_pool()

    with patch("repositories.repos.get_pool", new=AsyncMock(return_value=pool)):
        result = await flusher.flush_once()

    # Only the valid key should be written
    assert result == 1


@pytest.mark.asyncio
async def test_flush_once_skips_key_with_none_total():
    """If Redis returns None for a key, it should be skipped."""
    keys = ["rl:quota:tenant1:2026-05"]
    totals: dict[str, str] = {}  # None for all gets
    overages: dict[str, dict] = {}

    redis = _make_redis(keys, totals, overages)
    flusher = _make_flusher(redis=redis)
    flusher._table_ensured = True

    pool, conn = _make_pool()

    with patch("repositories.repos.get_pool", new=AsyncMock(return_value=pool)):
        result = await flusher.flush_once()

    assert result == 0


@pytest.mark.asyncio
async def test_ensure_table_runs_once():
    """_ensure_table should execute CREATE TABLE only on the first call."""
    redis = AsyncMock()
    flusher = _make_flusher(redis=redis)

    pool, conn = _make_pool()

    await flusher._ensure_table(pool)
    await flusher._ensure_table(pool)  # second call — should be no-op

    # CREATE TABLE executed exactly once
    assert conn.execute.call_count == 1
    call_sql = conn.execute.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS tenant_usage" in call_sql


def test_stop_sets_flag():
    flusher = _make_flusher()
    flusher.stop()
    assert flusher._stopped is True
