"""Semantic pipeline chaos — model loss, dry-run replay, and restart recovery.

Drives the REAL semantic classify / replay / store code paths credentiallessly
against the in-memory fallbacks (``get_pool() is None``). NO live model
endpoint, database, or bus.

Scenarios covered here:
  * model unavailable   -> the classify path resolves the FAIL-CLOSED
                           ``DisabledProvider`` (production mode, no credentials)
                           and ABSTAINS — it never fabricates a classification
                           or a sentiment row
  * replay dry-run      -> counts the Bronze scope and writes ZERO semantic
                           facts (job progress is the only durable record)
  * durable round-trip  -> a FRESH ``DurableSemanticSentimentStore`` instance
                           after a simulated process restart still reads what
                           was persisted, and re-delivery stays idempotent
                           (same reset + re-read pattern as
                           tests/integration/semantic/)
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest


def _feedback(tenant: str) -> dict[str, Any]:
    return {
        "source_event_id": f"evt-chaos-{tenant}",
        "source_type": "feedback",
        "actor_ref": f"user-{tenant}",
        "actor_type": "profile",
        "primary_subject_ref": f"product-{tenant}",
        "target_type": "product",
        "content": "excellent support and great quality, I recommend it",
        "language": "en",
    }


@pytest.fixture()
def model_unavailable(monkeypatch):
    """Configure the production classifier with NO credentials.

    ``get_classifier_provider`` must fail closed to ``DisabledProvider`` — never
    silently degrade a production request to the keyword fallback.
    """
    from config.settings import settings

    monkeypatch.delenv("SEMANTIC_MODEL_ENDPOINT", raising=False)
    monkeypatch.delenv("SEMANTIC_MODEL_API_KEY", raising=False)
    patched = dataclasses.replace(settings.semantic, classifier_provider="production")
    monkeypatch.setattr(settings, "semantic", patched)
    return patched


@pytest.fixture()
def durable_semantic_store():
    """Swap the engine store singleton for the durable store, restoring after."""
    from services.semantic_intelligence.engine import get_store, set_store
    from services.semantic_intelligence.store import DurableSemanticSentimentStore

    original = get_store()
    set_store(DurableSemanticSentimentStore())
    yield
    set_store(original)


# ── model unavailable ─────────────────────────────────────────────────────────
async def test_model_unavailable_classify_abstains_never_fabricates(tenant, model_unavailable):
    """Production model configured but credential-less: the text classify path
    must record an ABSTAINED observation (reason: missing credentials) and must
    not fabricate an inferred classification or any sentiment row."""
    from config.settings import settings
    from services.semantic_intelligence.eligibility import Eligibility
    from services.semantic_intelligence.models import ObservationStatus
    from services.semantic_intelligence.providers import DisabledProvider, get_classifier_provider
    from services.semantic_intelligence.service import SemanticIntelligenceService

    provider = get_classifier_provider(settings)
    assert isinstance(provider, DisabledProvider)
    assert provider.available() is False

    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(
        _feedback(tenant), tenant, eligibility=Eligibility.TEXT
    )
    assert obs.status == ObservationStatus.ABSTAINED
    assert obs.abstention_reason == "provider_disabled_missing_credentials"
    assert sentiments == []
    # Content-free abstention: zero inferred semantics, zero confidence.
    assert obs.classification_confidence == 0.0
    assert obs.topics == [] and obs.claims == [] and obs.narrative_frames == []
    stored_sentiment, _ = await svc.list_sentiment(tenant, limit=100)
    assert stored_sentiment == []
    # The abstention itself IS durably recorded (the pipeline saw the event).
    rows, _ = await svc.list_observations(tenant, limit=100)
    assert [r.observation_id for r in rows] == [obs.observation_id]


# ── replay dry-run ────────────────────────────────────────────────────────────
async def test_replay_dry_run_counts_scope_and_writes_nothing(tenant):
    """A dry-run replay over durable Bronze reports the would-replay scope but
    persists NO semantic facts — only the job's own progress record."""
    from repositories.repos import _IN_MEMORY_STORES
    from services.semantic_intelligence.service import SemanticIntelligenceService

    bronze = _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})
    for i in range(3):
        event_id = f"{tenant}-evt-{i}"
        bronze[event_id] = {
            "tenant_id": tenant,
            "event_id": event_id,
            "event_type": "feedback_submitted",
            "event_family": "engagement",
            "received_at": f"2026-07-0{i + 1}T00:00:00+00:00",
            "payload": {**_feedback(tenant), "source_event_id": event_id},
        }

    svc = SemanticIntelligenceService()
    result = await svc.create_replay_job(tenant, dry_run=True, filters={})
    assert result["dry_run"] is True
    assert result["status"] == "completed"
    assert result["scanned"] == 3
    assert result["replayed"] == 3  # would-replay count only — nothing executed

    # Zero writes: no semantic/sentiment facts for this tenant, Bronze untouched.
    rows, _ = await svc.list_observations(tenant, limit=100)
    assert rows == []
    silver = _IN_MEMORY_STORES.get("silver_semantic_observations", {})
    assert all(r.get("tenant_id") != tenant for r in silver.values())
    assert len(bronze) == 3

    # The job control record is durable and reports the same completed progress.
    job = await svc.get_replay_job(tenant, result["job_id"])
    assert job is not None and job["status"] == "completed"
    assert job["progress"]["scanned"] == 3


# ── durable-store restart round-trip ──────────────────────────────────────────
async def test_durable_store_round_trip_survives_simulated_restart(tenant, durable_semantic_store):
    """Classify → durably persist → 'restart' (fresh store + service instances)
    → the observation is still readable, and re-delivery stays idempotent."""
    from services.semantic_intelligence.engine import set_store
    from services.semantic_intelligence.models import ObservationStatus
    from services.semantic_intelligence.service import SemanticIntelligenceService
    from services.semantic_intelligence.store import DurableSemanticSentimentStore

    subject = f"product-{tenant}"
    obs, sentiments = await SemanticIntelligenceService().classify_and_persist(
        _feedback(tenant), tenant
    )
    assert obs.status == ObservationStatus.CLASSIFIED
    assert sentiments and sentiments[0].valence > 0

    # Simulated process restart: brand-new store + service must re-read the row.
    set_store(DurableSemanticSentimentStore())
    rows, _ = await SemanticIntelligenceService().list_observations(tenant, subject)
    assert [r.observation_id for r in rows] == [obs.observation_id]

    # Re-delivering the same event after the restart must not duplicate it.
    await SemanticIntelligenceService().classify_and_persist(_feedback(tenant), tenant)
    rows, _ = await SemanticIntelligenceService().list_observations(tenant, subject, limit=100)
    assert len(rows) == 1
