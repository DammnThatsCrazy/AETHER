"""Profile360 error-erasure fixes (audit item 9).

Covers:
  - composer per-dimension isolation: one subsystem raising degrades only its
    dimension (surfaced in `readiness`) instead of 500-ing the whole profile;
  - real freshness: /quality stale_dimensions and /data-freshness `stale` are
    computed from timestamps, not hardcoded.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

for _mod in ("jwt", "cryptography", "cryptography.hazmat"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.profile.aggregator import Profile360Aggregator, _is_stale  # noqa: E402
from services.profile.composer import ProfileComposer  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── _is_stale ────────────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_is_stale_old_timestamp():
    old = _iso(datetime.now(timezone.utc) - timedelta(hours=48))
    assert _is_stale(old) is True


def test_is_stale_recent_timestamp():
    recent = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
    assert _is_stale(recent) is False


def test_is_stale_missing_is_not_stale():
    assert _is_stale(None) is False
    assert _is_stale("not-a-date") is False


def test_is_stale_naive_timestamp_treated_utc():
    naive_old = (datetime.utcnow() - timedelta(hours=48)).isoformat()
    assert _is_stale(naive_old) is True


# ── composer per-dimension isolation ─────────────────────────────────────────


def _composer() -> ProfileComposer:
    identity = MagicMock()
    identity.get_profile = AsyncMock(return_value={"user_id": "u", "status": "active"})
    analytics = MagicMock()
    consent = MagicMock()
    consent.get_consent = AsyncMock(return_value={"status": "granted"})
    graph = MagicMock()
    cache = MagicMock()
    resolver = MagicMock()
    resolver.get_all_identifiers = AsyncMock(return_value=[{"type": "email"}])
    return ProfileComposer(identity, analytics, consent, graph, cache, resolver)


_LIGHT = dict(
    include_timeline=False, include_graph=False,
    include_intelligence=False, include_lake=False,
)


async def test_all_healthy_is_ready():
    result = await _composer().get_full_profile("u", "t", **_LIGHT)
    assert result["readiness"]["state"] == "ready"
    assert result["readiness"]["degraded_dimensions"] == []
    assert result["core"]["status"] == "active"
    assert result["identifiers"] == [{"type": "email"}]


async def test_one_dimension_failure_degrades_not_500():
    composer = _composer()
    composer._resolver.get_all_identifiers = AsyncMock(side_effect=RuntimeError("boom"))

    result = await composer.get_full_profile("u", "t", **_LIGHT)

    # Whole profile still returned (no 500).
    assert result["profile_id"] == "u"
    # The failed dimension is surfaced, not erased.
    assert result["readiness"]["state"] == "degraded"
    degraded = {d["dimension"] for d in result["readiness"]["degraded_dimensions"]}
    assert "identifiers" in degraded
    assert result["identifiers"] == []  # typed default
    # Other dimensions are intact.
    assert result["core"]["status"] == "active"
    assert result["consent"]["status"] == "granted"


async def test_core_failure_falls_back_to_unknown():
    composer = _composer()
    composer._identity.get_profile = AsyncMock(side_effect=RuntimeError("db down"))
    result = await composer.get_full_profile("u", "t", **_LIGHT)
    assert result["core"]["status"] == "unknown"
    assert result["readiness"]["state"] == "degraded"


# ── aggregator real freshness ────────────────────────────────────────────────


async def _aged_entity(agg, eid: str, tid: str, hours_old: int):
    await agg._entities.create_entity(eid, tid, "human", "Aged Entity")
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=hours_old)).isoformat()
    # Mutate the in-memory store directly: BaseRepository.update() forces
    # updated_at = now, which would defeat an aged-record fixture.
    row = await agg._entities.find_by_id(eid)
    row["updated_at"] = old_ts
    row["created_at"] = old_ts


async def test_data_freshness_flags_stale_dimension():
    agg = Profile360Aggregator()
    await _aged_entity(agg, "ent_stale", "tenant_a", hours_old=48)
    result = await agg.data_freshness("ent_stale", "tenant_a")
    entity_dim = next(d for d in result["dimensions"] if d["dimension"] == "entity")
    assert entity_dim["stale"] is True
    assert result["stale_count"] >= 1


async def test_quality_lists_stale_dimension_and_readiness():
    agg = Profile360Aggregator()
    await _aged_entity(agg, "ent_q", "tenant_a", hours_old=48)
    result = await agg.quality("ent_q", "tenant_a")
    assert "entity" in result["stale_dimensions"]
    # Fresh dims are not flagged.
    assert "behavior" not in result["stale_dimensions"]


async def test_quality_fresh_entity_not_stale():
    agg = Profile360Aggregator()
    await agg._entities.create_entity("ent_fresh", "tenant_a", "human", "Fresh")
    result = await agg.quality("ent_fresh", "tenant_a")
    assert result["stale_dimensions"] == []
