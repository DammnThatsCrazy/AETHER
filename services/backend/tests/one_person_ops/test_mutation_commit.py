"""Approval-to-commit pipeline: validator routing, CIS quarantine, rollback,
rejection safety, per-mutation partial failure, idempotency, tenant isolation,
and flag gating."""

from __future__ import annotations

import dataclasses
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from shared.common.common import BadRequestError, ConflictError, NotFoundError  # noqa: E402
from shared.graph.write_validator import GraphWriteValidator, ValidationResult  # noqa: E402
from services.agent import mutation_commit  # noqa: E402
from services.agent.mutation_commit import commit_approved_mutations, rollback_mutation  # noqa: E402
from services.agent.routes import (  # noqa: E402
    ObjectiveSubmission,
    ReviewDecision,
    _runtime_repo,
    approve_review_batch,
    list_review_batches,
    reject_review_batch,
    submit_objective,
)

from one_person_ops.conftest import FakeRequest, tenant_id  # noqa: E402

pytestmark = pytest.mark.asyncio


class FakeGraph:
    def __init__(self, fail_with: Exception | None = None):
        self.vertices: list = []
        self.edges: list = []
        self.queries: list[str] = []
        self.fail_with = fail_with

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
        return []


VERTEX_MUTATION = {
    "mutation_class": 2,
    "operation": "upsert",
    "target": {"kind": "vertex", "vertex_type": "ENTITY", "vertex_id": "v-1"},
    "diff": {"properties": {"name": "Acme"}},
}
EDGE_MUTATION = {
    "mutation_class": 2,
    "operation": "upsert",
    "target": {
        "kind": "edge", "edge_type": "RELATES_TO",
        "from_vertex_id": "v-1", "to_vertex_id": "v-2",
    },
    "diff": {"properties": {"weight": "0.7"}, "confidence": 0.9},
}


async def _approved_batch(tenant: str, mutations: list[dict]) -> dict:
    batch = await _runtime_repo.create_review_batch(tenant, "obj-x", mutations, "agent", "req-1")
    approved = await _runtime_repo.review_decision(tenant, batch["batch_id"], "approve", "operator", "ok", "req-1")
    assert approved["status"] == "approved"
    return approved


# ── Commit paths ───────────────────────────────────────────────────────────

async def test_approved_vertex_and_edge_commit(review_commit_enabled):
    tenant = tenant_id()
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION, EDGE_MUTATION])
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert result["batch_status"] == "committed"
    assert result["committed"] == 2 and result["failed"] == 0
    assert len(graph.vertices) == 1 and len(graph.edges) == 1
    # Edge write went through build_edge_properties: required props present.
    edge = graph.edges[0]
    for key in ("tenant_id", "idempotency_key", "actor_kind", "actor_id",
                "schema_version", "provenance", "valid_from", "confidence"):
        assert key in edge.properties, f"missing edge property: {key}"
    assert edge.properties["tenant_id"] == tenant
    assert edge.properties["actor_kind"] == "human"
    # Durable status + audit trail.
    for mutation_id in batch["mutation_ids"]:
        mutation = await _runtime_repo.staged_mutations.get(mutation_id)
        assert mutation["status"] == "committed"
        assert mutation["committed_by"] == "operator"
        assert mutation["rollback"]["supported"] is True
    stored_batch = await _runtime_repo.review_batches.get(batch["batch_id"])
    assert stored_batch["status"] == "committed"
    events = await _runtime_repo.events_for_tenant(tenant, limit=100)
    types = [e["event_type"] for e in events]
    assert types.count("mutation.committed") == 2
    assert "batch.committed" in types


async def test_commit_invokes_graph_write_validator(review_commit_enabled, monkeypatch):
    tenant = tenant_id()
    calls: list = []

    class SpyValidator(GraphWriteValidator):
        def validate(self, edge, env=None):
            calls.append(edge)
            return super().validate(edge, env=env)

    monkeypatch.setattr(mutation_commit, "GraphWriteValidator", SpyValidator)
    batch = await _approved_batch(tenant, [EDGE_MUTATION])
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=FakeGraph())
    assert result["committed"] == 1
    assert len(calls) == 1
    assert calls[0].edge_type == "RELATES_TO"


async def test_validator_failure_blocks_commit(review_commit_enabled, monkeypatch):
    tenant = tenant_id()

    class RejectingValidator:
        def validate(self, edge, env=None):
            return ValidationResult(passed=False, violations=["nope"])

    monkeypatch.setattr(mutation_commit, "GraphWriteValidator", RejectingValidator)
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [EDGE_MUTATION])
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert result["failed"] == 1 and result["committed"] == 0
    assert graph.edges == []
    mutation = await _runtime_repo.staged_mutations.get(batch["mutation_ids"][0])
    assert mutation["status"] == "failed_commit"
    assert (await _runtime_repo.review_batches.get(batch["batch_id"]))["status"] == "quarantined"


async def test_cis_quarantine_band_skips_commit(review_commit_enabled, monkeypatch):
    tenant = tenant_id()
    monkeypatch.setattr(settings, "cis", dataclasses.replace(settings.cis, enabled=True))

    class QuarantineGateway:
        async def evaluate_mutation(self, **kwargs):
            from shared.cis.mutation_gateway import MutationRiskResult, MutationRiskSignals
            return MutationRiskResult(
                score=95.0, band="quarantine", signals=MutationRiskSignals(),
                quarantined=True, quarantine_id="q-1",
            )

    monkeypatch.setattr(mutation_commit, "get_gateway", lambda: QuarantineGateway())
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert result["quarantined"] == 1 and result["committed"] == 0
    assert graph.vertices == []
    mutation = await _runtime_repo.staged_mutations.get(batch["mutation_ids"][0])
    assert mutation["status"] == "quarantined"
    assert mutation["quarantine"]["risk_band"] == "quarantine"
    events = await _runtime_repo.events_for_tenant(tenant, limit=100)
    assert any(e["event_type"] == "mutation.quarantined" for e in events)


async def test_rejected_batch_never_commits(review_commit_enabled):
    tenant = tenant_id()
    graph = FakeGraph()
    batch = await _runtime_repo.create_review_batch(tenant, "obj-x", [VERTEX_MUTATION], "agent", "req-1")
    rejected = await _runtime_repo.review_decision(tenant, batch["batch_id"], "reject", "operator", "no", "req-1")
    assert rejected["status"] == "rejected"
    with pytest.raises(ConflictError):
        await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert graph.vertices == [] and graph.edges == []
    mutation = await _runtime_repo.staged_mutations.get(batch["mutation_ids"][0])
    assert mutation["status"] == "rejected"


async def test_partial_failure_is_recorded_per_mutation(review_commit_enabled):
    tenant = tenant_id()
    graph = FakeGraph()
    bad_mutation = {
        "mutation_class": 2,
        "operation": "upsert",
        "target": {"kind": "hologram"},  # unsupported target kind
        "diff": {},
    }
    batch = await _approved_batch(tenant, [VERTEX_MUTATION, bad_mutation])
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    statuses = {r["mutation_id"]: r["status"] for r in result["results"]}
    assert result["committed"] == 1 and result["failed"] == 1
    assert set(statuses.values()) == {"committed", "failed_commit"}
    # The good mutation actually committed; the failure is loud, not silent.
    assert len(graph.vertices) == 1
    assert result["batch_status"] == "quarantined"


async def test_graph_failure_marks_failed_commit_and_preserves_error(review_commit_enabled):
    tenant = tenant_id()
    graph = FakeGraph(fail_with=RuntimeError("neptune down"))
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert result["failed"] == 1
    mutation = await _runtime_repo.staged_mutations.get(batch["mutation_ids"][0])
    assert mutation["status"] == "failed_commit"
    assert "RuntimeError" in mutation["commit_error"]


async def test_duplicate_commit_is_idempotent(review_commit_enabled):
    tenant = tenant_id()
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    first = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    second = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert first["committed"] == 1 and second["committed"] == 1
    assert len(graph.vertices) == 1  # not re-applied


async def test_invalid_mutation_class_fails_before_graph(review_commit_enabled):
    tenant = tenant_id()
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    mutation_id = batch["mutation_ids"][0]
    mutation = await _runtime_repo.staged_mutations.get(mutation_id)
    mutation["mutation_class"] = 9
    await _runtime_repo.staged_mutations.set(mutation_id, mutation)
    result = await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    assert result["failed"] == 1
    assert graph.vertices == []
    assert (await _runtime_repo.staged_mutations.get(mutation_id))["status"] == "failed_commit"


# ── Rollback ───────────────────────────────────────────────────────────────

async def test_rollback_marks_rolled_back_with_best_effort_inverse(review_commit_enabled):
    tenant = tenant_id()
    graph = FakeGraph()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=graph)
    mutation_id = batch["mutation_ids"][0]
    rolled = await rollback_mutation(tenant, mutation_id, "operator", graph=graph)
    assert rolled["status"] == "rolled_back"
    assert rolled["rolled_back_by"] == "operator"
    assert rolled["rollback"]["inverse_applied"] is True
    assert any("drop()" in q and "v-1" in q for q in graph.queries)
    events = await _runtime_repo.events_for_tenant(tenant, limit=100)
    assert any(e["event_type"] == "mutation.rolled_back" for e in events)
    # Idempotent second rollback.
    again = await rollback_mutation(tenant, mutation_id, "operator", graph=graph)
    assert again["status"] == "rolled_back"


async def test_rollback_requires_committed_status(review_commit_enabled):
    tenant = tenant_id()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    with pytest.raises(ConflictError):
        await rollback_mutation(tenant, batch["mutation_ids"][0], "operator", graph=FakeGraph())


# ── Tenant isolation ───────────────────────────────────────────────────────

async def test_tenant_cannot_commit_or_rollback_other_tenants_mutations(review_commit_enabled):
    tenant_a = tenant_id()
    tenant_b = tenant_id()
    graph = FakeGraph()
    batch = await _approved_batch(tenant_a, [VERTEX_MUTATION])
    with pytest.raises(NotFoundError):
        await commit_approved_mutations(tenant_b, batch["batch_id"], "operator", graph=graph)
    await commit_approved_mutations(tenant_a, batch["batch_id"], "operator", graph=graph)
    with pytest.raises(NotFoundError):
        await rollback_mutation(tenant_b, batch["mutation_ids"][0], "operator", graph=graph)


# ── Flag gating and route wiring ───────────────────────────────────────────

async def test_commit_pipeline_gated_off_by_default():
    tenant = tenant_id()
    batch = await _approved_batch(tenant, [VERTEX_MUTATION])
    with pytest.raises(BadRequestError):
        await commit_approved_mutations(tenant, batch["batch_id"], "operator", graph=FakeGraph())
    with pytest.raises(BadRequestError):
        await rollback_mutation(tenant, batch["mutation_ids"][0], "operator", graph=FakeGraph())


async def test_approve_route_without_flag_leaves_batch_approved_uncommitted():
    request = FakeRequest(tenant_id())
    tenant = request.state.tenant.tenant_id
    await submit_objective(ObjectiveSubmission(
        goal="Stage without commit",
        payload={"staged_mutations": [VERTEX_MUTATION]},
    ), request)
    batch_id = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    approved = await approve_review_batch(batch_id, ReviewDecision(notes="ok"), request)
    assert approved["data"]["status"] == "approved"
    assert approved["meta"].get("commit") is None
    mutation_id = approved["data"]["mutation_ids"][0]
    assert (await _runtime_repo.staged_mutations.get(mutation_id))["status"] == "approved"


async def test_approve_route_triggers_commit_when_flag_on(review_commit_enabled, monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(mutation_commit, "_graph_client", lambda: graph)
    request = FakeRequest(tenant_id())
    await submit_objective(ObjectiveSubmission(
        goal="Approve then commit",
        payload={"staged_mutations": [VERTEX_MUTATION]},
    ), request)
    batch_id = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    approved = await approve_review_batch(batch_id, ReviewDecision(notes="ship it"), request)
    assert approved["data"]["status"] == "committed"
    assert approved["meta"]["commit"]["committed"] == 1
    assert len(graph.vertices) == 1


async def test_reject_route_never_reaches_commit_even_with_flag_on(review_commit_enabled, monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(mutation_commit, "_graph_client", lambda: graph)
    request = FakeRequest(tenant_id())
    await submit_objective(ObjectiveSubmission(
        goal="Reject means never commit",
        payload={"staged_mutations": [VERTEX_MUTATION]},
    ), request)
    batch_id = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    rejected = await reject_review_batch(batch_id, ReviewDecision(notes="no"), request)
    assert rejected["data"]["status"] == "rejected"
    assert graph.vertices == [] and graph.edges == []
