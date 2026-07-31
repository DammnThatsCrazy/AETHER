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

import dataclasses
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.eligibility import Eligibility
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.models import ObservationStatus, StanceLabel
from services.semantic_intelligence.providers import (
    DeterministicClassifierProvider,
    ProductionModelProvider,
    ProviderResponseError,
    SemanticClassificationRequest,
    SemanticClassificationResult,
    SemanticClassifierProvider,
    provider_identity,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_provenance"

PRODUCTION_ALIASES = {"production-semantic-model", "multilingual-semantic-model"}


class StubModelProvider(SemanticClassifierProvider):
    """Available stub with a non-default identity for stamping assertions."""

    name = "stub-semantic-model@2.5.0"

    def available(self) -> bool:
        return True

    def classify(self, request: SemanticClassificationRequest) -> SemanticClassificationResult:
        base = DeterministicClassifierProvider().classify(request)
        model_id, model_version = provider_identity(self.name)
        return dataclasses.replace(
            base, provider=self.name, model_id=model_id, model_version=model_version
        )


class WiredProductionProvider(ProductionModelProvider):
    """Real ProductionModelProvider with the network seam replaced in-test."""

    def __init__(self, raw: str, served_model: str = "claude-opus-5") -> None:
        super().__init__("https://semantic-model.example.test", "key_test")
        self._raw = raw
        self._served_model = served_model

    def _request_completion(self, request: SemanticClassificationRequest) -> tuple[str, str]:
        return self._raw, self._served_model


def _model_verdict(**overrides) -> str:
    verdict = {
        "stance": "opposed",
        "intent": "cancel",
        "speech_act": "complaint",
        "topics": ["pricing"],
        "valence": -0.6,
        "confidence": 0.9,
    }
    verdict.update(overrides)
    return json.dumps(verdict)


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


# ── Phase 6: no semantic provenance lies ─────────────────────────────────────


async def test_production_mode_without_credentials_abstains_credential_waiting(monkeypatch):
    """Production mode with no credentials → ABSTAINED + credential_waiting.

    Never keyword output stamped as the production model."""
    monkeypatch.delenv("SEMANTIC_MODEL_ENDPOINT", raising=False)
    monkeypatch.delenv("SEMANTIC_MODEL_API_KEY", raising=False)
    monkeypatch.setattr(
        service_mod,
        "settings",
        SimpleNamespace(
            consent_authority=SimpleNamespace(authoritative_consent_enforcement_enabled=False),
            semantic=SimpleNamespace(
                classifier_provider="production", shadow_provider="", canary_tenants=[]
            ),
        ),
    )
    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(
        _payload("evt_prov_nocreds"), TENANT, eligibility=Eligibility.TEXT
    )
    assert obs.status is ObservationStatus.ABSTAINED
    assert obs.abstention_reason == "credential_waiting"
    assert sentiments == []
    # The abstained row never claims a production classification.
    assert obs.model_id not in PRODUCTION_ALIASES
    rows = await get_store().list_semantic(TENANT)
    assert [r.status for r in rows] == [ObservationStatus.ABSTAINED]
    assert all(r.model_id not in PRODUCTION_ALIASES for r in rows)


def test_keyword_output_never_carries_production_model_id():
    """Engine path: production-stamped output can only come from provider.classify().

    The payload's keywords scream 'supportive'; the model verdict says
    'opposed'. If the keyword classifier were still driving the production
    path, the production-stamped row would read supportive."""
    payload = _payload("evt_prov_keyword_vs_model")
    det_obs, _ = classify_event(payload, TENANT, provider=DeterministicClassifierProvider())
    assert det_obs.stance is StanceLabel.SUPPORTIVE
    assert det_obs.model_id == "deterministic-semantic-classifier"
    assert det_obs.model_id not in PRODUCTION_ALIASES

    prod = WiredProductionProvider(_model_verdict())
    obs, sentiments = classify_event(payload, TENANT, provider=prod)
    # Labels are the model's own verdict, not the keyword derivation …
    assert obs.stance is StanceLabel.OPPOSED
    assert obs.topics == ["pricing"]
    assert obs.classification_confidence == 0.9
    # … and provenance is the ACTUAL model identity, never a keyword stamp.
    assert obs.model_id == "claude-opus-5"
    assert obs.model_version == "claude-opus-5"
    assert sentiments and sentiments[0].model_id == "claude-opus-5"
    assert sentiments[0].valence == -0.6


async def test_malformed_provider_response_rejected_nothing_persisted(monkeypatch):
    """Malformed/contract-violating model output is REJECTED wholesale."""
    malformed = [
        '{"stance": "supportive", ',  # truncated JSON
        _model_verdict(stance="sarcastic"),  # unknown enum label
        _model_verdict(confidence=3.0),  # confidence out of range
        json.dumps({"stance": "supportive"}),  # missing required fields
    ]
    svc = SemanticIntelligenceService()
    for i, raw in enumerate(malformed):
        provider = WiredProductionProvider(raw)
        monkeypatch.setattr(
            service_mod, "get_classifier_provider", lambda settings, tenant_id=None, p=provider: p
        )
        with pytest.raises(ProviderResponseError):
            await svc.classify_and_persist(
                _payload(f"evt_prov_malformed_{i}"), TENANT, eligibility=Eligibility.TEXT
            )
    # Never partially ingested: nothing was persisted for any rejected response.
    assert await get_store().list_semantic(TENANT) == []
    assert await get_store().list_sentiment(TENANT) == []


async def test_transport_failure_abstains_first_class(monkeypatch):
    """A network failure after bounded retries abstains — never keyword output."""

    class UnreachableProvider(ProductionModelProvider):
        def __init__(self) -> None:
            super().__init__("https://semantic-model.example.test", "key_test")

        def _request_completion(self, request):
            raise anthropic.APIConnectionError(
                request=httpx.Request("POST", "https://semantic-model.example.test")
            )

    provider = UnreachableProvider()
    monkeypatch.setattr(
        service_mod, "get_classifier_provider", lambda settings, tenant_id=None: provider
    )
    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(
        _payload("evt_prov_unreachable"), TENANT, eligibility=Eligibility.TEXT
    )
    assert obs.status is ObservationStatus.ABSTAINED
    assert obs.abstention_reason == "provider_unavailable:APIConnectionError"
    assert sentiments == []
    # The abstained row records the resolved provider identity + abstention,
    # with zero confidence — it never claims a classification.
    assert obs.model_id == "production-semantic-model"
    assert obs.classification_confidence == 0.0
