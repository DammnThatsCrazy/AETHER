"""M6 REGISTERED-edge honesty (Social360 + Relationship Fidelity).

Milestone M6 registers every relationship predicate to a live graph edge. This
suite keeps the M1 honesty doctrine fail-closed in the other direction too:
after M6, NO predicate may remain PENDING_M6_REGISTRATION and every predicate
that claims REGISTERED must reference a real ``shared.graph.graph.EdgeType``
member that is mapped to a non-EXCLUDED relationship layer. It complements the
generated-twin parity test (``tests/contracts/test_relationship_predicate_registry_parity.py``),
which re-verifies the twins once the integrator regenerates them.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.graph.graph import EdgeType
from shared.graph.relationship_layers import RelationshipLayer, _EDGE_LAYER_MAP

# relationship_spine tests live at <root>/Backend Architecture/aether-backend/tests/relationship_spine
REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY = REPO_ROOT / "packages" / "shared" / "contracts" / "relationship-predicate-registry.json"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _edge_values() -> set[str]:
    return {v for k, v in vars(EdgeType).items() if not k.startswith("_") and isinstance(v, str)}


def test_all_twenty_predicates_registered():
    """M6 registers the full catalog: 20/20 REGISTERED, none PENDING."""
    preds = _registry()["predicates"]
    assert len(preds) == 20
    states = {p["predicate"]: p["graphRegistrationState"] for p in preds}
    assert all(s == "REGISTERED" for s in states.values()), states
    assert all(p.get("graphEdgeType") for p in preds)


def test_registered_edges_resolve_to_live_edge_types():
    """Every REGISTERED predicate references a real EdgeType member."""
    values = _edge_values()
    for pred in _registry()["predicates"]:
        edge = pred["graphEdgeType"]
        assert pred["graphRegistrationState"] == "REGISTERED"
        assert isinstance(edge, str) and edge in values, (
            f"{pred['predicate']} claims REGISTERED but {edge!r} is not an EdgeType"
        )


def test_registered_edges_are_not_excluded_from_relationship_layers():
    """No REGISTERED social edge may sit in the EXCLUDED bucket."""
    for pred in _registry()["predicates"]:
        edge = pred["graphEdgeType"]
        assert edge in _EDGE_LAYER_MAP, f"{edge!r} has no relationship-layer entry"
        assert _EDGE_LAYER_MAP[edge] != RelationshipLayer.EXCLUDED, (
            f"{edge!r} ({pred['predicate']}) is EXCLUDED -- a social relationship edge must be in H2H/H2A/A2H/A2A"
        )


def test_name_collisions_disambiguated():
    """The two predicate/EdgeType name collisions resolve to distinct edges."""
    by_pred = {p["predicate"]: p["graphEdgeType"] for p in _registry()["predicates"]}
    # H2A protocol edge INTERACTS_WITH already exists; social one is distinct.
    assert by_pred["INTERACTS_WITH"] == "SOCIAL_INTERACTS_WITH"
    # H2A service-plan SUBSCRIBES_TO already exists; social one is distinct.
    assert by_pred["SUBSCRIBES_TO"] == "SOCIAL_SUBSCRIBES_TO"
    # FOLLOWS kept its M1 disambiguation.
    assert by_pred["FOLLOWS"] == "FOLLOWS_SOCIAL"
    values = _edge_values()
    assert by_pred["INTERACTS_WITH"] in values
    assert by_pred["SUBSCRIBES_TO"] in values
    # The social edges are distinct members (never reusing the H2A names).
    assert "SOCIAL_INTERACTS_WITH" in values
    assert "SOCIAL_SUBSCRIBES_TO" in values
