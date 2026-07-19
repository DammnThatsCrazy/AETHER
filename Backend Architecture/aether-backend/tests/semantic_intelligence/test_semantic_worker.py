"""Phase A2 — semantic worker on validated ingestion, eligibility, consent, provider.

Proves classification now flows automatically from SDK_EVENTS_VALIDATED (not only
a manual API call), routes by eligibility (skip/structured/text/quarantine/abstain),
fails closed on consent, and never degrades a production text request to keywords.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.consumer import SemanticEventConsumer
from services.semantic_intelligence.eligibility import Eligibility, classify_eligibility
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.models import ObservationStatus
from services.semantic_intelligence.providers import (
    DeterministicClassifierProvider,
    DisabledProvider,
    get_classifier_provider,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.events.events import Event, Topic

TENANT = "tenant_worker"


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


def _event(event_type: str, **props) -> Event:
    return Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        payload={
            "event_id": f"evt_{event_type}",
            "event_type": event_type,
            "user_id": "user_1",
            "properties": props,
        },
    )


# ── eligibility ──────────────────────────────────────────────────────────────


def test_eligibility_routing():
    assert classify_eligibility("heartbeat", {})[0] is Eligibility.SKIP
    assert classify_eligibility("page", {})[0] is Eligibility.STRUCTURED
    assert classify_eligibility("payment_completed", {})[0] is Eligibility.STRUCTURED
    assert classify_eligibility("feedback_submitted", {"content": "hi"})[0] is Eligibility.TEXT
    assert classify_eligibility("feedback_submitted", {})[0] is Eligibility.ABSTAIN
    assert classify_eligibility("totally_made_up_event", {})[0] is Eligibility.QUARANTINE


# ── worker ───────────────────────────────────────────────────────────────────


async def test_worker_classifies_from_validated_event():
    await SemanticEventConsumer().on_validated_event(
        _event("feedback_submitted", content="great support, I recommend it", product_id="prod_1")
    )
    rows = await get_store().list_semantic(TENANT)
    assert len(rows) == 1
    assert rows[0].status is ObservationStatus.CLASSIFIED
    assert rows[0].primary_subject_ref == "prod_1"


async def test_worker_skips_telemetry():
    await SemanticEventConsumer().on_validated_event(_event("heartbeat"))
    assert await get_store().list_semantic(TENANT) == []


async def test_worker_quarantines_unregistered_event():
    await SemanticEventConsumer().on_validated_event(_event("not_a_real_event"))
    rows = await get_store().list_semantic(TENANT)
    assert len(rows) == 1
    assert rows[0].status is ObservationStatus.QUARANTINED


async def test_worker_requires_tenant():
    ev = Event(topic=Topic.SDK_EVENTS_VALIDATED, tenant_id="", payload={"event_type": "page"})
    await SemanticEventConsumer().on_validated_event(ev)  # no raise, no persist
    assert await get_store().list_semantic("") == []


# ── consent (fail closed) ────────────────────────────────────────────────────


async def test_consent_denied_yields_restricted_observation(monkeypatch):
    monkeypatch.setattr(
        service_mod,
        "settings",
        SimpleNamespace(
            consent_authority=SimpleNamespace(authoritative_consent_enforcement_enabled=True)
        ),
    )

    async def _deny(*_a, **_k):
        return (False, "consent_revoked")

    monkeypatch.setattr(service_mod, "evaluate_consent", _deny)

    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(
        {"source_event_id": "e", "source_type": "feedback", "actor_ref": "u1",
         "primary_subject_ref": "prod_1", "content": "love it"},
        TENANT,
        eligibility=Eligibility.TEXT,
    )
    assert obs.status is ObservationStatus.CONSENT_RESTRICTED
    assert obs.abstention_reason == "consent_revoked"
    assert sentiments == []


# ── provider (fail closed) ───────────────────────────────────────────────────


def test_provider_factory_fails_closed_without_credentials():
    det = get_classifier_provider(
        SimpleNamespace(semantic=SimpleNamespace(classifier_provider="deterministic"))
    )
    assert isinstance(det, DeterministicClassifierProvider) and det.available()

    prod = get_classifier_provider(
        SimpleNamespace(semantic=SimpleNamespace(classifier_provider="production"))
    )
    assert isinstance(prod, DisabledProvider) and not prod.available()


async def test_text_event_abstains_when_provider_disabled(monkeypatch):
    monkeypatch.setattr(
        service_mod,
        "settings",
        SimpleNamespace(
            consent_authority=SimpleNamespace(authoritative_consent_enforcement_enabled=False),
            semantic=SimpleNamespace(classifier_provider="production"),
        ),
    )
    svc = SemanticIntelligenceService()
    obs, _ = await svc.classify_and_persist(
        {"source_event_id": "e", "source_type": "feedback", "actor_ref": "u1",
         "primary_subject_ref": "prod_1", "content": "love it"},
        TENANT,
        eligibility=Eligibility.TEXT,
    )
    assert obs.status is ObservationStatus.ABSTAINED
    assert "provider_disabled" in (obs.abstention_reason or "")
