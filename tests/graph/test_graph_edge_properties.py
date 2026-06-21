"""Tests for edge_properties.py — idempotency key determinism and property helpers."""

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
    for prefix in ("shared",):
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


def test_idempotency_key_is_deterministic() -> None:
    with backend_path():
        from shared.graph.edge_properties import make_edge_idempotency_key
        k1 = make_edge_idempotency_key("t1", "HAS_SESSION", "u1", "s1")
        k2 = make_edge_idempotency_key("t1", "HAS_SESSION", "u1", "s1")
        assert k1 == k2


def test_idempotency_key_differs_by_tenant() -> None:
    with backend_path():
        from shared.graph.edge_properties import make_edge_idempotency_key
        k1 = make_edge_idempotency_key("tenant-a", "HAS_SESSION", "u1", "s1")
        k2 = make_edge_idempotency_key("tenant-b", "HAS_SESSION", "u1", "s1")
        assert k1 != k2


def test_idempotency_key_differs_by_edge_type() -> None:
    with backend_path():
        from shared.graph.edge_properties import make_edge_idempotency_key
        k1 = make_edge_idempotency_key("t1", "HAS_SESSION", "u1", "s1")
        k2 = make_edge_idempotency_key("t1", "DELEGATES", "u1", "s1")
        assert k1 != k2


def test_idempotency_key_differs_by_direction() -> None:
    with backend_path():
        from shared.graph.edge_properties import make_edge_idempotency_key
        k1 = make_edge_idempotency_key("t1", "DELEGATES", "u1", "a1")
        k2 = make_edge_idempotency_key("t1", "DELEGATES", "a1", "u1")
        assert k1 != k2


def test_idempotency_key_is_hex_string() -> None:
    with backend_path():
        from shared.graph.edge_properties import make_edge_idempotency_key
        k = make_edge_idempotency_key("t1", "NOTIFIES", "a1", "u1")
        assert isinstance(k, str)
        assert len(k) == 64  # SHA-256 hex digest
        int(k, 16)  # must be valid hex


def test_source_event_id_changes_key() -> None:
    with backend_path():
        from shared.graph.edge_properties import make_edge_idempotency_key
        k1 = make_edge_idempotency_key("t1", "DELEGATES", "u1", "a1", source_event_id="")
        k2 = make_edge_idempotency_key("t1", "DELEGATES", "u1", "a1", source_event_id="evt-99")
        assert k1 != k2


def test_build_edge_properties_includes_all_required() -> None:
    with backend_path():
        from shared.graph.edge_properties import REQUIRED_EDGE_PROPERTIES, build_edge_properties
        props = build_edge_properties(
            tenant_id="t1",
            edge_type="HAS_SESSION",
            from_vertex_id="u1",
            to_vertex_id="s1",
            actor_kind="human",
            actor_id="u1",
            provenance="test",
            valid_from="2024-01-01T00:00:00+00:00",
        )
        missing = REQUIRED_EDGE_PROPERTIES - set(props.keys())
        assert not missing, f"Missing required properties: {missing}"


def test_build_edge_properties_idempotency_key_matches_helper() -> None:
    with backend_path():
        from shared.graph.edge_properties import build_edge_properties, make_edge_idempotency_key
        props = build_edge_properties(
            tenant_id="t1",
            edge_type="DELEGATES",
            from_vertex_id="u1",
            to_vertex_id="a1",
            actor_kind="human",
            actor_id="u1",
            provenance="test",
            valid_from="2024-01-01T00:00:00+00:00",
            source_event_id="evt-001",
        )
        expected = make_edge_idempotency_key("t1", "DELEGATES", "u1", "a1", "evt-001")
        assert props["idempotency_key"] == expected


def test_required_edge_properties_is_non_empty_frozenset() -> None:
    with backend_path():
        from shared.graph.edge_properties import REQUIRED_EDGE_PROPERTIES
        assert isinstance(REQUIRED_EDGE_PROPERTIES, frozenset)
        assert len(REQUIRED_EDGE_PROPERTIES) >= 8, (
            f"Expected at least 8 required properties, got {len(REQUIRED_EDGE_PROPERTIES)}"
        )


def test_tenant_id_in_required_properties() -> None:
    with backend_path():
        from shared.graph.edge_properties import REQUIRED_EDGE_PROPERTIES
        assert "tenant_id" in REQUIRED_EDGE_PROPERTIES


def test_idempotency_key_in_required_properties() -> None:
    with backend_path():
        from shared.graph.edge_properties import REQUIRED_EDGE_PROPERTIES
        assert "idempotency_key" in REQUIRED_EDGE_PROPERTIES
