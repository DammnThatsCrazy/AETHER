"""Import Engine commit / replay / rollback — end-to-end through Bronze + graph.

Proves the mutation half: an approved import stages every row to Bronze
(tagged by commit id) and upserts entity/identifier vertices + relationship /
has-identifier edges into the graph with ``import_commit_id`` lineage; rollback
revokes exactly those edges and deletes the commit's Bronze rows (source bytes
untouched); replay re-stages under a fresh commit without duplicating edges.
Every read is tenant-scoped.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "services" / "api"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from ingestion.imports import commit as cm  # noqa: E402
from ingestion.imports import service as svc  # noqa: E402
from ingestion.imports.rights_admission import (  # noqa: E402
    ImportRightsAdmission,
    ImportRightsDenied,
)

TENANT = "tenant-commit"
OTHER = "tenant-other"
SOURCE = "tenant-import-source"

CSV = (
    b"user_id,email,friend_id\n"
    b"alice,Alice@Example.com,bob\n"
    b"bob,bob@example.com,alice\n"
)

# user_id -> entity + identifier.entity_ref + relationship.from_ref;
# email -> identifier.value (governance-sensitive); friend_id -> relationship.to_ref.
MAPPING = [
    {"source_column": "user_id", "primitive": "entity", "target_field": "external_id",
     "transform": "trim", "required": True},
    {"source_column": "email", "primitive": "identifier", "target_field": "value",
     "transform": "lowercase", "required": True},
    {"source_column": "user_id", "primitive": "identifier", "target_field": "entity_ref",
     "transform": "trim", "required": True},
    {"source_column": "user_id", "primitive": "relationship", "target_field": "from_ref",
     "transform": "trim", "required": True},
    {"source_column": "friend_id", "primitive": "relationship", "target_field": "to_ref",
     "transform": "trim", "required": True},
]


@contextmanager
def raises_named(*names: str):
    with pytest.raises(Exception) as excinfo:  # noqa: PT011
        yield excinfo
    got = type(excinfo.value).__name__
    assert got in names, f"expected one of {names}, got {got}: {excinfo.value}"


@pytest.fixture()
def clean(monkeypatch, request):
    from repositories.imports_repo import get_imports_repository
    from repositories.repos import reset_in_memory_stores
    from repositories.graph_mutation_ledger import reset_graph_ledger_memory
    from ingestion.silver.writer import reset_local_tables
    from tenancy.rights_authority.rollout import reset_rollout

    reset_rollout()
    request.addfinalizer(reset_rollout)
    reset_in_memory_stores()
    reset_graph_ledger_memory()
    reset_local_tables()
    r = get_imports_repository()
    _reset_graph()
    # Pin the repo accessor so seeding (svc) and the commit path (cm) share one
    # instance regardless of the suite's sys.modules churn.
    monkeypatch.setattr(svc, "get_imports_repository", lambda: r)
    monkeypatch.setattr(cm, "get_imports_repository", lambda: r)
    _install_rights(monkeypatch, SOURCE)
    return r


def _reset_graph():
    """Clear the in-memory graph backend's stores (created lazily on first op)."""
    from shared.graph.graph import get_graph_client

    backend = getattr(get_graph_client(), "_backend", None)
    if backend is not None:
        for name in ("_vertices", "_edges"):
            store = getattr(backend, name, None)
            if hasattr(store, "clear"):
                store.clear()


async def _seed_approved(
    tenant: str = TENANT, *, source_id: str | None = SOURCE
) -> str:
    session = await svc.create_import(
        tenant, created_by="u1", source_id=source_id
    )
    import_id = session["id"]
    await svc.store_file(tenant, import_id, filename="rel.csv", content=CSV, content_type="text/csv")
    await svc.analyze_import(tenant, import_id)
    await svc.set_mapping(tenant, import_id, MAPPING)
    await svc.validate_import(tenant, import_id)
    await svc.approve_import(tenant, import_id, approver="admin1")
    return import_id


class _DecisionRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def record(self, decision, *, identity_key=None):
        row = decision.model_dump(mode="json")
        row["identity_key"] = identity_key
        self.rows[row["decision_id"]] = row
        return row


class _ImportGrantService:
    def __init__(self, grant, *, revoke_on_hold: bool = False):
        self.grant = grant
        self.revoke_on_hold = revoke_on_hold

    async def is_durable(self):
        return True

    async def get_effective_grant(self, tenant_id, source_id):
        grant = self.grant
        status = getattr(getattr(grant, "status", None), "value", None)
        if (
            grant is None
            or grant.tenant_id != tenant_id
            or grant.source_id != source_id
            or status != "active"
            or grant.revoked_at is not None
        ):
            return None
        return grant

    def hold_grant_unrevoked(self, grant_id, *, tenant_id):
        from contextlib import asynccontextmanager
        from connectors.integrations.data_rights.models import GrantStatus

        @asynccontextmanager
        async def _hold():
            if self.revoke_on_hold:
                self.grant = self.grant.model_copy(update={
                    "status": GrantStatus.REVOKED,
                    "revoked_at": "2026-10-11T00:00:00+00:00",
                })
            yield

        return _hold()


def _install_rights(
    monkeypatch,
    grant_source_id: str | None,
    *,
    tenant_lake: bool = True,
    tenant_graph: bool = True,
    tenant_insights: bool = True,
    revoke_on_hold: bool = False,
):
    from connectors.integrations.data_rights.models import DataRightsGrant, GrantStatus
    from ingestion.imports import rights_admission
    from tenancy.rights_authority.resolver import EffectiveRightsResolver
    from tenancy.rights_authority.rollout import configure_rollout

    grant = DataRightsGrant(
        data_rights_grant_id="drg_import_fixture",
        tenant_id=TENANT,
        contract_id="contract-import-fixture",
        source_id=grant_source_id or "unused-import-fixture-source",
        connector_id="csv_import",
        connector_class="tenant_import",
        data_category="customer",
        data_sensitivity="sensitive_pii",
        raw_data_owner="tenant",
        tenant_lake_allowed=tenant_lake,
        tenant_graph_allowed=tenant_graph,
        tenant_insights_allowed=tenant_insights,
        olympus_baseline_allowed=False,
        cross_tenant_aggregate_allowed=False,
        model_training_allowed=False,
        commercial_reuse_allowed=False,
        legal_basis="contract",
        granted_by_user_id="tenant-admin",
        granted_at="2026-10-01T00:00:00+00:00",
        status=GrantStatus.ACTIVE,
        audit_event_id="audit-import-fixture",
    )
    service = _ImportGrantService(
        grant if grant_source_id is not None else None,
        revoke_on_hold=revoke_on_hold,
    )
    decisions = _DecisionRepository()
    resolver = EffectiveRightsResolver(
        grant_loader=lambda tenant_id, source_id: service.get_effective_grant(
            tenant_id, source_id
        ),
        decision_repository=decisions,
    )
    admission = ImportRightsAdmission(resolver=resolver, grant_service=service)
    monkeypatch.setattr(rights_admission, "_import_rights_admission", admission)
    # The import-owned gate is mandatory even when shared graph propagation is
    # disabled; its direct resolver decisions still must be durably stamped.
    configure_rollout("off")
    return service, decisions


# ── pure planners ────────────────────────────────────────────────────────────


def test_build_records_and_plan_graph():
    from ingestion.imports.contracts import FieldMapping

    fields = [FieldMapping(**f) for f in MAPPING]
    rows = [
        {"user_id": "alice", "email": "alice@example.com", "friend_id": "bob"},
        {"user_id": "bob", "email": "bob@example.com", "friend_id": "alice"},
    ]
    records, errors = cm.build_primitive_records(fields, rows)
    assert errors == []
    assert {r["primitive"] for r in records} == {"entity", "identifier", "relationship"}
    vertices, edges = cm.plan_graph(TENANT, records)
    vtypes = {v["vertex_type"] for v in vertices}
    assert {"Entity", "Identifier"} <= vtypes
    etypes = {e["type"] for e in edges}
    assert {"HAS_IDENTIFIER", "RELATED_TO"} <= etypes


def test_build_records_surfaces_transform_errors():
    from ingestion.imports.contracts import FieldMapping

    fields = [FieldMapping(source_column="n", primitive="metric", target_field="value",
                           transform="to_number", required=True)]
    records, errors = cm.build_primitive_records(fields, [{"n": "not-a-number"}])
    assert records == []
    assert errors and errors[0]["code"] == "transform_failed"


# ── commit ───────────────────────────────────────────────────────────────────


async def test_commit_stages_bronze_and_graph(clean):
    from repositories.lake import BronzeRepository
    from shared.graph.graph import get_graph_client

    import_id = await _seed_approved()
    record = await cm.commit_import(TENANT, import_id)
    assert record["status"] == "committed"
    assert record["counts"]["bronze_rows"] == 2
    assert record["counts"]["vertices"] == 4  # 2 entities + 2 identifiers
    assert record["counts"]["edges"] == 4     # 2 has-identifier + 2 related-to

    gc = get_graph_client()
    assert await gc.get_vertex(f"entity:{TENANT}:alice") is not None
    out = await gc.get_edges(f"entity:{TENANT}:alice", direction="out")
    assert any(e.edge_type == "RELATED_TO" and e.to_vertex_id == f"entity:{TENANT}:bob" for e in out)
    # lineage recorded on the edge
    assert all(e.properties.get("import_commit_id") == record["commit_id"] for e in out)

    detail = await svc.get_import(TENANT, import_id)
    assert detail["session"]["status"] == "committed"
    assert set(record["rights_decision_refs"]) == {
        "tenant_lake", "write_tenant_graph", "tenant_insights",
    }
    assert all(
        ref.startswith("rdec_")
        for ref in record["rights_decision_refs"].values()
    )
    bronze_rows = await BronzeRepository(cm.BRONZE_DOMAIN).query_by_source_tag(
        record["commit_id"], tenant_id=TENANT
    )
    assert len(bronze_rows) == 2
    assert all(
        row["rights_decision_refs"] == record["rights_decision_refs"]
        for row in bronze_rows
    )


@pytest.mark.parametrize(
    ("session_source", "grant_source", "tenant_graph", "revoke_on_hold"),
    [
        (None, SOURCE, True, False),
        (SOURCE, None, True, False),
        (SOURCE, SOURCE, False, False),
        ("wrong-source", SOURCE, True, False),
        (SOURCE, SOURCE, True, True),
    ],
    ids=[
        "missing-source", "missing-grant", "denied-use", "wrong-source",
        "revoked-before-write",
    ],
)
async def test_rights_denial_precedes_identity_bronze_and_graph_writes(
    clean, monkeypatch, session_source, grant_source, tenant_graph, revoke_on_hold
):
    from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
    from repositories.lake import BronzeRepository
    from shared.graph.graph import get_graph_client
    from ingestion.silver.writer import _local_tables

    _service, decisions = _install_rights(
        monkeypatch,
        grant_source,
        tenant_graph=tenant_graph,
        revoke_on_hold=revoke_on_hold,
    )
    import_id = await _seed_approved(source_id=session_source)
    identity_calls = []

    async def identity_write_spy(*args, **kwargs):
        identity_calls.append((args, kwargs))
        raise AssertionError("identity write ran before rights admission")

    monkeypatch.setattr(cm, "_register_csv_identity_evidence", identity_write_spy)
    with pytest.raises(ImportRightsDenied):
        await cm.commit_import(TENANT, import_id)

    assert identity_calls == []
    bronze = BronzeRepository(cm.BRONZE_DOMAIN)
    assert await bronze.find_many(filters={"tenant_id": TENANT}, limit=100) == []
    assert await get_graph_client().get_all_vertices() == []
    assert await GraphMutationLedgerRepository().list_records(TENANT) == []
    assert _local_tables.get("silver_import_facts", {}) == {}

    session = await clean.get_session(TENANT, import_id)
    active_commit = session["active_commit_id"]
    attempts = session["rights_admissions"][active_commit]
    assert attempts and attempts[-1]["status"] == "denied"
    persisted_refs = {
        ref
        for attempt in attempts
        for ref in attempt["decision_refs"].values()
    }
    assert persisted_refs
    assert persisted_refs <= decisions.rows.keys()


async def test_rights_refs_survive_commit_replay_and_graph_ledger(clean, monkeypatch):
    from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
    from ingestion.silver.writer import _local_tables

    _service, decisions = _install_rights(monkeypatch, SOURCE)
    import_id = await _seed_approved()
    first = await cm.commit_import(TENANT, import_id)
    second = await cm.replay_import(TENANT, import_id)
    assert first["rights_decision_refs"]["write_tenant_graph"] != (
        second["rights_decision_refs"]["write_tenant_graph"]
    )

    graph_ref_1 = first["rights_decision_refs"]["write_tenant_graph"]
    graph_ref_2 = second["rights_decision_refs"]["write_tenant_graph"]
    rows = await GraphMutationLedgerRepository().list_records(TENANT)
    refs = {row.get("rights_decision_ref") for row in rows}
    assert graph_ref_1 in refs and graph_ref_2 in refs
    assert graph_ref_1 in decisions.rows and graph_ref_2 in decisions.rows

    session = await clean.get_session(TENANT, import_id)
    history = session["rights_admissions"]
    assert first["commit_id"] in history and second["commit_id"] in history
    for record in (first, second):
        attempt_refs = {
            ref
            for attempt in history[record["commit_id"]]
            for ref in attempt["decision_refs"].values()
        }
        assert set(record["rights_decision_refs"].values()) <= attempt_refs

    from repositories.lake import BronzeRepository

    replay_bronze = await BronzeRepository(cm.BRONZE_DOMAIN).query_by_source_tag(
        second["commit_id"], tenant_id=TENANT
    )
    assert len(replay_bronze) == 2
    assert all(
        row["rights_decision_refs"] == second["rights_decision_refs"]
        for row in replay_bronze
    )
    silver_rows = _local_tables.get("silver_import_facts", {}).values()
    for record in (first, second):
        rows_for_commit = [
            row for row in silver_rows if row["commit_id"] == record["commit_id"]
        ]
        assert rows_for_commit
        assert all(
            row["rights_decision_refs"] == record["rights_decision_refs"]
            for row in rows_for_commit
        )


async def test_commit_requires_approved(clean):
    session = await svc.create_import(TENANT)
    with raises_named("ConflictError"):
        await cm.commit_import(TENANT, session["id"])


def _edge_count() -> int:
    from shared.graph.graph import get_graph_client

    backend = getattr(get_graph_client(), "_backend", None)
    return len(getattr(backend, "_edges", []) or [])


async def test_commit_is_idempotent_on_edges(clean):
    """A second stage under a new id adds no duplicate edges (existence-checked)."""
    import_id = await _seed_approved()
    rec1 = await cm.commit_import(TENANT, import_id)
    before = _edge_count()
    # Re-stage the same records under a fresh id directly (bypassing status guard).
    session = await svc.get_import(TENANT, import_id)
    rec2 = await cm._stage_and_mutate(TENANT, import_id, session["session"], "impc_dup")
    assert rec2["counts"]["edges"] == 0  # nothing new to create
    assert _edge_count() == before
    assert rec1["counts"]["edges"] == 4


# ── rollback ─────────────────────────────────────────────────────────────────


async def test_rollback_revokes_edges_and_deletes_bronze(clean):
    from repositories.lake import BronzeRepository
    from shared.graph.graph import get_graph_client

    import_id = await _seed_approved()
    record = await cm.commit_import(TENANT, import_id)
    result = await cm.rollback_import(TENANT, import_id, reason="test rollback")
    assert result["edges_revoked"] == 4
    assert result["bronze_deleted"] == 2
    assert len(result["vertices_deleted"]) == 4
    assert result["vertices_retained"] == []

    gc = get_graph_client()
    live = await gc.get_edges(f"entity:{TENANT}:alice", direction="out")
    assert live == []  # all revoked
    assert await gc.get_vertex(f"entity:{TENANT}:alice") is None
    # Bronze rows for the commit are gone.
    remaining = await BronzeRepository(cm.BRONZE_DOMAIN).query_by_source_tag(
        record["commit_id"], tenant_id=TENANT
    )
    assert remaining == []

    detail = await svc.get_import(TENANT, import_id)
    assert detail["session"]["status"] == "rolled_back"


async def test_rollback_twice_conflicts(clean):
    import_id = await _seed_approved()
    await cm.commit_import(TENANT, import_id)
    await cm.rollback_import(TENANT, import_id)
    with raises_named("ConflictError"):
        await cm.rollback_import(TENANT, import_id)


async def test_over_cap_rollback_preflight_prevents_graph_and_manifest_mutation(clean):
    from repositories.lake import BronzeRepository, SOURCE_TAG_ROLLBACK_CAP
    from shared.graph.graph import get_graph_client

    import_id = await _seed_approved()
    commit = await cm.commit_import(TENANT, import_id)
    bronze = BronzeRepository(cm.BRONZE_DOMAIN)
    for i in range(SOURCE_TAG_ROLLBACK_CAP - 1):
        row_id = f"over-cap-{i}"
        await bronze.insert(row_id, {
            "id": row_id,
            "source_tag": commit["commit_id"],
            "tenant_id": TENANT,
        })

    gc = get_graph_client()
    before_edges = await gc.get_edges(f"entity:{TENANT}:alice", direction="out")
    before_vertex = await gc.get_vertex(f"entity:{TENANT}:alice")

    with pytest.raises(ValueError, match="exceeds safety cap"):
        await cm.rollback_import(TENANT, import_id)

    after_edges = await gc.get_edges(f"entity:{TENANT}:alice", direction="out")
    after_vertex = await gc.get_vertex(f"entity:{TENANT}:alice")
    assert after_edges == before_edges
    assert after_vertex == before_vertex
    assert await clean.list_rollbacks(TENANT, import_id) == []
    detail = await svc.get_import(TENANT, import_id)
    assert detail["session"]["status"] == "committed"


# ── replay ───────────────────────────────────────────────────────────────────


async def test_replay_restages_under_new_commit(clean):
    from shared.graph.graph import get_graph_client

    import_id = await _seed_approved()
    rec1 = await cm.commit_import(TENANT, import_id)
    rec2 = await cm.replay_import(TENANT, import_id)
    assert rec2["commit_id"] != rec1["commit_id"]
    assert rec2.get("replayed") is True
    assert rec2["status"] == "committed"

    gc = get_graph_client()
    live = await gc.get_edges(f"entity:{TENANT}:alice", direction="out")
    # Prior commit's edges revoked, replay's edges live and carrying the new id.
    assert any(e.properties.get("import_commit_id") == rec2["commit_id"] for e in live)


# ── graph preview + tenant isolation + job handler ───────────────────────────


async def test_graph_preview_is_non_mutating(clean):
    from shared.graph.graph import get_graph_client

    import_id = await _seed_approved()
    preview = await cm.graph_preview(TENANT, import_id)
    assert preview["counts"]["vertices"] == 4 and preview["counts"]["edges"] == 4
    assert await get_graph_client().get_all_vertices() == []  # nothing was written


async def test_tenant_isolation(clean):
    import_id = await _seed_approved()
    await cm.commit_import(TENANT, import_id)
    with raises_named("NotFoundError"):
        await cm.rollback_import(OTHER, import_id)


async def test_commit_job_handler(clean):
    from workers.jobs.handlers import JobContext

    # Call the module-level handler directly (via this test's own `cm`), not the
    # global HANDLER_REGISTRY — a registry closure may be bound to a different
    # module identity under suite churn and miss the seeded session.
    import_id = await _seed_approved()

    async def _noop(*_a, **_k):
        return True

    ctx = JobContext(job_id="j1", tenant_id=TENANT, correlation_id="c1",
                     worker_id="test_worker",
                     heartbeat=_noop, emit_event=_noop)
    outcome = await cm.commit_job_handler({"import_id": import_id}, ctx)
    assert outcome.status == "succeeded"
    assert outcome.result["counts"]["edges"] == 4


def test_handlers_are_registered():
    from ingestion.imports.commit import register_import_handlers
    from workers.jobs.handlers import HANDLER_REGISTRY

    register_import_handlers()
    assert "import.commit" in HANDLER_REGISTRY and "import.replay" in HANDLER_REGISTRY


async def test_vertex_gc_retains_shared_or_currently_referenced_vertices(clean):
    from shared.graph.graph import Edge, get_graph_client

    import_id = await _seed_approved()
    record = await cm.commit_import(TENANT, import_id)
    graph = get_graph_client()
    shared_id = f"entity:{TENANT}:alice"
    await graph.add_edge(Edge(
        edge_type="CURRENT_REFERENCE",
        from_vertex_id=shared_id,
        to_vertex_id=f"external:{TENANT}:live",
        properties={"tenant_id": TENANT, "import_commit_id": "another-commit"},
    ))

    result = await cm.rollback_import(TENANT, import_id, reason="shared safety")

    assert shared_id not in result["vertices_deleted"]
    retained = {item["vertex_id"]: item["reason"] for item in result["vertices_retained"]}
    assert retained[shared_id] == "active_reference"
    assert await graph.get_vertex(shared_id) is not None


async def test_vertex_gc_is_idempotent_for_missing_vertices(clean):
    graph = __import__(
        "shared.graph.graph", fromlist=["get_graph_client"]
    ).get_graph_client()
    removed, reason = await graph.delete_vertex_if_orphaned(
        "missing-vertex", TENANT, "missing-commit"
    )
    assert removed is False
    assert reason == "not_found"


async def test_vertex_gc_retains_preexisting_vertex_without_foreign_edges(clean):
    from shared.graph.graph import Vertex, get_graph_client

    graph = get_graph_client()
    shared_id = f"entity:{TENANT}:alice"
    await graph.upsert_vertex(Vertex(
        vertex_type="Entity",
        vertex_id=shared_id,
        properties={"tenant_id": TENANT, "origin": "preexisting"},
    ))

    import_id = await _seed_approved()
    await cm.commit_import(TENANT, import_id)
    result = await cm.rollback_import(TENANT, import_id, reason="preserve original")

    retained = {item["vertex_id"]: item["reason"] for item in result["vertices_retained"]}
    assert retained[shared_id] == "ownership_changed"
    vertex = await graph.get_vertex(shared_id)
    assert vertex is not None
    assert vertex.properties["origin"] == "preexisting"
