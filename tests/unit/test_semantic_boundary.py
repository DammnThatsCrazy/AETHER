"""Unit tests for the WS-A3 semantic-level + SDK-boundary validator.

Drives ``generate_contracts.validate_field_trust`` (which runs
``_validate_semantic_boundary`` first) against crafted minimal registries so
each boundary rule is pinned without coupling to the full live registry.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_contracts():
    path = ROOT / "scripts" / "generate_contracts.py"
    spec = importlib.util.spec_from_file_location("generate_contracts_ws_a3", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_contracts_ws_a3"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_contracts()
_CLASSES = list(gen.FIELD_TRUST_CLASSES)


def _event(type_: str = "track", level: str = "A", emit: bool = True) -> dict:
    return {"type": type_, "family": "core", "semanticLevel": level, "sdkEmitable": emit}


def _boundary_registry(
    events: list[dict],
    *,
    sdk_classes=None,
    emit_levels=None,
    internal_classes=None,
    with_ft: bool = False,
) -> dict:
    sdk_classes = sdk_classes or ["OBSERVED", "SOURCE_ASSERTED", "SOURCE_REFERENCE", "CLIENT_HINT"]
    emit_levels = emit_levels or ["A", "B"]
    internal_classes = internal_classes or list(_CLASSES)
    reg = {
        "schemaVersion": "2.2.0",
        "trustClasses": _CLASSES,
        "semanticLevelSchemaVersion": "1.0.0",
        "sdkBoundarySchemaVersion": "1.0.0",
        "sdkBoundary": {
            "publicSdk": {
                "assertableTrustClasses": sdk_classes,
                "emittableSemanticLevels": emit_levels,
            },
            "aetherInternal": {
                "assertableTrustClasses": internal_classes,
                "emittableSemanticLevels": ["A", "B", "C"],
            },
        },
        "events": events,
    }
    if with_ft:
        # fieldTrustSchemaVersion is required iff >=1 event declares fields.
        reg["fieldTrustSchemaVersion"] = "1.0.0"
        reg["fieldTrustDefaults"] = {
            "trustClass": "OBSERVED",
            "sourceEmit": True,
            "minimumTrust": "OBSERVED",
            "level": "A",
        }
    return reg


# --- self-gating / structural ------------------------------------------------


def test_pre_22_registry_is_noop():
    # A truly pre-A2 registry carries none of the taxonomy blocks; both the
    # field-trust and A3-boundary validators must no-op cleanly.
    reg = {"schemaVersion": "2.1.0", "events": [_event()]}
    gen.validate_field_trust(reg)


def test_valid_boundary_passes():
    reg = _boundary_registry(
        [
            _event("track", "A", True),
            _event("journey_started", "B", True),
            _event("journey_completed", "C", False),
        ]
    )
    gen.validate_field_trust(reg)


# --- per-event rules ---------------------------------------------------------


def test_missing_semantic_level_fails():
    reg = _boundary_registry([{"type": "track", "family": "core", "sdkEmitable": True}])
    with pytest.raises(SystemExit):
        gen.validate_field_trust(reg)


def test_sdk_emittable_level_c_fails():
    reg = _boundary_registry([_event("journey_completed", "C", True)])
    with pytest.raises(SystemExit):
        gen.validate_field_trust(reg)


def test_sdk_emittable_unknown_level_fails():
    reg = _boundary_registry([_event("track", "D", True)])
    with pytest.raises(SystemExit):
        gen.validate_field_trust(reg)


def test_non_bool_sdk_emittable_fails():
    reg = _boundary_registry([{"type": "track", "family": "core", "semanticLevel": "A", "sdkEmitable": "yes"}])
    with pytest.raises(SystemExit):
        gen.validate_field_trust(reg)


# --- boundary-set rules ------------------------------------------------------


def test_sdk_classes_containing_server_stamped_fail():
    reg = _boundary_registry(
        [_event()], sdk_classes=["OBSERVED", "SOURCE_ASSERTED", "CLIENT_HINT", "SERVER_STAMPED"]
    )
    with pytest.raises(SystemExit):
        gen.validate_field_trust(reg)


def test_level_c_as_public_emit_level_fails():
    reg = _boundary_registry([_event()], emit_levels=["A", "B", "C"])
    with pytest.raises(SystemExit):
        gen.validate_field_trust(reg)


def test_internal_classes_must_equal_full_rank_fails():
    reg = _boundary_registry([_event()], internal_classes=["OBSERVED", "OPERATOR_ASSERTED"])
    with pytest.raises(SystemExit):
        gen.validate_field_trust(reg)


def test_sdk_event_declaring_backend_only_field_fails():
    events = [
        {
            "type": "track",
            "family": "core",
            "semanticLevel": "A",
            "sdkEmitable": True,
            "fieldTrust": {"fields": {"canonicalRef": {"trustClass": "RESOLVED"}}},
        }
    ]
    with pytest.raises(SystemExit):
        gen.validate_field_trust(_boundary_registry(events, with_ft=True))


def test_sdk_event_declaring_assertable_field_passes():
    events = [
        {
            "type": "track",
            "family": "core",
            "semanticLevel": "A",
            "sdkEmitable": True,
            "fieldTrust": {"fields": {"userId": {"trustClass": "CLIENT_HINT"}}},
        }
    ]
    gen.validate_field_trust(_boundary_registry(events, with_ft=True))


# --- live tree ---------------------------------------------------------------


def test_live_registry_passes_boundary_validation():
    """The committed 2.2.0 registry must satisfy every boundary rule."""
    reg = gen.load_registries()[0]
    gen.validate_field_trust(reg)
    assert reg["schemaVersion"] == "2.2.0"
