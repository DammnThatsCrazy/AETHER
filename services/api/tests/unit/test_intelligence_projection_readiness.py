"""Unit tests for the projection-plane presentation-only readiness mapping (P0.7).

``implementationState`` in the projection registry
(``packages/shared/contracts/intelligence-projection-registry.json``) is REPO
METADATA describing how far a projection has been converged onto the projection
plane — it is NOT readiness. This suite proves
``shared/intelligence_projections/readiness.py`` is a hand-written,
PRESENTATION-ONLY join layer that:

* maps EVERY generated registry implementation state to a presentation token
  (states are derived from ``PROJECTION_IMPLEMENTATION_STATES`` so the test
  cannot rot);
* raises the plane's :class:`ProjectionError` for an unknown state — never a
  bare ``KeyError``;
* is provably DISJOINT from the certification plane's ``CredentialReadiness``
  enum values (the enum is imported HERE — in the test — never in the
  readiness module, which stays self-contained);
* never emits ``production_ready`` (a claim DIMENSION, not a state);
* is hand-written and NOT derived from the certification plane.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

# Structural tests read the module source from disk, so this must be exact
# (the sibling files' parents[3] path is masked by conftest's sys.path insert).
BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.intelligence_projections import (  # noqa: E402
    IMPLEMENTATION_STATE_PRESENTATION,
    PRESENTATION_TOKENS,
    PROJECTION_IMPLEMENTATION_STATES,
    ProjectionError,
    presentation_token,
)
# The certification plane is imported in the TEST ONLY — the readiness module
# must stay self-contained (see test_readiness_module_never_imports_certification).
from shared.certification.readiness import CredentialReadiness  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _readiness_source() -> str:
    path = (
        BACKEND_ROOT / "shared" / "intelligence_projections" / "readiness.py"
    )
    return path.read_text(encoding="utf-8")


def _mapping_dict_literal() -> ast.Dict:
    """Return the AST of the hand-written ``IMPLEMENTATION_STATE_PRESENTATION``
    dict literal, so structural checks inspect the actual module source."""
    tree = ast.parse(_readiness_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "IMPLEMENTATION_STATE_PRESENTATION"
            ):
                assert isinstance(node.value, ast.Dict)
                return node.value
    raise AssertionError(
        "IMPLEMENTATION_STATE_PRESENTATION dict literal not found in readiness.py"
    )


# ---------------------------------------------------------------------------
# Total coverage of the generated registry states (drift-proof)
# ---------------------------------------------------------------------------

def test_every_generated_registry_state_maps_to_a_presentation_token() -> None:
    # The registry declares exactly four implementation states today.
    assert len(PROJECTION_IMPLEMENTATION_STATES) == 4

    # The hand-written mapping is bound to the GENERATED states, so adding a
    # registry state forces a review here rather than silently rotting.
    assert set(IMPLEMENTATION_STATE_PRESENTATION) == set(
        PROJECTION_IMPLEMENTATION_STATES
    )

    for state in PROJECTION_IMPLEMENTATION_STATES:
        token = presentation_token(state)
        assert isinstance(token, str)
        assert token in PRESENTATION_TOKENS


def test_presentation_mapping_is_bijective_and_closed() -> None:
    assert len(PRESENTATION_TOKENS) == len(IMPLEMENTATION_STATE_PRESENTATION) == 4
    assert set(PRESENTATION_TOKENS) == set(
        IMPLEMENTATION_STATE_PRESENTATION.values()
    )
    # Bijective: no two registry states share a presentation token.
    tokens = list(IMPLEMENTATION_STATE_PRESENTATION.values())
    assert len(tokens) == len(set(tokens))


def test_presentation_vocabulary_is_the_documented_closed_set() -> None:
    # The hand-written, documented presentation vocabulary (closed set). Any
    # change to these spellings is a deliberate presentation-layer decision.
    assert IMPLEMENTATION_STATE_PRESENTATION == {
        "registered": "queued",
        "in_flight": "converging",
        "implemented": "converged",
        "deprecated": "retired",
    }


def test_barrel_exports_the_readiness_api() -> None:
    # The plane barrel must surface the join layer for UI consumers.
    import shared.intelligence_projections as plane

    assert plane.IMPLEMENTATION_STATE_PRESENTATION is IMPLEMENTATION_STATE_PRESENTATION
    assert plane.PRESENTATION_TOKENS is PRESENTATION_TOKENS
    assert plane.presentation_token is presentation_token


# ---------------------------------------------------------------------------
# Unknown-state behavior
# ---------------------------------------------------------------------------

def test_unknown_state_raises_projection_error_not_key_error() -> None:
    with pytest.raises(ProjectionError) as excinfo:
        presentation_token("not_a_state")
    # A bare KeyError must never escape the public API.
    assert not isinstance(excinfo.value, KeyError)
    assert "not_a_state" in str(excinfo.value)


def test_known_states_do_not_raise() -> None:
    for state in PROJECTION_IMPLEMENTATION_STATES:
        presentation_token(state)  # must not raise


# ---------------------------------------------------------------------------
# Disjointness from the certification plane
# ---------------------------------------------------------------------------

def test_presentation_vocabulary_disjoint_from_certification_enum() -> None:
    cert_tokens = {member.value for member in CredentialReadiness}
    assert PRESENTATION_TOKENS.isdisjoint(cert_tokens)
    assert not set(IMPLEMENTATION_STATE_PRESENTATION.values()) & cert_tokens


def test_implemented_spelling_does_not_resurrect_certification_alias() -> None:
    # "implemented" is an alias of the certification token credential_waiting in
    # the readiness vocabulary; the presentation spelling of the "implemented"
    # registry state must be a distinct presentation token, never the alias.
    assert presentation_token("implemented") == "converged"
    assert presentation_token("implemented") not in {
        member.value for member in CredentialReadiness
    }


# ---------------------------------------------------------------------------
# production_ready is never emitted (a claim DIMENSION, not a state)
# ---------------------------------------------------------------------------

def test_production_ready_never_in_the_vocabulary() -> None:
    # Structural: the closed token set cannot contain it.
    assert "production_ready" not in PRESENTATION_TOKENS

    # Structural: the hand-written mapping literal has no such value.
    values = {ast.literal_eval(v) for v in _mapping_dict_literal().values}
    assert "production_ready" not in values

    # No registry state maps to it either.
    for state in PROJECTION_IMPLEMENTATION_STATES:
        assert presentation_token(state) != "production_ready"


# ---------------------------------------------------------------------------
# Hand-written and NOT derived from the certification plane
# ---------------------------------------------------------------------------

def test_mapping_is_a_hand_written_dict_literal() -> None:
    literal = _mapping_dict_literal()
    assert len(literal.keys) == 4
    values = {ast.literal_eval(v) for v in literal.values}
    assert values == set(PRESENTATION_TOKENS)


# The only modules the self-contained readiness module may import: the stdlib
# ``typing``/``__future__`` plus the projection plane's own error + generated
# registry. ANY other import is a coupling that must fail loudly.
_ALLOWED_READINESS_IMPORTS = frozenset(
    {
        "__future__",
        "typing",
        "shared.intelligence_projections.errors",
        "shared.intelligence_projections.generated_registry",
    }
)


def test_readiness_module_never_imports_certification_plane() -> None:
    # The disjointness guarantee is proven by tests, not by a runtime import:
    # the module is self-contained and must not import the certification plane.
    source = _readiness_source()
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)

    # Every import module must be on the explicit allowlist — no coupling to the
    # certification plane OR any other module outside the plane's own package
    # (the docstring legitimately mentions "certification token"; this checks
    # import statements only, so it cannot false-positive on prose).
    assert imported <= _ALLOWED_READINESS_IMPORTS, (
        "readiness.py imports a module outside its allowlist: "
        f"{sorted(imported - _ALLOWED_READINESS_IMPORTS)}"
    )

    # Dynamic import escape hatches are `ast.Call` nodes, invisible to the AST
    # scan above — scan the raw source for them too.
    for token in ("importlib", "import_module"):
        assert token not in source, (
            f"readiness.py references {token!r}, a dynamic-import escape hatch"
        )

    # Belt-and-braces: no certification plane module may be imported by name.
    assert not any("certification" in name for name in imported), (
        f"readiness.py imports the certification plane: {sorted(imported)}"
    )
