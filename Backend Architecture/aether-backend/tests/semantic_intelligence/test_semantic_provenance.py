"""Model provenance — observations are stamped from the RESOLVED provider.

``classify_event`` historically emitted the static ``models.py`` defaults no
matter which provider produced the classification, so a production provider's
output would still read ``deterministic-semantic-classifier@1.0.0``. These
tests pin the threading: the resolved provider's ``id@version`` name lands on
the semantic AND sentiment observations, the deterministic provider stays
byte-identical to the defaults (no idempotency break for existing data), and a
new provider version yields a NEW observation identity (``model_version``
participates in ``stable_hash``/``idempotency_key`` — intended).
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.eligibility import Eligibility
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.models import ObservationStatus
from services.semantic_intelligence.providers import (
    DeterministicClassifierProvider,
    SemanticClassifierProvider,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_provenance"


class StubModelProvider(SemanticClassifierProvider):
    """Available stub with a non-default identity for stamping assertions."""

    name = "stub-semantic-model@2.5.0"

    def available(self) -> bool:
        return True


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


def _payload(event_id: str = "evt_prov_1") -> dict:
    return {
        "source_event_id": event_id,
        "source_type": "feedback",
        "actor_ref": "user_1",
        "actor_type": "profile",
        "primary_subject_ref": "prod_1",
        "target_type": "product",
        "content": "great support, I recommend it",
        "language": "en",
    }


def test_default_call_keeps_static_defaults():
    """No provider argument → existing call sites keep the models.py identity."""
    obs, sentiments = classify_event(_payload(), TENANT)
    assert obs.model_id == "deterministic-semantic-classifier"
    assert obs.model_version == "1.0.0"
    assert sentiments and sentiments[0].model_id == "deterministic-sentiment-classifier"
    assert sentiments[0].model_version == "1.0.0"


def test_deterministic_provider_stamps_its_real_name():
    obs, sentiments = classify_event(
        _payload(), TENANT, provider=DeterministicClassifierProvider()
    )
    assert obs.model_id == "deterministic-semantic-classifier"
    assert obs.model_version == "1.0.0"
    assert sentiments and sentiments[0].model_id == "deterministic-semantic-classifier"
    assert sentiments[0].model_version == "1.0.0"


def test_deterministic_provider_preserves_observation_identity():
    """Explicitly-passed deterministic provider must not shift idempotency —
    model_version stays 1.0.0, so pre-existing observations dedupe as before."""
    baseline, _ = classify_event(_payload(), TENANT)
    stamped, _ = classify_event(_payload(), TENANT, provider=DeterministicClassifierProvider())
    assert stamped.stable_hash == baseline.stable_hash
    assert stamped.idempotency_key == baseline.idempotency_key


def test_provider_version_changes_observation_identity():
    """A new provider version is a new observation identity (never deduped away)."""

    class StubV1(StubModelProvider):
        name = "stub-semantic-model@1.0.0"

    class StubV2(StubModelProvider):
        name = "stub-semantic-model@2.0.0"

    v1, _ = classify_event(_payload(), TENANT, provider=StubV1())
    v2, _ = classify_event(_payload(), TENANT, provider=StubV2())
    assert v1.model_version == "1.0.0" and v2.model_version == "2.0.0"
    assert v1.stable_hash != v2.stable_hash
    assert v1.idempotency_key != v2.idempotency_key


async def test_service_persists_resolved_provider_identity(monkeypatch):
    """classify_and_persist stamps the provider IT resolved onto the stored rows."""
    monkeypatch.setattr(
        service_mod, "get_classifier_provider", lambda settings, tenant_id=None: StubModelProvider()
    )
    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(
        _payload("evt_prov_stub"), TENANT, eligibility=Eligibility.TEXT
    )
    assert obs.status is ObservationStatus.CLASSIFIED
    assert obs.model_id == "stub-semantic-model"
    assert obs.model_version == "2.5.0"
    assert sentiments and sentiments[0].model_id == "stub-semantic-model"
    assert sentiments[0].model_version == "2.5.0"

    # The persisted rows carry the stub identity too (not only the return value).
    rows = await get_store().list_semantic(TENANT)
    assert [(r.model_id, r.model_version) for r in rows] == [("stub-semantic-model", "2.5.0")]
    sent_rows = await get_store().list_sentiment(TENANT)
    assert [(r.model_id, r.model_version) for r in sent_rows] == [("stub-semantic-model", "2.5.0")]


async def test_service_structured_path_keeps_deterministic_identity():
    """Non-text (structured/route) calls never resolve a text provider — the
    deterministic defaults remain the recorded provenance."""
    svc = SemanticIntelligenceService()
    obs, _ = await svc.classify_and_persist(_payload("evt_prov_structured"), TENANT)
    assert obs.status is ObservationStatus.CLASSIFIED
    assert obs.model_id == "deterministic-semantic-classifier"
    assert obs.model_version == "1.0.0"
