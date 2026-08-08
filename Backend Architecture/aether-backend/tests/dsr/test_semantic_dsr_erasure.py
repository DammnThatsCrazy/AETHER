"""Semantic-intelligence plane reachable by a DSR erasure, with real evidence.

Seeds a subject's semantic observation, sentiment observation, Gold aggregate
state row and review-queue item, runs the ``consent.erasure`` handler, and
asserts the four semantic ``dsr_propagation`` components
(``semantic_observations``, ``sentiment_observations``, ``semantic_gold_state``,
``semantic_review_queue``) are marked ``completed`` with each store's OWN real
erased-row count — and that the rows are actually gone.

These four components were already declared expected in
``dsr_propagation.models.DSR_COMPONENTS`` but nothing ever marked them, so a
subject's semantic data silently survived a DSR erasure the record reported as
``completed``. A forced semantic-plane failure must mark all four semantic
components ``failed`` and keep the whole job retryable (the deletes are
idempotent), so the worker re-runs the erasure.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.jobs_repo import reset_jobs_memory
from repositories.repos import reset_in_memory_stores

from services.consent.erasure_jobs import (
    ERASURE_JOB_TYPE,
    register_consent_erasure_handler,
)
from services.dsr_propagation.service import dsr_propagation_service
from services.jobs.handlers import HANDLER_REGISTRY, JobContext
from services.measurement import privacy as privacy_mod
from services.semantic_intelligence.repositories.base_fact_repo import (
    SemanticFactRepository,
)
from services.semantic_intelligence.repositories.review_queue_repo import (
    SemanticReviewQueueRepository,
)

pytestmark = pytest.mark.asyncio

TENANT = "tenant-semantic-dsr"
USER = "subject-to-erase"
JOB_ID = "job_semantic_dsr"

_SEMANTIC_COMPONENTS = (
    "semantic_observations",
    "sentiment_observations",
    "semantic_gold_state",
    "semantic_review_queue",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_in_memory_stores()
    reset_jobs_memory()
    register_consent_erasure_handler()
    # Neutralize the measurement erasure so the test isolates the semantic plane;
    # the mobile stores stay empty (their erasers return 0 — harmless).
    monkeypatch.setattr(
        privacy_mod._touchpoint_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        privacy_mod._conversion_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    from services.measurement.engine.journey_compiler import JourneyCompiler

    monkeypatch.setattr(
        JourneyCompiler, "rebuild_affected_by_consent_change", AsyncMock(return_value=None)
    )
    yield
    reset_in_memory_stores()
    reset_jobs_memory()


async def _seed_table(table: str) -> None:
    """Seed one subject-linked row into a semantic silver/gold table."""
    repo = SemanticFactRepository(table)
    await repo.upsert(
        {
            "id": f"{table}_row",
            "tenant_id": TENANT,
            "subject_ref": USER,
            "source_event_id": f"ev_{table}",
            "occurred_at": "2026-08-01T00:00:00+00:00",
            "idempotency_key": f"idem_{table}",
            "data": {"idempotency_key": f"idem_{table}", "actor_ref": USER},
        }
    )


async def _seed_semantic_data() -> None:
    await _seed_table("silver_semantic_observations")
    await _seed_table("silver_sentiment_observations")
    await _seed_table("gold_entity_semantic_state")
    await SemanticReviewQueueRepository().enqueue(
        TENANT, "low_confidence", subject_ref=USER, source_event_id="ev_rq"
    )


def _ctx() -> JobContext:
    return JobContext(
        job_id=JOB_ID,
        tenant_id=TENANT,
        correlation_id="corr",
        heartbeat=AsyncMock(return_value=True),
        emit_event=AsyncMock(return_value=None),
    )


async def _run_handler(propagation_id: str):
    handler = HANDLER_REGISTRY[ERASURE_JOB_TYPE]
    return await handler(
        {"user_id": USER, "propagation_request_id": propagation_id}, _ctx()
    )


async def test_semantic_plane_erased_with_real_evidence():
    await _seed_semantic_data()
    propagation_id = await dsr_propagation_service.open_request(
        TENANT, f"user:{USER}", "erasure"
    )

    outcome = await _run_handler(propagation_id)
    assert outcome.status == "succeeded"

    status = await dsr_propagation_service.status(propagation_id, tenant_id=TENANT)
    by_comp = {c["component"]: c for c in status["components"]}

    # Each semantic component is completed WITH its store's own real erased-row
    # count (one seeded row per store).
    for comp in _SEMANTIC_COMPONENTS:
        assert by_comp[comp]["status"] == "completed", comp
        assert by_comp[comp]["records_impacted"] == 1, comp
        # The durable job id is the audit pointer for each store's execution.
        assert by_comp[comp]["audit_event_id"] == JOB_ID, comp

    # The rows are actually gone from every semantic store (a re-delete finds 0).
    for table in (
        "silver_semantic_observations",
        "silver_sentiment_observations",
        "gold_entity_semantic_state",
    ):
        assert await SemanticFactRepository(table).delete_by_subject(TENANT, USER) == 0
    assert await SemanticReviewQueueRepository().purge_by_subject(TENANT, USER) == 0


async def test_semantic_failure_marks_all_components_failed_and_is_retryable(monkeypatch):
    await _seed_semantic_data()
    propagation_id = await dsr_propagation_service.open_request(
        TENANT, f"user:{USER}", "erasure"
    )

    # Force the whole semantic plane to fail; all four components must be marked
    # failed and the job must stay retryable (the underlying deletes are idempotent).
    from services.semantic_intelligence.service import SemanticIntelligenceService

    monkeypatch.setattr(
        SemanticIntelligenceService,
        "erase_subject",
        AsyncMock(side_effect=RuntimeError("semantic store down")),
    )

    outcome = await _run_handler(propagation_id)
    assert outcome.status == "failed"
    assert "semantic store down" in (outcome.error or "")

    status = await dsr_propagation_service.status(propagation_id, tenant_id=TENANT)
    by_comp = {c["component"]: c for c in status["components"]}
    for comp in _SEMANTIC_COMPONENTS:
        assert by_comp[comp]["status"] == "failed", comp
    # Fail-closed roll-up surfaces the failure so the worker retries.
    assert status["overall"] == "failed"
