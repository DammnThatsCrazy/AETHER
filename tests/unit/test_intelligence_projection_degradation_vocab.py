"""Degradation-vocabulary validator tests (A8, rule group ``degradation_vocab``).

The projection engine maps every degradation onto a registered ``SectionState``
— never a parallel vocabulary. The registry's ``sectionStates`` MUST be a
superset of the engine's emittable states (``available``, ``empty``, ``missing``,
``degraded``, ``not_applicable``, ``unknown``, ``suppressed``, ``stale``).
Removing a state the engine emits fails the validator; the canonical registry
today satisfies the full set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import intelligence_projection_validation as ipv  # noqa: E402

REGISTRY_PATH = REPO_ROOT / "packages/shared/contracts/intelligence-projection-registry.json"
REAL_REG = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_engine_states_are_a_subset_of_registry_section_states():
    """Every engine-emittable SectionState is registered (single vocab)."""
    violations = ipv.validate_degradation_vocab(REAL_REG)
    assert violations == []
    assert set(REAL_REG["sectionStates"]) >= ipv.ENGINE_SECTION_STATES


def test_removing_a_required_state_fails_validation():
    """Dropping ``suppressed`` (an A8 state) from the registry must fail."""
    bad = json.loads(json.dumps(REAL_REG))
    bad["sectionStates"].remove("suppressed")
    violations = ipv.validate_degradation_vocab(bad)
    assert len(violations) == 1
    assert violations[0].rule == "degradation_vocab"
    assert violations[0].severity == "error"
    assert "suppressed" in violations[0].message


def test_engine_section_state_vocab_matches_the_engine():
    """The validator's engine set mirrors the engine's degradation module."""
    import os
    import sys as _sys

    backend = REPO_ROOT / "Backend Architecture" / "aether-backend"
    if str(backend) not in _sys.path:
        _sys.path.insert(0, str(backend))
    os.environ.setdefault("AETHER_ENV", "local")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    from shared.projection_engine import degradation as engine_degradation

    engine_states = {
        "available",
        engine_degradation.degraded_section_state(),
        engine_degradation.suppressed_section_state(),
        engine_degradation.stale_section_state(),
        "empty",
        "missing",
        "not_applicable",
        "unknown",
    }
    # The engine's emittable set is exactly the validator's required set.
    assert engine_states == set(ipv.ENGINE_SECTION_STATES)
