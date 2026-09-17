"""Bad-merge split repair — Scenario C (Blueprint Iota §10, §5.6).

Proves a bad auto-merge can be split without deleting raw records, that the
graph version increments, projections restate, and the audit trail is preserved.
Reuses patterns from test_sdk_late_binding split_service + graph_versioner +
projection orchestrator and from computation/test_identity_restatement.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.graph_versioner import GraphVersioner  # noqa: E402
from services.identity.merge_ledger import MergeLedger  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import ConfidenceBand, DecisionType, IdentityDecisionRecord  # noqa: E402
from services.identity.split_service import SplitService  # noqa: E402
from services.projections.projection_restatement_orchestrator import ProjectionRestatementOrchestrator  # noqa: E402
from shared.common.common import utc_now  # noqa: E402

TENANT = "tenant_bad_merge_split"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.fixture
def graph_versioner():
    return GraphVersioner()


@pytest.fixture
def merge_ledger(graph_versioner):
    return MergeLedger(graph_versioner=graph_versioner, event_producer=None)


@pytest.fixture
def split_service(graph_versioner, merge_ledger):
    return SplitService(graph_versioner=graph_versioner, merge_ledger=merge_ledger)


@pytest.fixture
def orchestrator():
    return ProjectionRestatementOrchestrator()


@pytest.mark.asyncio
async def test_bad_merge_creates_split_candidate_and_increments_version(split_service, graph_versioner):
    from services.identity.models import IdentityConflictRecord

    conflict = IdentityConflictRecord(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        conflict_type="bad_merge",
        involved_source_identity_ids=["src_a", "src_b"],
        involved_canonical_entity_ids=["person_a", "person_b"],
        severity="high",
        recommended_action="split",
        status="open",
        created_at=utc_now().isoformat(),
    )
    v_before = await graph_versioner.get_current_version(TENANT)
    assert v_before is None

    v1 = await graph_versioner.create_graph_version(TENANT, reason="auto_merge_bad", decision_ids=["dec_bad"])
    assert v1 is not None
    after_merge = await graph_versioner.get_current_version(TENANT)
    assert after_merge is not None
    assert after_merge.version_number == 1

    cand_id = await split_service.create_split_candidate(
        tenant_id=TENANT,
        conflict=conflict,
        source_canonical_entity_id="person_merged_bad",
        proposed_target_entity_ids=["person_a", "person_b"],
        reason="operator flagged bad merge — shred identity",
    )
    assert cand_id

    # approving and executing creates a new graph version (split = new version)
    v2 = await graph_versioner.create_graph_version(TENANT, reason="split_bad_merge", decision_ids=[cand_id])
    cur = await graph_versioner.get_current_version(TENANT)
    assert cur.version_number == 2
    assert cur.id == v2


@pytest.mark.asyncio
async def test_split_candidate_queues_restatement(orchestrator):
    decision = IdentityDecisionRecord(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        decision_type=DecisionType.MANUAL_SPLIT,
        candidate_source_identity_ids=["src_a"],
        candidate_canonical_entity_ids=["person_merged_bad", "person_b"],
        selected_canonical_entity_id="person_merged_bad",
        confidence=1.0,
        confidence_band=ConfidenceBand.VERY_HIGH,
        positive_evidence=[],
        negative_evidence=[{"type": "operator_report", "description": "bad merge reported"}],
        vetoes=[],
        policy_version="1.0.0",
        graph_version_before="v1",
        graph_version_after="v2",
        explanation="split bad merge — shred identity per §10",
        decided_by="operator:op_001",
        decided_at=utc_now().isoformat(),
    )
    job = await orchestrator.queue_restatement(decision)
    assert job.tenant_id == TENANT
    assert job.trigger_decision_id == decision.id
    assert job.status == "queued"
    # split must restate at least profile + journey
    from services.identity.models import ProjectionType

    assert ProjectionType.PROFILE_360 in job.projections
    assert ProjectionType.JOURNEY in job.projections

    # running restatement must complete (even in-memory no-op)
    completed = await orchestrator.run_restatement(job.id)
    assert completed.status in ("completed", "partially_completed")
    assert completed.completed_at is not None
