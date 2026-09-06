"""Relationship-spine feature flags (Social360 + Relationship Fidelity, M6).

Milestone M6 promotion / motif runtime behavior is ROLLOUT-GATED and defaults
OFF (blueprint §121–122, docs/blueprints/social360.md). These helpers read the
runtime settings DEFENSIVELY: the canonical env vars are honoured first, then a
best-effort read of ``config.settings`` (a sibling agent owns ``config/settings.py``
and may later surface the same knobs there), and the answer is ``False`` whenever
the knob is undefined anywhere. Nothing here writes settings.

Flags read (all default OFF):

* ``AETHER_SOCIAL360_ENABLED``              -> :func:`social360_enabled`
* ``AETHER_RELATIONSHIP_MOTIFS_ENABLED``    -> :func:`relationship_motifs_enabled`
* ``AETHER_RELATIONSHIP_PROMOTION_ENABLED`` -> :func:`relationship_promotion_enabled`

Promotion is additionally bounded by the master ``social360_enabled`` gate: a
relationship is never written to the graph unless the Social360 domain is
activated, because promotion exists to feed Relationship360 / the graph from the
Social360 evidence surface.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


def _truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _env_flag(name: str) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return _truthy(raw)


def _settings_flag(*path: str) -> Optional[bool]:
    """Best-effort read of ``config.settings`` down an attribute path.

    The exact settings namespace is owned by a sibling agent
    (``config/settings.py``). We try a few likely shapes without importing
    anything beyond the settings singleton and without raising when the knob
    does not exist yet.
    """
    try:
        from config.settings import settings  # type: ignore
    except Exception:  # pragma: no cover - settings may be unavailable
        return None
    try:
        obj: object = settings
        for attr in path:
            obj = getattr(obj, attr)
        return _truthy(obj)
    except Exception:  # pragma: no cover - attribute not defined yet
        return None


@lru_cache(maxsize=1)
def social360_enabled() -> bool:
    """Master Social360 gate (blueprint rollout flag, default OFF)."""
    value = _env_flag("AETHER_SOCIAL360_ENABLED")
    if value is not None:
        return value
    value = _settings_flag("social360", "enabled")
    if value is not None:
        return value
    return False


@lru_cache(maxsize=1)
def relationship_motifs_enabled() -> bool:
    """Relationship-motif matcher + graph_motifs indicator gate (default OFF)."""
    value = _env_flag("AETHER_RELATIONSHIP_MOTIFS_ENABLED")
    if value is not None:
        return value
    value = _settings_flag("relationship_motifs", "enabled")
    if value is not None:
        return value
    # The motif matcher consumes master-Social360 as a floor so motif-derived
    # output can never run while the broader domain is off.
    return social360_enabled()


@lru_cache(maxsize=1)
def relationship_promotion_enabled() -> bool:
    """Relationship-promotion -> graph gateway gate (default OFF).

    Promotion writes governed relationship edges to the graph; it requires the
    master Social360 gate in addition to its own env knob.
    """
    value = _env_flag("AETHER_RELATIONSHIP_PROMOTION_ENABLED")
    if value is not None:
        return value
    value = _settings_flag("relationship_promotion", "enabled")
    if value is not None:
        return bool(value) if value is not None else False
    return social360_enabled()


def invalidate_flag_cache() -> None:
    """Clear memoised flag reads (used by tests that flip env vars)."""
    social360_enabled.cache_clear()
    relationship_motifs_enabled.cache_clear()
    relationship_promotion_enabled.cache_clear()


__all__ = [
    "social360_enabled",
    "relationship_motifs_enabled",
    "relationship_promotion_enabled",
    "invalidate_flag_cache",
]
