"""Profile360 slot freshness from per-tenant source watermarks."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.freshness import source_watermarks as wm  # noqa: E402
from shared.freshness.slot_freshness import (  # noqa: E402
    OVERRIDES_ENV,
    evaluate_slot_freshness,
    slot_freshness_policies,
)
from shared.intelligence_projections.frame_runtime import _watermark_freshness  # noqa: E402
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    PRODUCT_360_SURFACE_DEFINITIONS,
)
from shared.store import InMemoryStore  # noqa: E402

PROFILE = PRODUCT_360_SURFACE_DEFINITIONS["profile360"]
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_store():
    wm.reset_for_tests(InMemoryStore("test_source_watermarks"))
    yield
    wm.reset_for_tests(None)


def test_profile360_declares_tiered_thresholds():
    policies = slot_freshness_policies(PROFILE)
    expected = {
        "session_history": 3600, "communications": 3600,
        "risk_summary": 21600, "risk_context": 21600,
        "relationships": 86400, "relationship_context": 86400,
        "agent_delegations": 86400, "value_summary": 86400,
        "economic_value_context": 86400, "location_temporal": 604800,
    }
    assert {k: v["maxAgeSeconds"] for k, v in policies.items()} == expected


def test_override_env_changes_one_slot(monkeypatch):
    monkeypatch.setenv(OVERRIDES_ENV, '{"profile360": {"risk_summary": 60, "bogus": -1}}')
    policies = slot_freshness_policies(PROFILE)
    assert policies["risk_summary"]["maxAgeSeconds"] == 60
    assert policies["risk_context"]["maxAgeSeconds"] == 21600


def test_invalid_override_env_is_ignored(monkeypatch):
    monkeypatch.setenv(OVERRIDES_ENV, "not json")
    assert slot_freshness_policies(PROFILE)["risk_summary"]["maxAgeSeconds"] == 21600


def test_verdicts_fresh_stale_and_unknown():
    policies = slot_freshness_policies(PROFILE)
    watermarks = {
        "risk_outputs": (NOW - timedelta(hours=1)).isoformat(),
        "analytics_events": (NOW - timedelta(hours=2)).isoformat(),
        "economic_facts": None,
    }
    verdicts = evaluate_slot_freshness(
        policies, ["risk_summary", "session_history", "value_summary", "identity_spine"],
        watermarks, NOW.isoformat(),
    )
    assert verdicts["risk_summary"].state == "fresh"
    assert verdicts["risk_summary"].ageSeconds == 3600
    assert verdicts["session_history"].state == "stale"
    assert verdicts["value_summary"].state == "unknown"
    assert verdicts["value_summary"].sourceAsOf is None
    assert "identity_spine" not in verdicts


@pytest.mark.asyncio
async def test_watermark_is_monotonic_and_tenant_scoped():
    later, earlier = NOW, NOW - timedelta(hours=3)
    await wm.advance_source_watermark("t1", "risk_outputs", at=later, force=True)
    await wm.advance_source_watermark("t1", "risk_outputs", at=earlier, force=True)
    read = await wm.read_source_watermarks("t1", ["risk_outputs"])
    assert read["risk_outputs"] == later.isoformat()
    assert (await wm.read_source_watermarks("t2", ["risk_outputs"]))["risk_outputs"] is None


@pytest.mark.asyncio
async def test_unwatermarked_authority_is_ignored():
    await wm.advance_source_watermark("t1", "identity", force=True)
    assert (await wm.read_source_watermarks("t1", ["identity"]))["identity"] is None


@pytest.mark.asyncio
async def test_advance_is_throttled_per_process():
    await wm.advance_source_watermark("t1", "risk_outputs", at=NOW - timedelta(hours=2))
    await wm.advance_source_watermark("t1", "risk_outputs", at=NOW)
    read = await wm.read_source_watermarks("t1", ["risk_outputs"])
    assert read["risk_outputs"] == (NOW - timedelta(hours=2)).isoformat()


@pytest.mark.asyncio
async def test_advance_failure_never_raises():
    class Broken(InMemoryStore):
        async def atomic_update(self, *args, **kwargs):
            raise RuntimeError("store down")

    wm.reset_for_tests(Broken("broken"))
    await wm.advance_source_watermark("t1", "risk_outputs", force=True)


@pytest.mark.asyncio
async def test_concurrent_advances_keep_latest():
    instants = [NOW - timedelta(minutes=i) for i in range(20)]
    await asyncio.gather(*[
        wm.advance_source_watermark("t1", "economic_facts", at=at, force=True) for at in instants
    ])
    read = await wm.read_source_watermarks("t1", ["economic_facts"])
    assert read["economic_facts"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_frame_runtime_freshness_only_for_policy_slots():
    now = datetime.now(timezone.utc)
    await wm.advance_source_watermark("t1", "risk_outputs", at=now, force=True)
    verdicts = await _watermark_freshness(PROFILE, ["risk_summary", "identity_spine", "communications"], "t1")
    assert set(verdicts) == {"risk_summary", "communications"}
    assert verdicts["risk_summary"].state == "fresh"
    assert verdicts["communications"].state == "unknown"
    assert await _watermark_freshness(PROFILE, ["identity_spine"], "t1") is None


def test_validator_mirrors_runtime_authorities():
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "ipv", root / "scripts/lib/intelligence_projection_validation.py",
    )
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.path.insert(0, str(root / "scripts"))
    sys.modules["ipv"] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        sys.modules.pop("ipv", None)
        sys.path.remove(str(root / "scripts"))
    assert module.WATERMARKED_AUTHORITIES == wm.WATERMARKED_AUTHORITIES


# ---------------------------------------------------------------- writers

WRITERS = [
    ("repositories.repos", "AnalyticsRepository", "record_event", "analytics_events"),
    ("repositories.repos", "AnalyticsRepository", "record_processed_event", "analytics_events"),
    ("repositories.repos", "DelegationRepository", "grant", "agent_access"),
    ("repositories.repos", "DelegationRepository", "revoke", "agent_access"),
    ("journeys.comms.repository", "CommsFactsRepository", "upsert", "communication_facts"),
    ("repositories.graph_mutation_ledger", "GraphMutationLedgerRepository", "append", "relationship_facts"),
    ("graph.geo.location_facts", "LocationFactRepository", "record", "geo_observations"),
    ("journeys.measurement.repositories.conversion_repo", "ConversionRepository", "upsert", "economic_facts"),
    ("intelligence.risk360.store", "RiskAssessmentRepository", "upsert_scoped", "risk_outputs"),
    ("intelligence.risk360.store", "RiskAssessmentRepository", "update_scoped", "risk_outputs"),
]


@pytest.mark.parametrize("module_name,cls_name,method,authority", WRITERS)
def test_every_owning_writer_advances_its_watermark(module_name, cls_name, method, authority):
    import importlib

    fn = getattr(getattr(importlib.import_module(module_name), cls_name), method)
    assert hasattr(fn, "__wrapped__"), f"{cls_name}.{method} does not advance {authority}"


def test_every_watermarked_authority_has_a_writer():
    assert {w[3] for w in WRITERS} == set(wm.WATERMARKED_AUTHORITIES)


@pytest.mark.asyncio
async def test_decorator_uses_result_tenant_and_skips_failures():
    @wm.advances_watermark("economic_facts")
    async def write(row):
        return row

    @wm.advances_watermark("economic_facts")
    async def broken(row):
        raise ValueError("write failed")

    with pytest.raises(ValueError):
        await broken({"tenant_id": "t9"})
    assert (await wm.read_source_watermarks("t9", ["economic_facts"]))["economic_facts"] is None
    await write({"tenant_id": "t9"})
    assert (await wm.read_source_watermarks("t9", ["economic_facts"]))["economic_facts"] is not None


def test_decorator_rejects_unknown_authority():
    with pytest.raises(ValueError):
        wm.advances_watermark("identity")


@pytest.mark.asyncio
async def test_risk_assessment_write_advances_risk_outputs():
    from intelligence.risk360.store import RiskAssessmentRepository

    await RiskAssessmentRepository().upsert_scoped("t-risk", "a1", {"subject_id": "e1"})
    read = await wm.read_source_watermarks("t-risk", ["risk_outputs"])
    assert read["risk_outputs"] is not None


@pytest.mark.asyncio
async def test_analytics_event_write_advances_analytics_events():
    from repositories.repos import AnalyticsRepository
    from shared.cache.cache import CacheClient

    await AnalyticsRepository(CacheClient()).record_event("ev1", {"tenant_id": "t-an", "event_id": "ev1"})
    read = await wm.read_source_watermarks("t-an", ["analytics_events"])
    assert read["analytics_events"] is not None
