"""Prometheus instrumentation for the semantic classify pipeline.

The alert rules (``aether_semantic_health``), the ``semantic-pipeline``
dashboard and ``tests/unit/test_semantic_observability_assets.py`` are
contracted to EXACTLY six series. These tests prove the service actually emits
each of them at the right lifecycle points — and emits NOTHING ELSE in the
``aether_semantic_*`` namespace (an alert on a series nothing emits would be
silently dead forever).
"""

from __future__ import annotations

import dataclasses

import pytest

from config.settings import settings
from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.eligibility import Eligibility
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.models import ObservationStatus
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.logger.logger import metrics

CONTRACTED_METRICS = frozenset(
    {
        "aether_semantic_observations_classified_total",
        "aether_semantic_observations_abstained_total",
        "aether_semantic_observations_quarantined_total",
        "aether_semantic_classify_latency_ms",
        "aether_semantic_review_queue_open",
        "aether_semantic_replay_jobs_active",
    }
)


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()


def _payload(event_id: str, content: str = "great support, I recommend it") -> dict:
    return {
        "source_event_id": event_id,
        "source_type": "feedback",
        "actor_ref": "user_1",
        "actor_type": "profile",
        "primary_subject_ref": "prod_1",
        "target_type": "product",
        "content": content,
        "language": "en",
    }


def _histogram(name: str, labels: dict | None = None) -> list[float]:
    """Raw observed values for one series (the collector's local backing store)."""
    return list(metrics._histograms.get(metrics._key(name, labels), []))


async def test_classified_counter_and_latency_histogram():
    tenant = "tenant_metrics_classified"
    labels = {"tenant_id": tenant}
    before = metrics.get_counter("aether_semantic_observations_classified_total", labels)
    latency_before = len(_histogram("aether_semantic_classify_latency_ms"))

    obs, _ = await SemanticIntelligenceService().classify_and_persist(
        _payload("evt_met_1"), tenant, eligibility=Eligibility.TEXT
    )
    assert obs.status is ObservationStatus.CLASSIFIED
    assert (
        metrics.get_counter("aether_semantic_observations_classified_total", labels)
        == before + 1
    )
    latency = _histogram("aether_semantic_classify_latency_ms")
    assert len(latency) == latency_before + 1
    assert latency[-1] >= 0


async def test_abstained_counter_provider_disabled(monkeypatch):
    tenant = "tenant_metrics_disabled"
    labels = {"tenant_id": tenant, "reason": "provider_disabled_by_config"}
    patched = dataclasses.replace(settings.semantic, classifier_provider="disabled")
    monkeypatch.setattr(settings, "semantic", patched)
    before = metrics.get_counter("aether_semantic_observations_abstained_total", labels)

    obs, _ = await SemanticIntelligenceService().classify_and_persist(
        _payload("evt_met_2"), tenant, eligibility=Eligibility.TEXT
    )
    assert obs.status is ObservationStatus.ABSTAINED
    assert (
        metrics.get_counter("aether_semantic_observations_abstained_total", labels)
        == before + 1
    )


async def test_abstained_counter_insufficient_content():
    tenant = "tenant_metrics_empty"
    labels = {"tenant_id": tenant, "reason": "insufficient_content"}
    before = metrics.get_counter("aether_semantic_observations_abstained_total", labels)

    obs, _ = await SemanticIntelligenceService().classify_and_persist(
        _payload("evt_met_3", content=""), tenant
    )
    assert obs.status is ObservationStatus.ABSTAINED
    assert (
        metrics.get_counter("aether_semantic_observations_abstained_total", labels)
        == before + 1
    )


async def test_quarantined_counter():
    tenant = "tenant_metrics_quarantine"
    labels = {"tenant_id": tenant, "reason": "quarantined_unregistered"}
    before = metrics.get_counter("aether_semantic_observations_quarantined_total", labels)

    obs, _ = await SemanticIntelligenceService().classify_and_persist(
        _payload("evt_met_4"), tenant, eligibility=Eligibility.QUARANTINE
    )
    assert obs.status is ObservationStatus.QUARANTINED
    assert (
        metrics.get_counter("aether_semantic_observations_quarantined_total", labels)
        == before + 1
    )


async def test_review_queue_gauge_tracks_open_counts():
    tenant = "tenant_metrics_queue"
    svc = SemanticIntelligenceService()
    await svc.enqueue_review(tenant, "ambiguous_subject", subject_ref="prod_1")
    series = _histogram("aether_semantic_review_queue_open", {"queue_type": "ambiguous_subject"})
    assert series and series[-1] == 1.0

    await svc.enqueue_review(tenant, "ambiguous_subject", subject_ref="prod_2")
    series = _histogram("aether_semantic_review_queue_open", {"queue_type": "ambiguous_subject"})
    assert series[-1] == 2.0

    # Reading the queue re-records the gauge too (fresh scrape after operator reads).
    result = await svc.review_queue(tenant)
    assert result["counts_by_queue"]["ambiguous_subject"] == 2
    series = _histogram("aether_semantic_review_queue_open", {"queue_type": "ambiguous_subject"})
    assert series[-1] == 2.0


async def test_replay_jobs_active_gauge_lifecycle():
    tenant = "tenant_metrics_replay"
    before = len(_histogram("aether_semantic_replay_jobs_active"))

    result = await SemanticIntelligenceService().create_replay_job(
        tenant, dry_run=True, filters={}
    )
    assert result["status"] == "completed"
    series = _histogram("aether_semantic_replay_jobs_active")
    # One run: gauge stepped up on start and back down on completion.
    assert len(series) == before + 2
    assert series[-2] == series[-1] + 1.0
    assert series[-1] >= 0.0


async def test_namespace_discipline_only_contracted_series(monkeypatch):
    """After driving every status branch + both gauges, the collector holds no
    aether_semantic_* series outside the six-series contract."""
    tenant = "tenant_metrics_namespace"
    svc = SemanticIntelligenceService()
    await svc.classify_and_persist(_payload("evt_ns_1"), tenant, eligibility=Eligibility.TEXT)
    await svc.classify_and_persist(_payload("evt_ns_2", content=""), tenant)
    await svc.classify_and_persist(
        _payload("evt_ns_3"), tenant, eligibility=Eligibility.QUARANTINE
    )
    patched = dataclasses.replace(settings.semantic, classifier_provider="disabled")
    monkeypatch.setattr(settings, "semantic", patched)
    await svc.classify_and_persist(_payload("evt_ns_4"), tenant, eligibility=Eligibility.TEXT)
    await svc.enqueue_review(tenant, "low_confidence", subject_ref="prod_1")
    await svc.create_replay_job(tenant, dry_run=True, filters={})

    emitted = {
        key.split("{")[0]
        for key in list(metrics._counters) + list(metrics._histograms)
        if key.startswith("aether_semantic")
    }
    assert emitted, "instrumentation emitted no aether_semantic series at all"
    assert emitted <= CONTRACTED_METRICS, (
        f"uncontracted aether_semantic series emitted: {sorted(emitted - CONTRACTED_METRICS)}"
    )
    # This test alone drives every family except nothing — all six must be live.
    assert emitted == CONTRACTED_METRICS, (
        f"contracted series never emitted: {sorted(CONTRACTED_METRICS - emitted)}"
    )
