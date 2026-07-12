"""Tests for the DSR subject / artifact impact indexes (prompt §3.12)."""
from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores

from services.dsr_propagation.indexes import (
    ArtifactIndex,
    DSRArtifactIndexRepository,
    DSRSubjectIndexRepository,
    SubjectIndex,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()


# ── SubjectIndex: find_impacted across components ─────────────────────────────

async def test_subject_index_find_impacted_across_components():
    idx = SubjectIndex()
    await idx.record_subject_ref("t1", "user:alice", "identity_aliases", "alias_1")
    await idx.record_subject_ref("t1", "user:alice", "identity_aliases", "alias_2")
    await idx.record_subject_ref("t1", "user:alice", "feature_rows", "feat_1")
    await idx.record_subject_ref("t1", "user:alice", "graph_edges", "edge_9")
    # A different subject must not bleed in.
    await idx.record_subject_ref("t1", "user:bob", "feature_rows", "feat_bob")

    impacted = await idx.find_impacted("t1", "user:alice")
    assert impacted == {
        "feature_rows": ["feat_1"],
        "graph_edges": ["edge_9"],
        "identity_aliases": ["alias_1", "alias_2"],  # deduped + sorted
    }


async def test_subject_index_is_idempotent():
    idx = SubjectIndex()
    await idx.record_subject_ref("t1", "user:alice", "feature_rows", "feat_1")
    await idx.record_subject_ref("t1", "user:alice", "feature_rows", "feat_1")
    impacted = await idx.find_impacted("t1", "user:alice")
    assert impacted == {"feature_rows": ["feat_1"]}


async def test_subject_index_unknown_component_rejected():
    idx = SubjectIndex()
    with pytest.raises(Exception):
        await idx.record_subject_ref("t1", "user:alice", "not_a_component", "r1")


async def test_subject_index_requires_identifiers():
    idx = SubjectIndex()
    with pytest.raises(Exception):
        await idx.record_subject_ref("", "user:alice", "feature_rows", "r1")
    with pytest.raises(Exception):
        await idx.record_subject_ref("t1", "", "feature_rows", "r1")
    with pytest.raises(Exception):
        await idx.record_subject_ref("t1", "user:alice", "feature_rows", "")


async def test_subject_index_empty_for_unknown_subject():
    idx = SubjectIndex()
    assert await idx.find_impacted("t1", "nobody") == {}


# ── SubjectIndex: tenant isolation ────────────────────────────────────────────

async def test_subject_index_tenant_isolation():
    idx = SubjectIndex()
    await idx.record_subject_ref("t1", "user:shared", "feature_rows", "feat_t1")
    await idx.record_subject_ref("t2", "user:shared", "feature_rows", "feat_t2")

    assert await idx.find_impacted("t1", "user:shared") == {"feature_rows": ["feat_t1"]}
    assert await idx.find_impacted("t2", "user:shared") == {"feature_rows": ["feat_t2"]}
    # A tenant with nothing recorded sees nothing.
    assert await idx.find_impacted("t3", "user:shared") == {}


# ── ArtifactIndex: artifacts_for_subject + subjects_for_artifact ──────────────

async def test_artifact_index_forward_and_reverse():
    art = ArtifactIndex()
    await art.record_artifact(
        "t1", "export_2024", "exports", ["user:alice", "user:bob"],
    )
    await art.record_artifact(
        "t1", "model_v3", "model_artifacts", ["user:alice"],
    )

    alice_artifacts = await art.artifacts_for_subject("t1", "user:alice")
    assert alice_artifacts == [
        {"artifact_id": "export_2024", "kind": "exports"},
        {"artifact_id": "model_v3", "kind": "model_artifacts"},
    ]
    bob_artifacts = await art.artifacts_for_subject("t1", "user:bob")
    assert bob_artifacts == [{"artifact_id": "export_2024", "kind": "exports"}]

    # Reverse: which subjects does an artifact embed.
    assert await art.subjects_for_artifact("t1", "export_2024") == [
        "user:alice", "user:bob",
    ]
    assert await art.subjects_for_artifact("t1", "model_v3") == ["user:alice"]


async def test_artifact_index_idempotent_and_dedupes():
    art = ArtifactIndex()
    await art.record_artifact("t1", "export_2024", "exports", ["user:alice"])
    await art.record_artifact("t1", "export_2024", "exports", ["user:alice"])
    assert await art.artifacts_for_subject("t1", "user:alice") == [
        {"artifact_id": "export_2024", "kind": "exports"},
    ]


async def test_artifact_index_requires_identifiers():
    art = ArtifactIndex()
    with pytest.raises(Exception):
        await art.record_artifact("", "a1", "exports", ["user:alice"])
    with pytest.raises(Exception):
        await art.record_artifact("t1", "", "exports", ["user:alice"])
    with pytest.raises(Exception):
        await art.record_artifact("t1", "a1", "", ["user:alice"])
    # Empty / falsy subject_refs are skipped, not indexed.
    stored = await art.record_artifact("t1", "a1", "exports", ["", None])  # type: ignore[list-item]
    assert stored == []
    assert await art.subjects_for_artifact("t1", "a1") == []


async def test_artifact_index_tenant_isolation():
    art = ArtifactIndex()
    await art.record_artifact("t1", "export_shared", "exports", ["user:alice"])
    await art.record_artifact("t2", "export_shared", "exports", ["user:alice"])

    assert await art.artifacts_for_subject("t1", "user:alice") == [
        {"artifact_id": "export_shared", "kind": "exports"},
    ]
    # t2 has its own row; t3 sees nothing.
    assert await art.artifacts_for_subject("t2", "user:alice") == [
        {"artifact_id": "export_shared", "kind": "exports"},
    ]
    assert await art.artifacts_for_subject("t3", "user:alice") == []
    assert await art.subjects_for_artifact("t3", "export_shared") == []


async def test_index_repository_table_names():
    assert DSRSubjectIndexRepository().table_name == "dsr_subject_index"
    assert DSRArtifactIndexRepository().table_name == "dsr_artifact_index"
