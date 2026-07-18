"""Agent runtime + supervised graph-mutation chaos (PR6 real seam).

Drives REAL code, credentialless:

  * agent stale run       -> ``AgentRuntimeRepository.sweep_stale_runs`` reclaims
                             a run whose heartbeat aged past the stale threshold,
                             marking it 'stale' for operator/recovery replay.
  * partial mutation commit -> ``commit_approved_mutations`` commits the good
                             mutation and records the bad one as failed_commit;
                             the batch is quarantined (loud, not silent).
  * graph write failure   -> a graph client raising mid-write marks the mutation
                             failed_commit and preserves the error; nothing is
                             half-applied without a record.
  * rollback failure      -> when the inverse drop errors, the rollback is marked
                             rollback_repair_required (never a false clean undo).

Isolation: unique tenant ids (tenant-scoped reads), flag enabled per-test via the
``review_commit_enabled`` fixture that mirrors the one-person-ops suite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.agent.mutation_commit import commit_approved_mutations, rollback_mutation
from services.agent.routes import _runtime_repo
from services.agent.runtime_repository import AgentRuntimeRepository


# ── fakes / fixtures ──────────────────────────────────────────────────────────
class FakeGraph:
    """In-process graph client. ``fail_with`` fails every write; ``fail_drop``
    fails only the rollback inverse (drop) while count probes still read back."""

    def __init__(self, fail_with: Exception | None = None, fail_drop: bool = False):
        self.vertices: list = []
        self.edges: list = []
        self.queries: list[str] = []
        self.fail_with = fail_with
        self.fail_drop = fail_drop

    async def add_vertex(self, vertex):
        if self.fail_with:
            raise self.fail_with
        self.vertices.append(vertex)
        return vertex.vertex_id

    async def add_edge(self, edge):
        if self.fail_with:
            raise self.fail_with
        self.edges.append(edge)

    async def query(self, gremlin: str):
        self.queries.append(gremlin)
        if self.fail_drop and "drop()" in gremlin:
            raise RuntimeError("neptune drop timeout")
        return []


VERTEX_MUTATION = {
    "mutation_class": 2,
    "operation": "upsert",
    "target": {"kind": "vertex", "vertex_type": "ENTITY", "vertex_id": "v-1"},
    "diff": {"properties": {"name": "Acme"}},
}
BAD_MUTATION = {
    "mutation_class": 2,
    "operation": "upsert",
    "target": {"kind": "hologram"},  # unsupported target kind
    "diff": {},
}


async def _approved_batch(tenant: str, mutations: list[dict]) -> dict:
    batch = await _runtime_repo.create_review_batch(tenant, "obj-chaos", mutations, "agent", "req-1")
    approved = await _runtime_repo.review_decision(
        tenant, batch["batch_id"], "approve", "operator", "ok", "req-1"
    )
    assert approved["status"] == "approved"
    return approved


# ── agent stale run ───────────────────────────────────────────────────────────
async def test_stale_run_is_detected_and_swept(tenant):
    repo = AgentRuntimeRepository()
    old = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
    run_id = "run-chaos-1"
    await repo.worker_runs.set(run_id, {
        "run_id": run_id, "tenant_id": tenant, "status": "running",
        "objective_id": "obj-chaos", "controller": "nous", "worker_id": "w-1",
        "attempt": 1, "created_at": old, "updated_at": old, "heartbeat_at": old,
    })

    stuck = await repo.list_stuck_runs(tenant)
    assert run_id in {r["run_id"] for r in stuck}

    swept = await repo.sweep_stale_runs(tenant)
    assert [r["run_id"] for r in swept] == [run_id]
    assert (await repo.get_run(tenant, run_id))["status"] == "stale"
    # A fresh run is untouched by the sweep.
    assert await repo.list_stuck_runs(tenant) == []


async def test_fresh_run_is_not_swept(tenant):
    repo = AgentRuntimeRepository()
    now = datetime.now(timezone.utc).isoformat()
    run_id = "run-fresh-1"
    await repo.worker_runs.set(run_id, {
        "run_id": run_id, "tenant_id": tenant, "status": "running",
        "objective_id": "obj-chaos", "controller": "nous", "worker_id": "w-1",
        "attempt": 1, "created_at": now, "updated_at": now, "heartbeat_at": now,
    })
    assert await repo.sweep_stale_runs(tenant) == []
    assert (await repo.get_run(tenant, run_id))["status"] == "running"


# ── partial mutation commit ───────────────────────────────────────────────────
async def test_partial_mutation_commit_is_recorded_per_mutation(tenant, review_commit_enabled):
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION, BAD_MUTATION])
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)

    statuses = {r["mutation_id"]: r["status"] for r in result["results"]}
    assert result["committed"] == 1 and result["failed"] == 1
    assert set(statuses.values()) == {"committed", "failed_commit"}
    assert len(graph.vertices) == 1               # the good mutation really committed
    assert result["batch_status"] == "quarantined"  # failure is loud, not silent


# ── graph write failure ───────────────────────────────────────────────────────
async def test_graph_write_failure_marks_failed_commit_and_preserves_error(tenant, review_commit_enabled):
    graph = FakeGraph(fail_with=RuntimeError("neptune down"))
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)

    assert result["failed"] == 1 and result["committed"] == 0
    mutation = await _runtime_repo.staged_mutations.get(batch["mutation_ids"][0])
    assert mutation["status"] == "failed_commit"
    assert "RuntimeError" in mutation["commit_error"]
    assert graph.vertices == []  # nothing half-applied


async def test_commit_is_idempotent_under_duplicate_apply(tenant, review_commit_enabled):
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    first = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    second = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert first["committed"] == 1 and second["committed"] == 1
    assert len(graph.vertices) == 1  # not re-applied on the duplicate commit


# ── rollback failure ──────────────────────────────────────────────────────────
async def test_rollback_inverse_failure_marks_repair_required(tenant, review_commit_enabled):
    # Commit succeeds against a healthy graph.
    healthy = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=healthy)
    mutation_id = batch["mutation_ids"][0]

    # The rollback inverse (drop) fails; the read-back still works.
    failing = FakeGraph(fail_drop=True)
    rolled = await rollback_mutation(tenant, mutation_id, "operator", graph=failing)

    assert rolled["status"] == "rollback_repair_required"
    assert rolled["rollback"]["repair_required"] is True
    assert rolled["rollback"]["inverse_applied"] is False
    assert rolled["rollback"]["inverse_error"]           # error is recorded, not swallowed
    assert rolled["rollback"]["repair_id"]               # a durable repair task was opened


async def test_rollback_success_is_clean_and_idempotent(tenant, review_commit_enabled):
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    mutation_id = batch["mutation_ids"][0]

    rolled = await rollback_mutation(tenant, mutation_id, "operator", graph=graph)
    assert rolled["status"] == "rolled_back"
    again = await rollback_mutation(tenant, mutation_id, "operator", graph=graph)
    assert again["status"] == "rolled_back"  # idempotent second rollback
