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

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from services.imports import commit as cm  # noqa: E402
from services.imports import service as svc  # noqa: E402

TENANT = "tenant-commit"
OTHER = "tenant-other"

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
def clean():
    from repositories.import_files import get_import_file_repository
    from repositories.imports_repo import get_imports_repository
    from repositories.lake import BronzeRepository
    from shared.graph.graph import get_graph_client

    r = get_imports_repository()
    for attr in ("sessions", "schemas", "mappings", "templates", "validations",
                 "row_errors", "commits", "rollbacks"):
        getattr(r, attr)._store.clear()
    get_import_file_repository()._store.clear()
    BronzeRepository(cm.BRONZE_DOMAIN)._store.clear()
    _reset_graph()
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


async def _seed_approved(tenant: str = TENANT) -> str:
    session = await svc.create_import(tenant, created_by="u1")
    import_id = session["id"]
    await svc.store_file(tenant, import_id, filename="rel.csv", content=CSV, content_type="text/csv")
    await svc.analyze_import(tenant, import_id)
    await svc.set_mapping(tenant, import_id, MAPPING)
    await svc.validate_import(tenant, import_id)
    await svc.approve_import(tenant, import_id, approver="admin1")
    return import_id


# ── pure planners ────────────────────────────────────────────────────────────


def test_build_records_and_plan_graph():
    from services.imports.contracts import FieldMapping

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
    from services.imports.contracts import FieldMapping

    fields = [FieldMapping(source_column="n", primitive="metric", target_field="value",
                           transform="to_number", required=True)]
    records, errors = cm.build_primitive_records(fields, [{"n": "not-a-number"}])
    assert records == []
    assert errors and errors[0]["code"] == "transform_failed"


# ── commit ───────────────────────────────────────────────────────────────────


async def test_commit_stages_bronze_and_graph(clean):
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

    gc = get_graph_client()
    live = await gc.get_edges(f"entity:{TENANT}:alice", direction="out")
    assert live == []  # all revoked
    # Bronze rows for the commit are gone.
    remaining = await BronzeRepository(cm.BRONZE_DOMAIN).query_by_source_tag(record["commit_id"])
    assert remaining == []

    detail = await svc.get_import(TENANT, import_id)
    assert detail["session"]["status"] == "rolled_back"


async def test_rollback_twice_conflicts(clean):
    import_id = await _seed_approved()
    await cm.commit_import(TENANT, import_id)
    await cm.rollback_import(TENANT, import_id)
    with raises_named("ConflictError"):
        await cm.rollback_import(TENANT, import_id)


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
    from services.imports.commit import register_import_handlers
    from services.jobs.handlers import HANDLER_REGISTRY, JobContext

    register_import_handlers()
    import_id = await _seed_approved()

    async def _noop(*_a, **_k):
        return True

    ctx = JobContext(job_id="j1", tenant_id=TENANT, correlation_id="c1",
                     heartbeat=_noop, emit_event=_noop)
    outcome = await HANDLER_REGISTRY["import.commit"]({"import_id": import_id}, ctx)
    assert outcome.status == "succeeded"
    assert outcome.result["counts"]["edges"] == 4
