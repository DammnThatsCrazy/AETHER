"""Supervised agent-mutation runtime: approval invariants, optimistic
concurrency, rollback verification + repair, post-commit reconciliation, the
worker→review staging seam, and the Kyber command-center routes.

Every test asserts the same north star: NOTHING commits to the canonical graph
without an explicit, current, human approval — and the kill switch stops it.
"""

from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import ConflictError, ForbiddenError, NotFoundError  # noqa: E402
from services.agent import mutation_commit, worker_bridge  # noqa: E402
from services.agent.mutation_commit import (  # noqa: E402
    commit_approved_mutations,
    reconcile_mutation,
    rollback_mutation,
)
from services.agent.routes import (  # noqa: E402
    DispatchRequest,
    KillSwitchAction,
    MutationActionRequest,
    ObjectiveSubmission,
    ReviewDecision,
    _runtime_repo,
    approve_review_batch,
    dispatch_step,
    export_audit,
    get_mutation_diff,
    get_mutation_evidence,
    list_review_batches,
    quarantine_batch,
    reapprove_batch,
    rollback_committed_mutation,
    submit_objective,
    toggle_kill_switch,
    verify_mutation_state,
)
from services.agent.worker_routes import RunStatusUpdate, update_run_status

from one_person_ops.conftest import (  # noqa: E402
    OPERATOR_PERMISSIONS,
    WORKER_PERMISSIONS,
    FakeRequest,
    set_ops_flags,
    tenant_id,
)

pytestmark = pytest.mark.asyncio


VERTEX_MUTATION = {
    "mutation_class": 2,
    "operation": "upsert",
    "target": {"kind": "vertex", "vertex_type": "ENTITY", "vertex_id": "v-occ"},
    "diff": {"properties": {"name": "Acme"}},
}


class StatefulFakeGraph:
    """A fake graph that actually tracks presence so rollback verification and
    reconciliation can be exercised. ``undroppable`` simulates a graph where the
    inverse drop does not remove the artifact; ``raise_on_drop`` simulates an
    inverse that errors."""

    _V = re.compile(r"g\.V\('([^']*)'\)")
    _E = re.compile(r"has\('idempotency_key',\s*'([^']*)'\)")

    def __init__(self, undroppable: bool = False, raise_on_drop: bool = False):
        self.vertices: set[str] = set()
        self.edges: set[str] = set()
        self.undroppable = undroppable
        self.raise_on_drop = raise_on_drop
        self.queries: list[str] = []

    async def add_vertex(self, vertex):
        self.vertices.add(vertex.vertex_id)
        return vertex.vertex_id

    async def upsert_vertex(self, vertex):
        self.vertices.add(vertex.vertex_id)
        return vertex.vertex_id

    async def add_edge(self, edge):
        self.edges.add(edge.properties.get("idempotency_key", ""))

    async def query(self, gremlin: str):
        self.queries.append(gremlin)
        is_vertex = gremlin.startswith("g.V(")
        vid = self._V.search(gremlin)
        eid = self._E.search(gremlin)
        if ".drop()" in gremlin:
            if self.raise_on_drop:
                raise RuntimeError("neptune drop rejected")
            if not self.undroppable:
                if is_vertex and vid:
                    self.vertices.discard(vid.group(1))
                elif eid:
                    self.edges.discard(eid.group(1))
            return []
        if ".count()" in gremlin:
            if is_vertex and vid:
                return [1 if vid.group(1) in self.vertices else 0]
            if eid:
                return [1 if eid.group(1) in self.edges else 0]
            return [0]
        return []


async def _staged_batch(tenant: str, mutations: list[dict], objective_id: str = "obj-x") -> dict:
    return await _runtime_repo.create_review_batch(tenant, objective_id, mutations, "agent", "req-1")


async def _approved_batch(tenant: str, mutations: list[dict]) -> dict:
    batch = await _staged_batch(tenant, mutations)
    approved = await _runtime_repo.review_decision(tenant, batch["batch_id"], "approve", "operator", "ok", "req-1")
    assert approved["status"] == "approved"
    return approved


# ═══════════════════════════════════════════════════════════════════════════
# Item 4 — Approval invariants
# ═══════════════════════════════════════════════════════════════════════════

async def test_worker_credential_cannot_approve(review_commit_enabled):
    tenant = tenant_id()
    batch = await _staged_batch(tenant, [VERTEX_MUTATION])
    worker = FakeRequest(tenant, permissions=set(WORKER_PERMISSIONS))
    with pytest.raises(ForbiddenError):
        await approve_review_batch(batch["batch_id"], ReviewDecision(notes="nope"), worker)
    # And the batch never left pending → nothing is committable.
    assert (await _runtime_repo.review_batches.get(batch["batch_id"]))["status"] == "pending"


async def test_operator_approval_required_to_commit(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    # A pending (never-approved) batch cannot commit — human review is the gate.
    batch = await _staged_batch(tenant, [VERTEX_MUTATION])
    with pytest.raises(ConflictError):
        await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert graph.vertices == set()
    # Approve, then commit succeeds.
    await _runtime_repo.review_decision(tenant, batch["batch_id"], "approve", "operator", "ok", "req-1")
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert result["committed"] == 1 and "v-occ" in graph.vertices


async def test_expired_approval_cannot_commit(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    mutation_id = batch["mutation_ids"][0]
    # Backdate the approval well past the TTL.
    mutation = await _runtime_repo.staged_mutations.get(mutation_id)
    mutation["approved_at"] = "2000-01-01T00:00:00+00:00"
    await _runtime_repo.staged_mutations.set(mutation_id, mutation)
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert result["committed"] == 0 and result["blocked"] == 1
    assert result["results"][0]["status"] == "approval_expired"
    assert graph.vertices == set()
    assert result["batch_status"] == "quarantined"


async def test_modified_mutation_requires_reapproval(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    batch_id = batch["batch_id"]
    mutation_id = batch["mutation_ids"][0]
    # Tamper the approved mutation's content (still a valid class).
    mutation = await _runtime_repo.staged_mutations.get(mutation_id)
    mutation["diff"] = {"properties": {"name": "Evil Corp"}}
    await _runtime_repo.staged_mutations.set(mutation_id, mutation)
    # The recorded approval no longer covers this content → commit is refused.
    result = await commit_approved_mutations(tenant, batch_id, "operator", graph=graph)
    assert result["blocked"] == 1 and result["committed"] == 0
    assert result["results"][0]["status"] == "needs_reapproval"
    assert graph.vertices == set()
    # Re-approval re-binds the approval to the current content → commit proceeds.
    await _runtime_repo.reapprove_batch(tenant, batch_id, "operator", "req-2", notes="reviewed change")
    result2 = await commit_approved_mutations(tenant, batch_id, "operator", graph=graph)
    assert result2["committed"] == 1 and "v-occ" in graph.vertices


async def test_quarantined_mutation_cannot_commit(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    batch_id = batch["batch_id"]
    # Operator hard-stop quarantine freezes the batch.
    await _runtime_repo.quarantine_review_batch(tenant, batch_id, "operator", "looks wrong", "req-1")
    assert (await _runtime_repo.staged_mutations.get(batch["mutation_ids"][0]))["status"] == "quarantined"
    result = await commit_approved_mutations(tenant, batch_id, "operator", graph=graph)
    assert result["committed"] == 0
    assert result["results"][0]["status"] == "skipped_not_approved"
    assert graph.vertices == set()


async def test_kill_switch_blocks_commit_at_pipeline(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await _runtime_repo.set_kill_switch(tenant, True, "operator", "incident", "req-1")
    # Even a direct/scheduled caller with an approved batch cannot commit.
    with pytest.raises(ConflictError):
        await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert graph.vertices == set()


async def test_kill_switch_blocks_commit_via_approve_route(review_commit_enabled, monkeypatch):
    graph = StatefulFakeGraph()
    monkeypatch.setattr(mutation_commit, "_graph_client", lambda: graph)
    request = FakeRequest(tenant_id())
    await submit_objective(ObjectiveSubmission(
        goal="Kill switch blocks commit", payload={"staged_mutations": [VERTEX_MUTATION]},
    ), request)
    await toggle_kill_switch(KillSwitchAction(action="engage", reason="incident"), request)
    batch_id = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    approved = await approve_review_batch(batch_id, ReviewDecision(notes="try commit"), request)
    # Approval is recorded, but the commit is blocked and nothing is written.
    assert approved["data"]["status"] == "approved"
    assert approved["meta"]["commit_blocked"] == "kill_switch_engaged"
    assert graph.vertices == set()


async def test_scheduled_or_noesis_cannot_bypass_review(review_commit_enabled):
    """Non-operator actors and automated callers cannot manufacture an approval
    or commit unreviewed work."""
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _staged_batch(tenant, [VERTEX_MUTATION])
    # A caller lacking agent:approve (e.g. a scheduled job / Noesis service
    # credential) cannot approve via the route.
    for perms in ({"agent:manage", "agent:dispatch"}, set(WORKER_PERMISSIONS)):
        actor = FakeRequest(tenant, permissions=perms)
        with pytest.raises(ForbiddenError):
            await approve_review_batch(batch["batch_id"], ReviewDecision(), actor)
    # And committing the still-pending batch directly is refused (no approval).
    with pytest.raises(ConflictError):
        await commit_approved_mutations(tenant, batch["batch_id"], "scheduler", graph=graph)
    assert graph.vertices == set()
    assert (await _runtime_repo.staged_mutations.get(batch["mutation_ids"][0]))["status"] == "staged"


# ═══════════════════════════════════════════════════════════════════════════
# Item 2 — Optimistic concurrency (expected-version / ETag)
# ═══════════════════════════════════════════════════════════════════════════

async def test_stale_version_commit_is_rejected(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    # Two batches staged against the SAME target at the same base version.
    batch_a = await _approved_batch(tenant, [VERTEX_MUTATION])
    batch_b = await _approved_batch(tenant, [VERTEX_MUTATION])
    mut_a = await _runtime_repo.staged_mutations.get(batch_a["mutation_ids"][0])
    mut_b = await _runtime_repo.staged_mutations.get(batch_b["mutation_ids"][0])
    assert mut_a["base_version"] == 0 and mut_b["base_version"] == 0
    # First commit advances the canonical version 0 → 1.
    first = await commit_approved_mutations(tenant, batch_a["batch_id"], "operator", graph=graph)
    assert first["committed"] == 1
    committed = await _runtime_repo.staged_mutations.get(batch_a["mutation_ids"][0])
    assert committed["committed_version"] == 1
    # Second commit was staged against version 0 → now stale → rejected, no write.
    second = await commit_approved_mutations(tenant, batch_b["batch_id"], "operator", graph=graph)
    assert second["committed"] == 0 and second["blocked"] == 1
    assert second["results"][0]["status"] == "stale_version"
    conflict = (await _runtime_repo.staged_mutations.get(batch_b["mutation_ids"][0]))["conflict"]
    assert conflict["kind"] == "stale_version"
    assert conflict["expected_version"] == 0 and conflict["current_version"] == 1
    # Exactly one vertex write happened despite two approvals for the same target.
    assert graph.vertices == {"v-occ"}


async def test_duplicate_commit_does_not_double_bump_version(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    # Idempotent re-commit short-circuits before OCC → version stays 1.
    assert await _runtime_repo.canonical_version(tenant, "vertex:ENTITY:v-occ") == 1


# ═══════════════════════════════════════════════════════════════════════════
# Item 3 — Rollback verification + repair + reconciliation
# ═══════════════════════════════════════════════════════════════════════════

async def test_rollback_verifies_inverse_applied(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert "v-occ" in graph.vertices
    rolled = await rollback_mutation(tenant, batch["mutation_ids"][0], "operator", graph=graph)
    assert rolled["status"] == "rolled_back"
    assert rolled["rollback"]["verified"] is True
    assert rolled["rollback"]["verification"]["confirmed"] is True
    assert rolled["rollback"]["verification"]["remaining"] == 0
    assert "v-occ" not in graph.vertices


async def test_rollback_opens_repair_when_artifact_persists(review_commit_enabled):
    tenant = tenant_id()
    commit_graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=commit_graph)
    # Roll back against a graph where the drop does not remove the vertex.
    stubborn = StatefulFakeGraph(undroppable=True)
    stubborn.vertices.add("v-occ")
    rolled = await rollback_mutation(tenant, batch["mutation_ids"][0], "operator", graph=stubborn)
    assert rolled["status"] == "rollback_repair_required"
    assert rolled["rollback"]["verified"] is False
    assert rolled["rollback"]["repair_required"] is True
    repairs = await _runtime_repo.list_repair_tasks(tenant, status="open")
    assert len(repairs) == 1 and repairs[0]["reason"] == "artifact_still_present"
    assert repairs[0]["repair_id"] == rolled["rollback"]["repair_id"]
    events = await _runtime_repo.events_for_tenant(tenant, limit=100)
    assert any(e["event_type"] == "mutation.rollback_repair_required" for e in events)


async def test_rollback_opens_repair_on_inverse_error(review_commit_enabled):
    tenant = tenant_id()
    commit_graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=commit_graph)
    erroring = StatefulFakeGraph(raise_on_drop=True)
    erroring.vertices.add("v-occ")
    rolled = await rollback_mutation(tenant, batch["mutation_ids"][0], "operator", graph=erroring)
    assert rolled["status"] == "rollback_repair_required"
    assert rolled["rollback"]["inverse_error"]
    repairs = await _runtime_repo.list_repair_tasks(tenant, status="open")
    assert repairs and repairs[0]["reason"] == "inverse_error"


async def test_reconcile_committed_matches_graph(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    receipt = await reconcile_mutation(tenant, batch["mutation_ids"][0], "operator", graph=graph)
    assert receipt["consistent"] is True
    assert receipt["observed_present"] is True and receipt["expected_present"] is True


async def test_reconcile_detects_drift(review_commit_enabled):
    tenant = tenant_id()
    graph = StatefulFakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    # The committed vertex vanishes out-of-band → reconciliation flags drift.
    graph.vertices.discard("v-occ")
    receipt = await reconcile_mutation(tenant, batch["mutation_ids"][0], "operator", graph=graph)
    assert receipt["consistent"] is False
    events = await _runtime_repo.events_for_tenant(tenant, limit=100)
    assert any(e["event_type"] == "mutation.reconcile_drift" for e in events)


# ═══════════════════════════════════════════════════════════════════════════
# Item 1 — Worker → review staging seam (proposals are staged, never committed)
# ═══════════════════════════════════════════════════════════════════════════

async def _dispatched_run(request, monkeypatch) -> dict:
    monkeypatch.setattr(
        worker_bridge, "dispatch_to_worker",
        lambda envelope: {"dispatched": True, "task_id": "t", "queue": envelope["queue"]},
    )
    objective = (await submit_objective(ObjectiveSubmission(goal="Discover then propose"), request))["data"]
    return (await dispatch_step(
        DispatchRequest(objective_id=objective["objective_id"], controller="discovery"), request
    ))["data"]


async def test_completed_run_stages_proposals_for_review_not_commit(monkeypatch):
    set_ops_flags(monkeypatch, worker_bridge_enabled=True, staged_mutation_review_enabled=True)
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=set(OPERATOR_PERMISSIONS))
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=set(WORKER_PERMISSIONS))
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    completed = await update_run_status(
        run["run_id"],
        RunStatusUpdate(status="completed", output={
            "step": "web_crawler",
            "proposed_mutations": [{
                "mutation_class": 1, "operation": "upsert",
                "target": {"kind": "vertex", "vertex_type": "ENTITY", "vertex_id": "ent-1"},
                "diff": {"properties": {"title": "Acme"}},
            }],
        }),
        worker,
    )
    batch_id = completed["data"]["review_batch_id"]
    # A pending review batch exists with the proposal STAGED (not approved/committed).
    batch = await _runtime_repo.review_batches.get(batch_id)
    assert batch["status"] == "pending"
    mutation = await _runtime_repo.staged_mutations.get(batch["mutation_ids"][0])
    assert mutation["status"] == "staged"
    # The objective is parked awaiting review (cannot be re-dispatched around the gate).
    objective = await _runtime_repo.get_objective(tenant, run["objective_id"])
    assert objective["status"] == "awaiting_review"
    with pytest.raises(ConflictError):
        await dispatch_step(DispatchRequest(objective_id=run["objective_id"], controller="discovery"), operator)
    # The staging worker credential cannot approve what it proposed.
    with pytest.raises(ForbiddenError):
        await approve_review_batch(batch_id, ReviewDecision(), FakeRequest(tenant, permissions=set(WORKER_PERMISSIONS)))


async def test_duplicate_completion_stages_proposals_once(monkeypatch):
    set_ops_flags(monkeypatch, worker_bridge_enabled=True, staged_mutation_review_enabled=True)
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=set(OPERATOR_PERMISSIONS))
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=set(WORKER_PERMISSIONS))
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    payload = RunStatusUpdate(status="completed", output={"proposed_mutations": [{
        "mutation_class": 1, "operation": "upsert",
        "target": {"kind": "vertex", "vertex_type": "ENTITY", "vertex_id": "ent-dup"},
        "diff": {"properties": {"title": "Acme"}},
    }]})
    await update_run_status(run["run_id"], payload, worker)
    # A retried completion callback (idempotent) must not stage a second batch.
    await update_run_status(run["run_id"], payload, worker)
    batches = await _runtime_repo.review_batches_for_objective(tenant, run["objective_id"])
    assert len(batches) == 1


async def test_bad_proposals_are_dropped_not_raised(monkeypatch):
    set_ops_flags(monkeypatch, worker_bridge_enabled=True, staged_mutation_review_enabled=True)
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=set(OPERATOR_PERMISSIONS))
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=set(WORKER_PERMISSIONS))
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    completed = await update_run_status(
        run["run_id"],
        RunStatusUpdate(status="completed", output={
            "proposed_mutations": [{"mutation_class": 99, "target": {}}, "not-a-dict"],
        }),
        worker,
    )
    # All proposals were invalid → no batch created, callback still succeeds.
    assert "review_batch_id" not in completed["data"]
    assert completed["data"]["status"] == "completed"


# ═══════════════════════════════════════════════════════════════════════════
# Item 5 — Command-center routes against the live runtime
# ═══════════════════════════════════════════════════════════════════════════

async def _route_committed_mutation(request, monkeypatch) -> tuple[str, str, StatefulFakeGraph]:
    graph = StatefulFakeGraph()
    monkeypatch.setattr(mutation_commit, "_graph_client", lambda: graph)
    await submit_objective(ObjectiveSubmission(
        goal="Route commit", payload={"staged_mutations": [VERTEX_MUTATION]},
    ), request)
    batch_id = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    approved = await approve_review_batch(batch_id, ReviewDecision(notes="go"), request)
    mutation_id = approved["data"]["mutation_ids"][0]
    return batch_id, mutation_id, graph


async def test_rollback_and_verify_routes(review_commit_enabled, monkeypatch):
    request = FakeRequest(tenant_id())
    _, mutation_id, graph = await _route_committed_mutation(request, monkeypatch)
    assert "v-occ" in graph.vertices
    rolled = await rollback_committed_mutation(mutation_id, MutationActionRequest(reason="undo"), request)
    assert rolled["data"]["status"] == "rolled_back"
    verify = await verify_mutation_state(mutation_id, request)
    # After rollback the mutation should reconcile as absent → consistent.
    assert verify["data"]["consistent"] is True
    assert verify["data"]["observed_present"] is False


async def test_diff_and_evidence_routes(review_commit_enabled, monkeypatch):
    request = FakeRequest(tenant_id())
    _, mutation_id, _ = await _route_committed_mutation(request, monkeypatch)
    diff = await get_mutation_diff(mutation_id, request)
    assert diff["data"]["target"]["vertex_id"] == "v-occ"
    assert diff["data"]["committed_version"] == 1
    evidence = await get_mutation_evidence(mutation_id, request)
    assert evidence["data"]["approval"]["approved_by"]
    assert isinstance(evidence["data"]["events"], list)


async def test_quarantine_route_blocks_commit(review_commit_enabled, monkeypatch):
    graph = StatefulFakeGraph()
    monkeypatch.setattr(mutation_commit, "_graph_client", lambda: graph)
    request = FakeRequest(tenant_id())
    await submit_objective(ObjectiveSubmission(
        goal="Quarantine me", payload={"staged_mutations": [VERTEX_MUTATION]},
    ), request)
    batch_id = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    quarantined = await quarantine_batch(batch_id, MutationActionRequest(reason="suspicious"), request)
    assert quarantined["data"]["status"] == "quarantined"
    # Approving a quarantined batch cannot resurrect a commit (review_decision
    # only acts on pending), and the mutation stays quarantined.
    mutation_id = quarantined["data"]["mutation_ids"][0]
    assert (await _runtime_repo.staged_mutations.get(mutation_id))["status"] == "quarantined"
    assert graph.vertices == set()


async def test_reapprove_route_recommits_after_quarantine(review_commit_enabled, monkeypatch):
    graph = StatefulFakeGraph()
    monkeypatch.setattr(mutation_commit, "_graph_client", lambda: graph)
    request = FakeRequest(tenant_id())
    await submit_objective(ObjectiveSubmission(
        goal="Quarantine then reapprove", payload={"staged_mutations": [VERTEX_MUTATION]},
    ), request)
    batch_id = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    # Hard-stop quarantine, then a fresh operator review re-approves → recommit.
    await quarantine_batch(batch_id, MutationActionRequest(reason="hold"), request)
    assert graph.vertices == set()
    reapproved = await reapprove_batch(batch_id, ReviewDecision(notes="cleared"), request)
    assert reapproved["data"]["status"] == "committed"
    assert reapproved["meta"]["commit"]["committed"] == 1
    assert "v-occ" in graph.vertices


async def test_audit_export_route(review_commit_enabled, monkeypatch):
    request = FakeRequest(tenant_id())
    await _route_committed_mutation(request, monkeypatch)
    export = await export_audit(request)
    assert export["data"]["counts"]["events"] >= 1
    assert export["data"]["counts"]["review_batches"] >= 1
    assert "exported_at" in export["data"]
