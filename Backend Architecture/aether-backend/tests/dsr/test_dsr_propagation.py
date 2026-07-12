"""Tests for the DSR propagation-record layer (prompt §3.11)."""
from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores

from services.dsr_propagation.models import (
    DSR_COMPONENTS,
    DSR_PROPAGATION_STATUSES,
    DSRPropagationStep,
    overall_status,
)
from services.dsr_propagation.service import (
    DSRPropagationRepository,
    DSRPropagationService,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()


def _svc() -> DSRPropagationService:
    return DSRPropagationService()


# ── open_request seeds every component as pending ─────────────────────────────

async def test_open_request_creates_all_component_steps_pending():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="erasure",
    )
    assert request_id.startswith("dsrp_")

    status = await svc.status(request_id, tenant_id="t1")
    components = status["components"]
    # One step per §3.11 component, in the canonical order.
    assert [c["component"] for c in components] == list(DSR_COMPONENTS)
    assert len(components) == 16
    assert all(c["status"] == "pending" for c in components)
    # A freshly-opened request rolls up to pending, never completed.
    assert status["overall"] == "pending"
    assert status["dsr_type"] == "erasure"
    assert status["subject_ref"] == "user:alice"


async def test_open_request_rejects_unknown_dsr_type():
    svc = _svc()
    with pytest.raises(Exception):
        await svc.open_request(tenant_id="t1", subject_ref="user:x", dsr_type="nope")


async def test_open_request_requires_tenant_and_subject():
    svc = _svc()
    with pytest.raises(Exception):
        await svc.open_request(tenant_id="", subject_ref="user:x", dsr_type="access")
    with pytest.raises(Exception):
        await svc.open_request(tenant_id="t1", subject_ref="", dsr_type="access")


# ── mark_step advances a single component + evidence ──────────────────────────

async def test_mark_step_records_evidence_and_timestamps():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="erasure",
    )
    step = await svc.mark_step(
        request_id, "feature_rows", "completed", tenant_id="t1",
        records_impacted=42, policy_decision_id="pol_1",
        audit_event_id="aud_1", requires_recompute=True,
    )
    assert step["status"] == "completed"
    assert step["records_impacted"] == 42
    assert step["policy_decision_id"] == "pol_1"
    assert step["audit_event_id"] == "aud_1"
    assert step["requires_recompute"] is True
    # completed is terminal -> started_at + completed_at auto-stamped.
    assert step["started_at"] and step["completed_at"]

    # Only the targeted component changed.
    status = await svc.status(request_id, tenant_id="t1")
    others = [c for c in status["components"] if c["component"] != "feature_rows"]
    assert all(c["status"] == "pending" for c in others)


async def test_mark_step_running_sets_started_not_completed():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="access",
    )
    step = await svc.mark_step(request_id, "exports", "running", tenant_id="t1")
    assert step["started_at"] is not None
    assert step["completed_at"] is None


async def test_mark_step_rejects_unknown_status_component_and_evidence():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="access",
    )
    with pytest.raises(Exception):
        await svc.mark_step(request_id, "exports", "banana", tenant_id="t1")
    with pytest.raises(Exception):
        await svc.mark_step(request_id, "not_a_component", "completed", tenant_id="t1")
    with pytest.raises(Exception):
        await svc.mark_step(
            request_id, "exports", "completed", tenant_id="t1", bogus_field=1,
        )


async def test_mark_step_negative_records_impacted_rejected():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="erasure",
    )
    with pytest.raises(Exception):
        await svc.mark_step(
            request_id, "feature_rows", "completed", tenant_id="t1",
            records_impacted=-5,
        )


# ── overall roll-up semantics ─────────────────────────────────────────────────

async def test_blocked_step_makes_overall_blocked():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="erasure",
    )
    # Complete a couple, then block one.
    await svc.mark_step(request_id, "identity_aliases", "completed", tenant_id="t1")
    await svc.mark_step(request_id, "graph_edges", "running", tenant_id="t1")
    await svc.mark_step(
        request_id, "model_artifacts", "blocked", tenant_id="t1",
        blocked_reason="on-chain immutable; pseudonymize only",
    )
    status = await svc.status(request_id, tenant_id="t1")
    # blocked outranks running/completed/pending.
    assert status["overall"] == "blocked"


async def test_blocked_requires_reason():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="erasure",
    )
    with pytest.raises(Exception):
        await svc.mark_step(request_id, "model_artifacts", "blocked", tenant_id="t1")
    with pytest.raises(Exception):
        await svc.mark_step(
            request_id, "model_artifacts", "blocked", tenant_id="t1",
            blocked_reason="   ",
        )


async def test_skipped_legal_hold_counts_as_resolved():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="erasure",
    )
    # Resolve every component: most completed, one skipped under legal hold.
    for component in DSR_COMPONENTS:
        if component == "audit_exports":
            await svc.mark_step(
                request_id, component, "skipped_legal_hold", tenant_id="t1",
                blocked_reason="", policy_decision_id="pol_hold",
            )
        else:
            await svc.mark_step(request_id, component, "completed", tenant_id="t1")

    status = await svc.status(request_id, tenant_id="t1")
    # All completed / skipped_legal_hold -> overall completed.
    assert status["overall"] == "completed"
    skipped = [c for c in status["components"] if c["component"] == "audit_exports"][0]
    assert skipped["status"] == "skipped_legal_hold"


async def test_running_step_makes_overall_running():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="access",
    )
    await svc.mark_step(request_id, "exports", "running", tenant_id="t1")
    status = await svc.status(request_id, tenant_id="t1")
    assert status["overall"] == "running"


async def test_failed_and_manual_review_surface_in_overall():
    svc = _svc()
    rid = await svc.open_request(tenant_id="t1", subject_ref="s", dsr_type="erasure")
    await svc.mark_step(rid, "feature_rows", "requires_manual_review", tenant_id="t1")
    assert (await svc.status(rid, tenant_id="t1"))["overall"] == "requires_manual_review"
    await svc.mark_step(rid, "training_datasets", "failed", tenant_id="t1")
    # failed outranks requires_manual_review.
    assert (await svc.status(rid, tenant_id="t1"))["overall"] == "failed"


# ── tenant isolation (fail-closed: cross-tenant reads/writes = not found) ──────

async def test_tenant_isolation_on_status_and_mark():
    svc = _svc()
    request_id = await svc.open_request(
        tenant_id="t1", subject_ref="user:alice", dsr_type="erasure",
    )
    # Correct tenant sees it.
    assert (await svc.status(request_id, tenant_id="t1"))["overall"] == "pending"
    # Another tenant cannot read it.
    with pytest.raises(Exception):
        await svc.status(request_id, tenant_id="t2")
    # Another tenant cannot mutate it.
    with pytest.raises(Exception):
        await svc.mark_step(request_id, "exports", "completed", tenant_id="t2")
    # And the record is untouched from t1's view.
    exports = [
        c for c in (await svc.status(request_id, tenant_id="t1"))["components"]
        if c["component"] == "exports"
    ][0]
    assert exports["status"] == "pending"


async def test_status_missing_request_raises():
    svc = _svc()
    with pytest.raises(Exception):
        await svc.status("dsrp_does_not_exist", tenant_id="t1")


# ── unit: overall_status helper + model constants ─────────────────────────────

async def test_overall_status_helper_precedence():
    assert overall_status([]) == "pending"
    assert overall_status([{"status": "pending"}, {"status": "completed"}]) == "pending"
    assert overall_status([{"status": "completed"}, {"status": "skipped_legal_hold"}]) == "completed"
    assert overall_status([{"status": "running"}, {"status": "pending"}]) == "running"
    assert overall_status([{"status": "blocked"}, {"status": "running"}]) == "blocked"
    assert overall_status([{"status": "failed"}, {"status": "running"}]) == "failed"


async def test_status_constants_match_spec():
    assert len(DSR_COMPONENTS) == 16
    assert set(DSR_PROPAGATION_STATUSES) == {
        "pending", "running", "completed", "blocked", "failed",
        "skipped_legal_hold", "requires_manual_review",
    }
    # Model defaults to a pending step with zeroed impact counters.
    step = DSRPropagationStep(component="exports")
    assert step.status == "pending"
    assert step.records_impacted == 0 and step.artifacts_impacted == 0


async def test_repository_table_name():
    assert DSRPropagationRepository().table_name == "dsr_propagation_records"
