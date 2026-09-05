"""Authoritative relationship-predicate registry reader (backend).

Milestone M6 promotion / motif code must resolve a relationship predicate to its
REGISTERED graph edge. The generated Python twin
(``generated_relationship_predicate_registry.py``) is regenerated from
``packages/shared/contracts/relationship-predicate-registry.json`` at
integration time; until then it is stale with respect to the M6 edge
registration. This module reads the registry JSON -- the canonical source of
truth -- LAZILY and caches it, and always cross-checks a registered
``graphEdgeType`` against the live ``shared.graph.graph.EdgeType`` class so a
predicate can never claim a graph edge that does not exist. This mirrors the
runtime JSON-registry pattern already used by
``shared/privacy/retention.py`` and ``shared/privacy/consent_enforcement.py``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from shared.graph.graph import EdgeType

# repo-root/packages/shared/contracts/relationship-predicate-registry.json
# relationship_spine is at <root>/Backend Architecture/aether-backend/shared/relationship_spine
_REGISTRY_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "shared"
    / "contracts"
    / "relationship-predicate-registry.json"
)


def _edge_type_values() -> frozenset[str]:
    return frozenset(
        v
        for k, v in vars(EdgeType).items()
        if not k.startswith("_") and isinstance(v, str)
    )


@lru_cache(maxsize=1)
def _load_registry() -> Optional[dict[str, Any]]:
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover - registry always present in-repo
        return None


def all_predicates() -> list[dict[str, Any]]:
    """Every predicate entry in registry file order (empty list when unreadable)."""
    reg = _load_registry()
    if not reg:
        return []
    return list(reg.get("predicates", []))


def predicate_entry(predicate: str) -> Optional[dict[str, Any]]:
    """Registry entry for one predicate (None when unknown)."""
    for entry in all_predicates():
        if entry.get("predicate") == predicate:
            return dict(entry)
    return None


def is_registered(predicate: str) -> bool:
    """True when the predicate's graphRegistrationState is REGISTERED."""
    entry = predicate_entry(predicate)
    return bool(entry and entry.get("graphRegistrationState") == "REGISTERED")


def graph_edge_type(predicate: str) -> Optional[str]:
    """The registry graphEdgeType value for a predicate (None when PENDING)."""
    entry = predicate_entry(predicate)
    if entry is None:
        return None
    return entry.get("graphEdgeType")


def live_graph_edge_type(predicate: str) -> Optional[str]:
    """The registered graphEdgeType ONLY when it is a live EdgeType member.

    A REGISTERED predicate whose edge is not yet a ``shared.graph.graph.EdgeType``
    member is a contract violation; this returns None so callers fail closed
    instead of projecting an edge that cannot exist.
    """
    edge = graph_edge_type(predicate)
    if edge is None or edge not in _edge_type_values():
        return None
    return edge


def resolve_required_edges_for(predicate: str) -> list[str]:
    """All live EdgeType members a predicate's edges may be stored under.

    A predicate is written to the graph under exactly one registered EdgeType;
    the ``FOLLOWS`` predicate already disambiguates to ``FOLLOWS_SOCIAL`` via the
    registry, so this returns a single-element list for a registered predicate
    and an empty list when the predicate has no registered live edge (used by
    the motif matcher to skip patterns it cannot yet observe in the graph).
    """
    edge = live_graph_edge_type(predicate)
    return [edge] if edge is not None else []



def motif_observation_edge_type(predicate: str) -> Optional[str]:
    """Resolve a motif required-edge predicate to a LIVE EdgeType member.

    A motif's ``requiredEdges`` reference *predicates* that are either (a)
    registered relationship predicates (e.g. ``FOLLOWS``, whose graph edge is
    ``FOLLOWS_SOCIAL``) or (b) bare graph EdgeType members that are NOT
    relationship-predicate registry entries (e.g. ``DELEGATES_TO``,
    ``ACTED_FOR`` -- agentic edges the motif composes over but never promotes as
    relationship predicates). Registered predicates resolve through the registry
    cross-check (:func:`live_graph_edge_type`); otherwise the predicate is used
    verbatim ONLY when it is already a live ``EdgeType`` member. A predicate
    that resolves nowhere returns ``None`` so the motif matcher fails closed and
    never searches for an edge type that cannot exist.
    """
    edge = live_graph_edge_type(predicate)
    if edge is not None:
        return edge
    if predicate in _edge_type_values():
        return predicate
    return None


__all__ = [
    "all_predicates",
    "predicate_entry",
    "is_registered",
    "graph_edge_type",
    "live_graph_edge_type",
    "resolve_required_edges_for",
    "motif_observation_edge_type",
]
