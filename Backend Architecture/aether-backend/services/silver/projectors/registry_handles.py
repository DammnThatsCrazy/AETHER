"""Registry-driven projector handles.

Derives each projector's `handles` set from the canonical event registry
(packages/shared/contracts/event-registry.json) by family + silverProjection,
so a projector can never drift from the registry: adding an event with a
silverProjection routes it automatically; removing one stops routing it.
"""

from __future__ import annotations

import json
import pathlib

# parents[5] = repo root (projectors -> silver -> services -> aether-backend
# -> "Backend Architecture" -> repo root)
_REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "packages" / "shared" / "contracts" / "event-registry.json"
)


def registry_handles(family: str, silver_projection: str) -> frozenset[str]:
    """Event types of `family` whose silverProjection is `silver_projection`."""
    try:
        events = json.loads(_REGISTRY_PATH.read_text()).get("events", [])
    except Exception:  # pragma: no cover - registry ships with the repo
        return frozenset()
    return frozenset(
        e["type"] for e in events
        if e.get("family") == family and e.get("silverProjection") == silver_projection
    )
