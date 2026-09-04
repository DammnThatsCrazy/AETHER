"""Projection-engine lens tests (A8): lens registry, lens set, composition.

Covers the lens-registry singleton (backed by the generated twin), lens-set
construction/validation, and the composition algebra (identity, idempotence,
order stability, disparate-grain capability drops) with the typed conflict
classes and their resolutions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.projection_engine.conflict import (  # noqa: E402
    ConflictClass,
    ConflictResolution,
    LensConflict,
    LensNotFound,
)
from shared.projection_engine.lens_composition import compose_lenses  # noqa: E402
from shared.projection_engine.lens_registry import LensRegistry, lens_registry  # noqa: E402
from shared.projection_engine.lens_set import LensSet  # noqa: E402


def test_registry_is_generated_and_sorted() -> None:
    """The singleton is backed by the generated lens registry (28 day-1 lenses)."""
    ids = lens_registry.ids()
    assert "standard" in ids
    assert len(lens_registry.list()) == 28
    assert ids == tuple(sorted(ids))


def test_standard_is_the_default_base() -> None:
    descriptor = lens_registry.get("standard")
    assert descriptor.kind == "base"
    assert descriptor.base_lens is None
    assert descriptor.default is True
    assert lens_registry.default_base() == "standard"


def test_overlays_declare_the_base() -> None:
    for lens_id in ("economic", "outcome", "infrastructure", "evidence", "temporal"):
        descriptor = lens_registry.get(lens_id)
        assert descriptor.kind == "overlay"
        assert descriptor.base_lens == "standard"


def test_unresolvable_lens_raises_lens_not_found() -> None:
    with pytest.raises(LensNotFound) as excinfo:
        lens_registry.get("does_not_exist")
    assert excinfo.value.conflict_class is ConflictClass.PARAMETER_CONFLICT


def test_lens_set_from_request_identity() -> None:
    """None / empty lens ids -> the default base lens alone."""
    assert LensSet.from_request(None, registry=lens_registry) == LensSet("standard", ())
    assert LensSet.from_request([], registry=lens_registry).lens_ids() == ("standard",)


def test_lens_set_from_request_non_base_first_is_overlay() -> None:
    """A non-base lens first -> default base + the provided ids as overlays."""
    lens_set = LensSet.from_request(["economic"], registry=lens_registry)
    assert lens_set.lens_ids() == ("standard", "economic")


def test_lens_set_from_request_explicit_base() -> None:
    lens_set = LensSet.from_request(["standard", "economic", "outcome"], registry=lens_registry)
    assert lens_set.lens_ids() == ("standard", "economic", "outcome")


def test_composition_identity() -> None:
    comp = compose_lenses(LensSet("standard", ()), registry=lens_registry)
    assert comp.ordered_lens_ids == ("standard",)
    assert not comp.incompatible


def test_composition_order_stability() -> None:
    """Overlays compose in registry order regardless of request order."""
    a = compose_lenses(LensSet("standard", ("outcome", "economic")), registry=lens_registry)
    b = compose_lenses(LensSet("standard", ("economic", "outcome")), registry=lens_registry)
    assert a.ordered_lens_ids == b.ordered_lens_ids
    assert list(a.ordered_lens_ids).index("economic") < list(a.ordered_lens_ids).index("outcome")


def test_composition_idempotence() -> None:
    comp = compose_lenses(
        LensSet("standard", ("economic", "economic")), registry=lens_registry
    )
    assert comp.ordered_lens_ids.count("economic") == 1


def test_composition_capability_missing_drops_inapplicable_lens() -> None:
    """A lens whose applicableSubjectKinds excludes the subject kind is dropped."""
    comp = compose_lenses(
        LensSet("standard", ("economic", "outcome")),
        subject_kind="deployment",
        registry=lens_registry,
    )
    assert comp.ordered_lens_ids == ("standard",)
    assert [i.lens_id for i in comp.incompatible] == ["economic", "outcome"]
    assert all(
        i.conflict_class is ConflictClass.CAPABILITY_MISSING for i in comp.incompatible
    )
    assert ConflictResolution.DEGRADE in comp.resolutions


def test_composition_applicable_lenses_kept() -> None:
    comp = compose_lenses(
        LensSet("standard", ("economic", "evidence")),
        subject_kind="campaign",
        registry=lens_registry,
    )
    assert comp.ordered_lens_ids == ("standard", "economic", "evidence")
    assert not comp.incompatible


def test_illegal_composition_non_base_base_raises() -> None:
    with pytest.raises(LensConflict) as excinfo:
        compose_lenses(LensSet("economic", ("outcome",)), registry=lens_registry)
    assert excinfo.value.conflict_class is ConflictClass.PARAMETER_CONFLICT


def test_illegal_composition_wrong_overlay_base_raises() -> None:
    """An overlay whose declared base is not the set base is illegal (custom
    registry — all real day-1 overlays base on ``standard``)."""
    defs = {
        "a": {
            "id": "a", "displayName": "A", "kind": "base", "baseLens": None,
            "description": "", "domain": "x", "applicableSubjectKinds": [],
            "temporalModes": [], "default": True,
        },
        "c": {
            "id": "c", "displayName": "C", "kind": "overlay", "baseLens": "z",
            "description": "", "domain": "x", "applicableSubjectKinds": [],
            "temporalModes": [], "default": False,
        },
    }
    reg = LensRegistry(defs)
    with pytest.raises(LensConflict) as excinfo:
        LensSet("a", ("c",)).validate(reg)
    assert excinfo.value.conflict_class is ConflictClass.PARAMETER_CONFLICT
    assert excinfo.value.lens_id == "c"
