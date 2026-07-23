"""Canary routing (``semantic.canary_tenants``) for the classifier provider.

A tenant on the canary list resolves the candidate (production) provider —
fail-closed to Disabled without credentials, exactly like any production
request. Every other tenant keeps the configured primary. The canary list must
never weaken fail-closed semantics: a credential-less canary ABSTAINS, it is
never silently degraded to the keyword classifier.
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
from services.semantic_intelligence.providers import (
    DeterministicClassifierProvider,
    DisabledProvider,
    ProductionModelProvider,
    get_classifier_provider,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

CANARY_TENANT = "tenant_canary"
OTHER_TENANT = "tenant_regular"


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


@pytest.fixture()
def canary_config(monkeypatch):
    patched = dataclasses.replace(settings.semantic, canary_tenants=[CANARY_TENANT])
    monkeypatch.setattr(settings, "semantic", patched)
    return patched


@pytest.fixture()
def candidate_creds(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MODEL_ENDPOINT", "https://stub-model.example.test")
    monkeypatch.setenv("SEMANTIC_MODEL_API_KEY", "stub-key")


@pytest.fixture()
def no_candidate_creds(monkeypatch):
    monkeypatch.delenv("SEMANTIC_MODEL_ENDPOINT", raising=False)
    monkeypatch.delenv("SEMANTIC_MODEL_API_KEY", raising=False)


def _payload(event_id: str) -> dict:
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


def test_canary_tenant_routes_to_candidate(canary_config, candidate_creds):
    provider = get_classifier_provider(settings, CANARY_TENANT)
    assert isinstance(provider, ProductionModelProvider)
    assert provider.name == "production-semantic-model@1.0.0"
    assert provider.available() is True


def test_non_canary_and_tenantless_calls_keep_primary(canary_config, candidate_creds):
    assert isinstance(
        get_classifier_provider(settings, OTHER_TENANT), DeterministicClassifierProvider
    )
    # Existing tenant-less call sites keep the primary provider unchanged.
    assert isinstance(get_classifier_provider(settings), DeterministicClassifierProvider)


def test_empty_canary_list_changes_nothing(candidate_creds):
    assert settings.semantic.canary_tenants == []
    assert isinstance(
        get_classifier_provider(settings, CANARY_TENANT), DeterministicClassifierProvider
    )


def test_canary_without_creds_fails_closed(canary_config, no_candidate_creds):
    provider = get_classifier_provider(settings, CANARY_TENANT)
    assert isinstance(provider, DisabledProvider)
    assert provider.available() is False
    assert provider.abstention_reason() == "provider_disabled_missing_credentials"


async def test_canary_without_creds_abstains_end_to_end(canary_config, no_candidate_creds):
    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(
        _payload("evt_canary_nocreds"), CANARY_TENANT, eligibility=Eligibility.TEXT
    )
    assert obs.status is ObservationStatus.ABSTAINED
    assert obs.abstention_reason == "provider_disabled_missing_credentials"
    assert sentiments == []

    # A non-canary tenant is untouched by the canary's failure mode.
    other, other_sentiments = await svc.classify_and_persist(
        _payload("evt_regular_nocreds"), OTHER_TENANT, eligibility=Eligibility.TEXT
    )
    assert other.status is ObservationStatus.CLASSIFIED
    assert other_sentiments and other_sentiments[0].valence > 0


async def test_canary_with_creds_stamps_candidate_provenance(canary_config, candidate_creds):
    """The canary's persisted observation carries the CANDIDATE model identity."""
    obs, sentiments = await SemanticIntelligenceService().classify_and_persist(
        _payload("evt_canary_creds"), CANARY_TENANT, eligibility=Eligibility.TEXT
    )
    assert obs.status is ObservationStatus.CLASSIFIED
    assert obs.model_id == "production-semantic-model"
    assert obs.model_version == "1.0.0"
    assert sentiments and sentiments[0].model_id == "production-semantic-model"
