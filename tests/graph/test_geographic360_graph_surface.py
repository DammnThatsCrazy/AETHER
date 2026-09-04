"""Graph-surface tests for the geographic360 location-fact edges (G4.2).

Every ``LocationFact`` resolution target surfaces as a typed, evidence-carrying
edge: region -> ``LOCATED_AT``, place -> ``OBSERVED_IN``, jurisdiction ->
``UNDER_JURISDICTION``. The new EdgeTypes must be classified (EXCLUDED, with
unclassified edges still erroring in strict mode), the assembled edges must
carry the location provenance keys + ``EvidenceRef`` ids, and precision must
never exceed evidence (``precise`` needs a coordinate; ``coarse_cell`` needs
cell evidence) with unknown vocabulary failing closed.
"""

from __future__ import annotations

import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    original = list(sys.path)
    for prefix in ("shared", "services", "config"):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    if "jwt" not in sys.modules:
        sys.modules["jwt"] = types.SimpleNamespace(
            encode=lambda *a, **kw: "stub",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception,
                ExpiredSignatureError=Exception,
                InvalidTokenError=Exception,
            ),
        )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


@contextmanager
def geo_surface():
    """backend_path() plus the surface module + models imported once."""
    with backend_path():
        from services.geo.location_edges import (  # noqa: WPS433
            LocationFactValidationError,
            build_location_edge_intents,
            validate_location_fact,
        )
        from shared.geo.models import (  # noqa: WPS433
            Coordinate,
            Jurisdiction,
            LocationFact,
            Place,
            Region,
        )
        from shared.graph.graph import EdgeType, VertexType  # noqa: WPS433
        from shared.graph.relationship_layers import (  # noqa: WPS433
            RelationshipLayer,
            classify_edge_type,
        )

        yield {
            "LocationFactValidationError": LocationFactValidationError,
            "build_location_edge_intents": build_location_edge_intents,
            "validate_location_fact": validate_location_fact,
            "Coordinate": Coordinate,
            "Jurisdiction": Jurisdiction,
            "LocationFact": LocationFact,
            "Place": Place,
            "Region": Region,
            "EdgeType": EdgeType,
            "VertexType": VertexType,
            "RelationshipLayer": RelationshipLayer,
            "classify_edge_type": classify_edge_type,
        }


def _fact(geo, **overrides) -> object:
    kwargs: dict = {
        "location_id": "loc-1",
        "tenant_id": "t1",
        "subject_type": "entity",
        "subject_id": "e-1",
        "role": "primary_residence",
        "precision_class": "region",
        "precision_state": "full",
        "observed_at": None,
        "provider": "tenant_supplied",
        "evidence_refs": ["ev-1"],
    }
    kwargs.update(overrides)
    return geo["LocationFact"](**kwargs)


def test_new_edge_types_classified_excluded() -> None:
    """LOCATED_AT / OBSERVED_IN / UNDER_JURISDICTION classify to EXCLUDED."""
    with geo_surface() as geo:
        classify = geo["classify_edge_type"]
        for edge_type in (
            geo["EdgeType"].LOCATED_AT,
            geo["EdgeType"].OBSERVED_IN,
            geo["EdgeType"].UNDER_JURISDICTION,
        ):
            assert classify(edge_type) == geo["RelationshipLayer"].EXCLUDED


def test_new_vertex_types_exist() -> None:
    """PLACE / REGION / JURISDICTION are first-class vertex kinds."""
    with geo_surface() as geo:
        assert geo["VertexType"].PLACE == "Place"
        assert geo["VertexType"].REGION == "Region"
        assert geo["VertexType"].JURISDICTION == "Jurisdiction"


def test_unclassified_edge_type_still_errors_in_strict_mode() -> None:
    """An unknown edge type raises, never silently defaults, in strict mode."""
    with geo_surface() as geo:
        import shared.graph.relationship_layers as rl  # noqa: PLC0415

        original = rl._is_strict
        rl._is_strict = lambda: True
        try:
            with pytest.raises(rl.UnknownEdgeTypeError):
                rl.classify_edge_type("LOCATED_AT_NO_SUCH_VOCAB_EDGE")
        finally:
            rl._is_strict = original


def test_validate_location_fact_fails_closed_on_unknown_vocabulary() -> None:
    """Unknown role / precision_class / region_type / precision_state rejected."""
    with geo_surface() as geo:
        validate = geo["validate_location_fact"]
        for field, bad in (
            ("role", "orbiting_moon"),
            ("precision_class", "street_level"),
            ("region_type", "dungeon"),
            ("precision_state", "silently_coarsened"),
        ):
            with pytest.raises(geo["LocationFactValidationError"]):
                validate(_fact(geo, **{field: bad}))


def test_precision_never_exceeds_evidence() -> None:
    """'precise' needs a coordinate; 'coarse_cell' needs cell/coordinate."""
    with geo_surface() as geo:
        validate = geo["validate_location_fact"]
        # precise without a coordinate is rejected.
        with pytest.raises(geo["LocationFactValidationError"]):
            validate(_fact(geo, precision_class="precise"))
        # precise with a coordinate passes.
        validate(
            _fact(
                geo,
                precision_class="precise",
                coordinate=geo["Coordinate"](latitude=45.5, longitude=-122.6),
            )
        )
        # coarse_cell without cell/coordinate is rejected; with a cell passes.
        with pytest.raises(geo["LocationFactValidationError"]):
            validate(_fact(geo, precision_class="coarse_cell"))
        validate(
            _fact(
                geo,
                precision_class="coarse_cell",
                coarse_cell="8928308280fffffff",
            )
        )


def test_build_edges_emits_one_typed_edge_per_resolution_target() -> None:
    """region -> LOCATED_AT, place -> OBSERVED_IN, jurisdiction -> UNDER_JURISDICTION."""
    with geo_surface() as geo:
        fact = _fact(
            geo,
            role="observed_presence",
            region=geo["Region"](
                region_id="r-us-or", region_type="admin_region", name="Oregon"
            ),
            place=geo["Place"](
                place_id="p-1",
                name="Pioneer Courthouse Square",
                region_type="locality",
                country_code="US",
            ),
            jurisdiction=geo["Jurisdiction"](
                jurisdiction_id="j-us",
                name="United States",
                kind="country",
                iso_codes=("US",),
            ),
        )
        build = geo["build_location_edge_intents"]
        intents = build(fact, tenant_id="t1")
        types_seen = [i.edge.edge_type for i in intents]
        assert types_seen == [
            geo["EdgeType"].LOCATED_AT,
            geo["EdgeType"].OBSERVED_IN,
            geo["EdgeType"].UNDER_JURISDICTION,
        ]
        assert [i.edge.to_vertex_id for i in intents] == ["r-us-or", "p-1", "j-us"]
        assert all(i.subject_id == "e-1" for i in intents)


def test_build_edges_carry_evidence_and_provenance() -> None:
    """Edges carry evidence_refs + the registered geographic provenance keys."""
    with geo_surface() as geo:
        fact = _fact(
            geo,
            region=geo["Region"](
                region_id="r-us-or",
                region_type="admin_region",
                name="Oregon",
            ),
            coarse_cell="8928308280fffffff",
            evidence_refs=["ev-1", "ev-2"],
        )
        build = geo["build_location_edge_intents"]
        (intent,) = build(fact, tenant_id="t1")
        props = intent.edge.properties
        assert props["tenant_id"] == "t1"
        assert props["location_role"] == "primary_residence"
        assert props["precision_class"] == "region"
        assert props["precision_state"] == "full"
        assert props["region_type"] == "admin_region"
        assert props["coarse_cell"] == "8928308280fffffff"
        assert props["evidence_refs"] == ["ev-1", "ev-2"]
        assert intent.evidence_refs == ["ev-1", "ev-2"]
        # Classification holds for the assembled edge's type.
        classify = geo["classify_edge_type"]
        assert classify(intent.edge.edge_type) == geo["RelationshipLayer"].EXCLUDED


def test_fact_without_resolution_target_assembles_nothing() -> None:
    """A bare-coordinate fact (no named target) assembles no edge."""
    with geo_surface() as geo:
        fact = _fact(
            geo,
            precision_class="precise",
            coordinate=geo["Coordinate"](latitude=45.5, longitude=-122.6),
        )
        build = geo["build_location_edge_intents"]
        assert build(fact, tenant_id="t1") == []


def test_build_requires_a_subject_id() -> None:
    """No subject id on the fact and none passed -> fail closed, no edge."""
    with geo_surface() as geo:
        fact = _fact(
            geo,
            subject_id=None,
            region=geo["Region"](
                region_id="r-us-or", region_type="admin_region", name="Oregon"
            ),
        )
        build = geo["build_location_edge_intents"]
        with pytest.raises(geo["LocationFactValidationError"]):
            build(fact, tenant_id="t1")


def test_invalid_fact_never_assembles() -> None:
    """Validation runs before assembly — an invalid fact yields no edge."""
    with geo_surface() as geo:
        fact = _fact(
            geo,
            precision_class="precise",  # no coordinate -> invalid
            region=geo["Region"](
                region_id="r-us-or", region_type="admin_region", name="Oregon"
            ),
        )
        build = geo["build_location_edge_intents"]
        with pytest.raises(geo["LocationFactValidationError"]):
            build(fact, tenant_id="t1")
