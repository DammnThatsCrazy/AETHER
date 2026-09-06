"""GraphSnapshotRef canonical-primitive importability test (Phase 2, risk360/fraud360).

``services/operational_intelligence/models.py`` is the canonical home for the
canonical primitives (``EntityRef``, ``EvidenceRef``, …). Phase 2 adds
``GraphSnapshotRef`` there so the risk360 / fraud360 projection contracts
(whose registry ``inputRefs`` already declare ``GraphSnapshotRef``) can import
one shared definition instead of re-declaring their own.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.operational_intelligence.models import (  # noqa: E402
    EntityRef,
    EvidenceRef,
    GraphSnapshotRef,
)


def test_graph_snapshot_ref_importable_from_canonical_home():
    """GraphSnapshotRef lives beside EvidenceRef/EntityRef and is constructible."""
    ref = GraphSnapshotRef(graph_snapshot_id="snap-1")
    assert ref.graph_snapshot_id == "snap-1"
    assert ref.asOf is None  # asOf is optional


def test_graph_snapshot_ref_accepts_as_of():
    ref = GraphSnapshotRef(
        graph_snapshot_id="snap-2",
        asOf="2026-01-01T00:00:00Z",
    )
    assert ref.asOf == "2026-01-01T00:00:00Z"


def test_graph_snapshot_ref_required_field_enforced():
    """graph_snapshot_id is required; a snapshot ref without it is a contract error."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GraphSnapshotRef(asOf="2026-01-01T00:00:00Z")  # type: ignore[call-arg]


def test_sibling_canonical_primitives_still_importable():
    """The canonical-primitives block stays cohesive."""
    entity = EntityRef(kind="agent", id="ent-1")
    assert entity.id == "ent-1"
    evidence = EvidenceRef(id="ev-1", type="transaction", source="fraud_evaluator")
    assert evidence.type == "transaction"
    graph = GraphSnapshotRef(graph_snapshot_id="snap-3")
    assert graph.graph_snapshot_id == "snap-3"
