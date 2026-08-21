"""Shadow-mode candidate evaluation seam (``semantic.shadow_provider``).

When the flag is set, classify_and_persist ALSO runs the candidate provider's
classification in-process, compares stance/intent/valence-sign, and records
disagreements to the ``semantic_shadow_divergences`` JSONB fact table. The
shadow output must NEVER affect the persisted primary observation.

Honest limit (mirrors the service docstring): with only the deterministic and
fail-closed disabled providers available locally, a real model cannot diverge
here — the divergence path is exercised via a stub candidate below, plus the
real fail-closed candidate (production mode without credentials), whose
abstention IS an honest local divergence.
"""

from __future__ import annotations

import dataclasses

import pytest

from config.settings import settings
from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.models import IntentLabel, ObservationStatus, StanceLabel
from services.semantic_intelligence.providers import (
    DeterministicClassifierProvider,
    DisabledProvider,
    SemanticClassificationRequest,
    SemanticClassificationResult,
    SemanticClassifierProvider,
    get_shadow_provider,
    provider_identity,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_shadow"
_DIVERGENCE_TABLE = "semantic_shadow_divergences"


class StubCandidateProvider(SemanticClassifierProvider):
    name = "stub-candidate-model@3.0.0"

    def available(self) -> bool:
        return True

    async def classify(self, request: SemanticClassificationRequest) -> SemanticClassificationResult:
        # Deterministic labels re-stamped with the stub's own identity — the
        # divergence itself is injected per-test where needed.
        base = await DeterministicClassifierProvider().classify(request)
        model_id, model_version = provider_identity(self.name)
        return dataclasses.replace(
            base, provider=self.name, model_id=model_id, model_version=model_version
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


def _payload(event_id: str = "evt_shadow_1") -> dict:
    return {
        "source_event_id": event_id,
        "source_type": "feedback",
        "actor_ref": "user_1",
        "actor_type": "profile",
        "primary_subject_ref": "prod_1",
        "target_type": "product",
        "content": "I support this product and recommend it",
        "language": "en",
    }


def _divergence_rows(tenant_id: str) -> list[dict]:
    return [
        row
        for row in _IN_MEMORY_STORES.get(_DIVERGENCE_TABLE, {}).values()
        if row.get("tenant_id") == tenant_id
    ]


def test_shadow_provider_resolution(monkeypatch):
    assert get_shadow_provider(settings) is None  # default '' = off
    patched = dataclasses.replace(settings.semantic, shadow_provider="deterministic")
    monkeypatch.setattr(settings, "semantic", patched)
    assert isinstance(get_shadow_provider(settings), DeterministicClassifierProvider)


async def test_shadow_off_by_default_records_nothing():
    obs, _ = await SemanticIntelligenceService().classify_and_persist(_payload(), TENANT)
    assert obs.status is ObservationStatus.CLASSIFIED
    assert _divergence_rows(TENANT) == []


async def test_agreeing_candidate_records_no_divergence(monkeypatch):
    """A deterministic candidate agrees with the deterministic primary — quiet."""
    patched = dataclasses.replace(settings.semantic, shadow_provider="deterministic")
    monkeypatch.setattr(settings, "semantic", patched)
    obs, _ = await SemanticIntelligenceService().classify_and_persist(_payload(), TENANT)
    assert obs.status is ObservationStatus.CLASSIFIED
    assert _divergence_rows(TENANT) == []


async def test_stub_candidate_divergence_recorded_and_primary_untouched(monkeypatch):
    stub = StubCandidateProvider()
    monkeypatch.setattr(service_mod, "get_shadow_provider", lambda _settings: stub)

    # Divergence requires a candidate that actually disagrees; locally only the
    # deterministic engine exists, so flip the stub candidate's labels in-test.
    real_classify = classify_event

    async def _divergent_classify(payload, tenant_id, provider=None):
        obs, sentiments = await real_classify(payload, tenant_id, provider=provider)
        if isinstance(provider, StubCandidateProvider):
            obs = obs.model_copy(
                update={"stance": StanceLabel.OPPOSED, "intent": IntentLabel.CANCEL}
            )
        return obs, sentiments

    monkeypatch.setattr(service_mod, "classify_event", _divergent_classify)

    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(_payload(), TENANT)

    # Primary is untouched: deterministic labels, deterministic provenance, and
    # exactly one persisted observation (the candidate's output never lands).
    assert obs.status is ObservationStatus.CLASSIFIED
    assert obs.stance is StanceLabel.SUPPORTIVE
    assert obs.model_id == "deterministic-semantic-classifier"
    rows = await get_store().list_semantic(TENANT)
    assert [r.observation_id for r in rows] == [obs.observation_id]

    divergences = _divergence_rows(TENANT)
    assert len(divergences) == 1
    data = divergences[0]["data"]
    assert data["shadow_model"] == "stub-candidate-model@3.0.0"
    assert data["primary_model"] == "deterministic-semantic-classifier@1.0.0"
    assert data["primary_observation_id"] == obs.observation_id
    assert data["primary"]["stance"] == "supportive"
    assert data["candidate"]["stance"] == "opposed"
    assert data["agreement"] == {"stance": False, "intent": False, "valence": True}

    # Redelivery of the same event dedupes on the shadow idempotency key.
    await svc.classify_and_persist(_payload(), TENANT)
    assert len(_divergence_rows(TENANT)) == 1


async def test_failclosed_candidate_abstains_and_diverges(monkeypatch):
    """Shadow=production without credentials resolves the fail-closed Disabled
    candidate: its abstention is compared (full disagreement), and it must never
    fabricate a shadow classification."""
    monkeypatch.delenv("SEMANTIC_MODEL_ENDPOINT", raising=False)
    monkeypatch.delenv("SEMANTIC_MODEL_API_KEY", raising=False)
    patched = dataclasses.replace(settings.semantic, shadow_provider="production")
    monkeypatch.setattr(settings, "semantic", patched)
    assert isinstance(get_shadow_provider(settings), DisabledProvider)

    obs, _ = await SemanticIntelligenceService().classify_and_persist(_payload(), TENANT)
    assert obs.status is ObservationStatus.CLASSIFIED  # primary unaffected

    divergences = _divergence_rows(TENANT)
    assert len(divergences) == 1
    data = divergences[0]["data"]
    assert data["candidate"]["status"] == "abstained"
    assert data["candidate"]["stance"] is None
    assert data["candidate"]["abstention_reason"] == "credential_waiting"
    assert data["agreement"]["stance"] is False


async def test_shadow_failure_never_breaks_the_write_path(monkeypatch):
    """A crashing shadow comparison is swallowed — the primary write survives."""
    stub = StubCandidateProvider()
    monkeypatch.setattr(service_mod, "get_shadow_provider", lambda _settings: stub)

    real_classify = classify_event

    async def _exploding_classify(payload, tenant_id, provider=None):
        if isinstance(provider, StubCandidateProvider):
            raise RuntimeError("candidate exploded")
        return await real_classify(payload, tenant_id, provider=provider)

    monkeypatch.setattr(service_mod, "classify_event", _exploding_classify)

    obs, _ = await SemanticIntelligenceService().classify_and_persist(_payload(), TENANT)
    assert obs.status is ObservationStatus.CLASSIFIED
    rows = await get_store().list_semantic(TENANT)
    assert len(rows) == 1
    assert _divergence_rows(TENANT) == []
