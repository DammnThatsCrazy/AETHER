"""Tests for GraphWriteValidator — pre-write edge property enforcement."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path

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
                PyJWTError=Exception, ExpiredSignatureError=Exception, InvalidTokenError=Exception
            ),
        )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


def _valid_props(tenant_id: str = "t1") -> dict:
    return {
        "tenant_id": tenant_id,
        "idempotency_key": "abc123",
        "actor_kind": "agent",
        "actor_id": "agent-1",
        "schema_version": "1",
        "provenance": "test",
        "valid_from": "2024-01-01T00:00:00+00:00",
        "confidence": "0.9",
    }


def test_valid_edge_passes_validation() -> None:
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        edge = Edge(EdgeType.HAS_SESSION, "u1", "s1", _valid_props())
        result = GraphWriteValidator().validate(edge, env="production")
        assert result.passed, f"Expected pass; violations: {result.violations}"


def test_missing_tenant_id_fails() -> None:
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        props = _valid_props()
        del props["tenant_id"]
        edge = Edge(EdgeType.HAS_SESSION, "u1", "s1", props)
        result = GraphWriteValidator().validate(edge, env="production")
        assert not result.passed
        assert any("tenant_id" in v for v in result.violations)


def test_missing_idempotency_key_fails() -> None:
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        props = _valid_props()
        del props["idempotency_key"]
        edge = Edge(EdgeType.DELEGATES, "u1", "a1", props)
        result = GraphWriteValidator().validate(edge, env="production")
        assert not result.passed
        assert any("idempotency_key" in v for v in result.violations)


def test_invalid_actor_kind_fails() -> None:
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        props = _valid_props()
        props["actor_kind"] = "robot"
        edge = Edge(EdgeType.NOTIFIES, "a1", "u1", props)
        result = GraphWriteValidator().validate(edge, env="production")
        assert not result.passed
        assert any("actor_kind" in v for v in result.violations)


def test_confidence_out_of_range_fails() -> None:
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        props = _valid_props()
        props["confidence"] = "1.5"
        edge = Edge(EdgeType.HAS_SESSION, "u1", "s1", props)
        result = GraphWriteValidator().validate(edge, env="production")
        assert not result.passed
        assert any("confidence" in v for v in result.violations)


def test_confidence_zero_is_valid() -> None:
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        props = _valid_props()
        props["confidence"] = "0.0"
        edge = Edge(EdgeType.HAS_SESSION, "u1", "s1", props)
        result = GraphWriteValidator().validate(edge, env="production")
        assert result.passed, f"Violations: {result.violations}"


def test_h2a_edge_requires_consent_purpose() -> None:
    """H2A edges (DELEGATES etc.) need consent_purpose in their properties."""
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        props = _valid_props()
        # No consent_purpose
        edge = Edge(EdgeType.DELEGATES, "u1", "a1", props)
        result = GraphWriteValidator().validate(edge, env="production")
        assert not result.passed
        assert any("consent_purpose" in v for v in result.violations)


def test_h2a_edge_passes_with_consent_purpose() -> None:
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        props = _valid_props()
        props["consent_purpose"] = "agent_delegation"
        edge = Edge(EdgeType.DELEGATES, "u1", "a1", props)
        result = GraphWriteValidator().validate(edge, env="production")
        assert result.passed, f"Violations: {result.violations}"


def test_a2h_edge_requires_consent_purpose() -> None:
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        props = _valid_props()
        props["actor_kind"] = "agent"
        edge = Edge(EdgeType.NOTIFIES, "a1", "u1", props)
        result = GraphWriteValidator().validate(edge, env="production")
        assert not result.passed
        assert any("consent_purpose" in v for v in result.violations)


def test_validation_lenient_in_local_mode() -> None:
    """In local mode, validation logs but does not raise and passes all edges."""
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator
        # Empty properties — many violations
        edge = Edge(EdgeType.HAS_SESSION, "u1", "s1", {})
        result = GraphWriteValidator().validate(edge, env="local")
        # In local mode violations are returned but .passed is False
        assert not result.passed
        assert len(result.violations) > 0  # violations recorded but not raised


def test_empty_edge_type_fails() -> None:
    with backend_path():
        from shared.graph.graph import Edge
        from shared.graph.write_validator import GraphWriteValidator
        edge = Edge("", "u1", "s1", _valid_props())
        result = GraphWriteValidator().validate(edge, env="production")
        assert not result.passed
        assert any("edge_type" in v for v in result.violations)


def test_all_required_properties_enforced() -> None:
    """Each required property, when missing, produces a violation."""
    with backend_path():
        from shared.graph.edge_properties import REQUIRED_EDGE_PROPERTIES
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.write_validator import GraphWriteValidator

        for prop in REQUIRED_EDGE_PROPERTIES:
            props = _valid_props()
            del props[prop]
            edge = Edge(EdgeType.HAS_SESSION, "u1", "s1", props)
            result = GraphWriteValidator().validate(edge, env="production")
            assert not result.passed, f"Expected failure for missing {prop!r}"
            assert any(prop in v for v in result.violations), (
                f"Missing violation for {prop!r}; got: {result.violations}"
            )
