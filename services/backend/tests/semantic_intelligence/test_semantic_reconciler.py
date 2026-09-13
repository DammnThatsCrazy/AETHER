"""Semantic reconciler + replay kill-switch.

Proves the reconciler re-derives Gold projections from Silver evidence and
repairs a drifted Gold row (and, in dry-run, reports drift without touching
it), and that the ``semantic.replay`` kill-switch actually gates the durable
replay handler's registration.
"""

from __future__ import annotations

import dataclasses

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.models import (
    IntentLabel,
    SemanticObservation,
    StanceLabel,
    SubjectType,
)
from services.semantic_intelligence.reconciler import reconcile_tenant
from services.semantic_intelligence.reducers import (
    _GOLD_ENTITY_TABLE,
    REDUCER_VERSION,
    recompute_entity_state,
)
from services.semantic_intelligence.repositories.base_fact_repo import (
    SemanticFactRepository,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_recon"
SUBJECT = "prod_recon"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    original = get_store()
    # Durable store keeps Silver AND Gold in the SemanticFactRepository in-memory
    # tables, so distinct_tenants / gold reads see one consistent view.
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()


def _obs(actor: str, stance: StanceLabel) -> SemanticObservation:
    return SemanticObservation(
        tenant_id=TENANT,
        source_event_id=f"e_{actor}_{stance.value}",
        source_type="feedback",
        actor_ref=actor,
        actor_type=SubjectType.PROFILE,
        primary_subject_ref=SUBJECT,
        target_type=SubjectType.PRODUCT,
        stance=stance,
        intent=IntentLabel.EVALUATE,
        classification_confidence=0.9,
    )


def _gold_row() -> dict:
    repo = SemanticFactRepository(_GOLD_ENTITY_TABLE, mode="gold")
    for row in repo._store.values():
        if row.get("tenant_id") == TENANT and row.get("subject_ref") == SUBJECT:
            return row
    raise AssertionError("gold row not found")


async def _seed_two_and_persist_gold():
    store = get_store()
    await store.put_semantic(_obs("a1", StanceLabel.SUPPORTIVE))
    await store.put_semantic(_obs("a2", StanceLabel.SUPPORTIVE))
    await recompute_entity_state(TENANT, SUBJECT)


async def test_reconciler_repairs_drifted_gold():
    await _seed_two_and_persist_gold()

    # Clean immediately after a fresh recompute.
    clean = await reconcile_tenant(TENANT, repair=False)
    assert clean.is_clean

    # Corrupt the stored Gold projection so it diverges from Silver evidence.
    row = _gold_row()
    row["data"]["observation_count"] = 99
    row["data"]["confidence"] = 0.111

    report = await reconcile_tenant(TENANT, repair=True)
    assert any(d.subject_ref == SUBJECT and d.kind == "entity" for d in report.drifted)
    assert report.repaired >= 1

    # Repaired back to the reducer's truth (2 observations, real confidence).
    repaired = _gold_row()["data"]
    assert repaired["observation_count"] == 2
    assert repaired["confidence"] != 0.111
    assert repaired["idempotency_key"] == f"gold_entity:{TENANT}:{SUBJECT}:{REDUCER_VERSION}"

    # A second pass finds nothing to fix.
    assert (await reconcile_tenant(TENANT, repair=True)).is_clean


async def test_reconciler_dry_run_reports_without_repair():
    await _seed_two_and_persist_gold()
    row = _gold_row()
    row["data"]["observation_count"] = 42

    report = await reconcile_tenant(TENANT, repair=False)
    assert not report.is_clean
    assert report.repaired == 0
    # Dry run left the corrupted value in place.
    assert _gold_row()["data"]["observation_count"] == 42


def test_replay_flag_gates_handler_registration(monkeypatch):
    from services.jobs.handlers import HANDLER_REGISTRY
    from services.semantic_intelligence.jobs import (
        SEMANTIC_REPLAY_JOB_TYPE,
        register_semantic_replay_handler,
    )
    from config.settings import settings

    HANDLER_REGISTRY.pop(SEMANTIC_REPLAY_JOB_TYPE, None)
    try:
        # Flag OFF (default): registration is a no-op → job type stays unknown.
        monkeypatch.setattr(
            settings, "semantic", dataclasses.replace(settings.semantic, replay_enabled=False)
        )
        register_semantic_replay_handler()
        assert SEMANTIC_REPLAY_JOB_TYPE not in HANDLER_REGISTRY

        # Flag ON: the durable handler is registered.
        monkeypatch.setattr(
            settings, "semantic", dataclasses.replace(settings.semantic, replay_enabled=True)
        )
        register_semantic_replay_handler()
        assert SEMANTIC_REPLAY_JOB_TYPE in HANDLER_REGISTRY
    finally:
        HANDLER_REGISTRY.pop(SEMANTIC_REPLAY_JOB_TYPE, None)
