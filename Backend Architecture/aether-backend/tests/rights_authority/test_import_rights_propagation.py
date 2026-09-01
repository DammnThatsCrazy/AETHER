"""Import projections preserve the source Bronze rights receipt."""

from __future__ import annotations

from services.imports.commit import plan_graph
from services.silver.projectors.import_projector import ImportProjector
from shared.graph.graph import Edge
from shared.graph.mutation_intents import edge_intent


def _rights() -> dict:
    return {
        "rights_decision_refs": ["rdec_store"],
        "envelope_ref": "rae_source",
        "policy_set_ref": "rps_tenant",
        "source_grant_ref": "drg_source",
        "lineage_root_refs": ["sdk_event:event-1:"],
    }


def test_import_graph_plan_flattens_receipt_references() -> None:
    vertices, edges = plan_graph(
        "tenant-1",
        [
            {
                "primitive": "entity",
                "row": 0,
                "fields": {"external_id": "customer-1", "entity_type": "Customer"},
                "rights": _rights(),
            },
            {
                "primitive": "relationship",
                "row": 0,
                "fields": {"from_ref": "customer-1", "to_ref": "customer-2"},
                "rights": _rights(),
            },
        ],
    )

    assert vertices[0]["properties"]["rights_envelope_id"] == "rae_source"
    assert vertices[0]["properties"]["rights_decision_id"] == "rdec_store"
    assert edges[0]["rights"]["rights_source_grant_refs"] == ["drg_source"]


def test_import_silver_projection_carries_receipt_and_graph_intent_reads_it() -> None:
    receipt = _rights()
    result = ImportProjector().project_records(
        tenant_id="tenant-1",
        commit_id="commit-1",
        import_id="import-1",
        mapping_version=1,
        occurred_at="2026-09-01T00:00:00+00:00",
        records=[
            {
                "file_id": "file-1",
                "row": 0,
                "primitive": "entity",
                "fields": {"external_id": "customer-1"},
                "rights": receipt,
            }
        ],
    )

    assert result.rows[0]["rights"] == receipt
    intent = edge_intent(
        Edge(
            edge_type="RELATED_TO",
            from_vertex_id="entity:tenant-1:customer-1",
            to_vertex_id="entity:tenant-1:customer-2",
            properties={
                "tenant_id": "tenant-1",
                "rights_envelope_id": "rae_source",
                "rights_decision_id": "rdec_graph",
                "rights_policy_set_ref": "rps_tenant",
                "rights_source_grant_refs": ["drg_source"],
            },
        ),
        tenant_id="tenant-1",
    )
    assert intent.rights_envelope_id == "rae_source"
    assert intent.rights_decision_id == "rdec_graph"
    assert intent.rights_source_grant_refs == ["drg_source"]
