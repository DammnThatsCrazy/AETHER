"""Silver projection of committed tenant imports.

Proves the commit fans out its primitive records into silver_import_facts: the
projector builds one row per (commit, file, row, primitive) with a replay-safe
idempotency key, the writer persists idempotently, and a real commit reports the
Silver row count and populates the local Silver table.
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
from ingestion.silver.projectors.import_projector import (  # noqa: E402
    SILVER_IMPORT_TABLE,
    ImportProjector,
)

TENANT = "tenant-silver"
SOURCE = "tenant-silver-source"

CSV = (
    b"user_id,email,friend_id\n"
    b"alice,alice@example.com,bob\n"
    b"bob,bob@example.com,alice\n"
)
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
    assert type(excinfo.value).__name__ in names


# ── pure projector ───────────────────────────────────────────────────────────


def test_project_records_row_shape():
    records = [
        {"primitive": "entity", "row": 0, "fields": {"external_id": "e1"}, "file_id": "f1"},
        {"primitive": "identifier", "row": 0, "fields": {"value": "e1@x"}, "file_id": "f1"},
    ]
    result = ImportProjector().project_records(
        tenant_id="t1", commit_id="impc_x", import_id="imp1",
        mapping_version=1, occurred_at="2026-07-20T00:00:00+00:00", records=records,
        rights_decision_refs={"tenant_lake": "rdec_lake", "tenant_insights": "rdec_insights"},
    )
    assert result.table == SILVER_IMPORT_TABLE
    assert len(result.rows) == 2
    r0 = result.rows[0]
    assert r0["commit_id"] == "impc_x" and r0["primitive"] == "entity"
    assert r0["idempotency_key"] == "impc_x:f1:0:entity"
    assert r0["bronze_record_id"] == "f1:0"
    assert r0["payload"] == {"external_id": "e1"}
    assert r0["rights_decision_refs"] == {
        "tenant_lake": "rdec_lake", "tenant_insights": "rdec_insights"
    }


async def test_writer_persists_and_dedupes():
    from ingestion.silver.writer import SilverFactWriter, _local_tables, reset_local_tables

    reset_local_tables()
    result = ImportProjector().project_records(
        tenant_id="t1", commit_id="impc_y", import_id="imp1", mapping_version=1,
        occurred_at="2026-07-20T00:00:00+00:00",
        records=[{"primitive": "entity", "row": 0, "fields": {}, "file_id": "f1"}],
    )
    n = await SilverFactWriter().persist([result])
    assert n == 1
    assert len(_local_tables.get(SILVER_IMPORT_TABLE, {})) == 1
    # Re-persisting the same key is a no-op in the local first-write-wins store.
    await SilverFactWriter().persist([result])
    assert len(_local_tables[SILVER_IMPORT_TABLE]) == 1


# ── end-to-end through commit ────────────────────────────────────────────────


@pytest.fixture()
def clean(monkeypatch, request):
    from repositories.imports_repo import get_imports_repository
    from ingestion.silver.writer import reset_local_tables
    from repositories.repos import reset_in_memory_stores
    from repositories.graph_mutation_ledger import reset_graph_ledger_memory
    from tenancy.rights_authority.rollout import reset_rollout
    from shared.graph.graph import get_graph_client

    reset_rollout()
    request.addfinalizer(reset_rollout)
    reset_in_memory_stores()
    reset_graph_ledger_memory()
    r = get_imports_repository()
    reset_local_tables()
    backend = getattr(get_graph_client(), "_backend", None)
    if backend is not None:
        for name in ("_vertices", "_edges"):
            store = getattr(backend, name, None)
            if hasattr(store, "clear"):
                store.clear()
    monkeypatch.setattr(svc, "get_imports_repository", lambda: r)
    monkeypatch.setattr(cm, "get_imports_repository", lambda: r)
    return r


async def _seed_approved() -> str:
    from connectors.integrations.data_rights.models import DataRightsGrant, GrantStatus
    from connectors.integrations.data_rights.service import data_rights_service

    grant = DataRightsGrant(
        data_rights_grant_id="drg_silver_fixture",
        tenant_id=TENANT,
        contract_id="contract-silver-fixture",
        source_id=SOURCE,
        connector_id="csv_import",
        connector_class="tenant_import",
        data_category="customer",
        data_sensitivity="sensitive_pii",
        raw_data_owner="tenant",
        tenant_lake_allowed=True,
        tenant_graph_allowed=True,
        tenant_insights_allowed=True,
        olympus_baseline_allowed=False,
        cross_tenant_aggregate_allowed=False,
        model_training_allowed=False,
        commercial_reuse_allowed=False,
        legal_basis="contract",
        granted_by_user_id="tenant-admin",
        granted_at="2026-10-01T00:00:00+00:00",
        status=GrantStatus.ACTIVE,
        audit_event_id="audit-silver-fixture",
    )
    await data_rights_service._repository.create(grant, actor="tenant-admin")
    session = await svc.create_import(TENANT, created_by="u1", source_id=SOURCE)
    import_id = session["id"]
    await svc.store_file(TENANT, import_id, filename="rel.csv", content=CSV, content_type="text/csv")
    await svc.analyze_import(TENANT, import_id)
    await svc.set_mapping(TENANT, import_id, MAPPING)
    await svc.validate_import(TENANT, import_id)
    await svc.approve_import(TENANT, import_id, approver="admin1")
    return import_id


async def test_commit_populates_silver(clean):
    from ingestion.silver.writer import _local_tables
    from repositories.lake import BronzeRepository

    import_id = await _seed_approved()
    record = await cm.commit_import(TENANT, import_id)
    # 2 rows x 3 primitives (entity, identifier, relationship) = 6 records.
    assert record["counts"]["silver_rows"] == 6
    facts = _local_tables.get(SILVER_IMPORT_TABLE, {})
    assert len([k for k in facts if k.startswith(f"{TENANT}:")]) == 6
    bronze = await BronzeRepository(cm.BRONZE_DOMAIN).query_by_source_tag(
        record["commit_id"], tenant_id=TENANT
    )
    bronze_ids = {row["id"] for row in bronze}
    # every fact carries the commit lineage
    assert all(v["commit_id"] == record["commit_id"] for v in facts.values())
    assert all(v["rights_decision_refs"] == record["rights_decision_refs"] for v in facts.values())
    assert all(v["bronze_record_id"] in bronze_ids for v in facts.values())
