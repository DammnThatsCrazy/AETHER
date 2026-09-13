"""Regression coverage for finding provenance across the governed OODA loop."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import InvestigationRepository, reset_in_memory_stores  # noqa: E402
from services.intelligence.comparison.findings import FindingsService  # noqa: E402
from services.intelligence.repositories import RecommendationRepository  # noqa: E402
from services.intelligence.decision_models import (  # noqa: E402
    ActionDispatch,
    ActionFeedback,
    DecisionRecord,
    OutcomeObservation,
)


TENANT = "tenant-loop"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _finding() -> dict:
    return {
        "id": "finding-1",
        "finding_id": "finding-1",
        "tenant_id": TENANT,
        "comparison_run_id": "run-1",
        "finding_type": "material_change",
        "title": "Material change",
        "subject_refs": ["entity-1"],
        "dimension": "outcomes",
        "metric": "conversion_rate",
        "causal_claim": "correlated",
        "evidence_basis": "statistical_correlation",
        "fact_linkage": "linked",
        "disposition": "informational",
    }


@pytest.mark.asyncio
async def test_finding_handoff_preserves_investigation_and_recommendation_provenance():
    service = FindingsService()
    await service._repo.upsert_scoped(TENANT, "finding-1", _finding())

    investigating = await service.dispose(
        TENANT, "finding-1", "investigate", actor_id="operator-1"
    )
    case = await InvestigationRepository().find_by_id(investigating["investigation_id"])
    assert case is not None
    assert case["findingId"] == "finding-1"

    decided = await service.dispose(
        TENANT, "finding-1", "decide", actor_id="operator-1"
    )
    recommendation = await RecommendationRepository().find_by_id(
        decided["recommendation_id"]
    )
    assert recommendation is not None
    assert recommendation["finding_id"] == "finding-1"
    assert recommendation["investigation_id"] == investigating["investigation_id"]

    case = await InvestigationRepository().find_by_id(investigating["investigation_id"])
    assert case["recommendationId"] == decided["recommendation_id"]


def test_loop_records_accept_optional_provenance_links():
    common = {
        "finding_id": "finding-1",
        "investigation_id": "case-1",
    }
    decision = DecisionRecord(
        decision_id="decision-1",
        recommendation_id="recommendation-1",
        actor_id="operator-1",
        rejected_actions=[],
        decision_status="deferred",
        created_at="2026-09-09T00:00:00Z",
        tenant_id=TENANT,
        **common,
    )
    action = ActionFeedback(
        action_id="action-1",
        decision_id=decision.decision_id,
        action_type="manual",
        status="planned",
        actor_type="human",
        created_at="2026-09-09T00:00:00Z",
        tenant_id=TENANT,
        recommendation_id=decision.recommendation_id,
        **common,
    )
    dispatch = ActionDispatch(
        dispatch_id="dispatch-1",
        tenant_id=TENANT,
        action_id=action.action_id,
        decision_id=decision.decision_id,
        recommendation_id=decision.recommendation_id,
        target_type="ticket",
        payload={},
        approval_metadata={},
        created_at="2026-09-09T00:00:00Z",
        retry_count=0,
        **common,
    )
    outcome = OutcomeObservation(
        outcome_id="outcome-1",
        action_id=action.action_id,
        recommendation_id=decision.recommendation_id,
        outcome_type="conversion",
        label="neutral",
        observed_window={"start": "2026-09-09", "end": "2026-09-10"},
        computed_at="2026-09-10T00:00:00Z",
        confidence_delta=0.0,
        tenant_id=TENANT,
        **common,
    )

    assert decision.finding_id == action.finding_id == dispatch.finding_id == outcome.finding_id
    assert decision.investigation_id == action.investigation_id == dispatch.investigation_id == outcome.investigation_id
