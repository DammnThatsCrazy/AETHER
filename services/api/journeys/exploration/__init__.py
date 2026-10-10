"""Unified Exploration Fabric backend (WP3.4).

Flag-gated (``AETHER_EXPLORATION_ENABLED``, default OFF) exploration plane:
a planner that validates every filter against the canonical filter-field
registry, per-surface adapters, conditioned facets with cohort-minimum
suppression, and the ``/v1/explore`` API. Submodules are imported lazily by
``main.py`` only when the flag is on — importing this package has no side
effects and pulls in no heavy dependencies.
"""

from __future__ import annotations

__all__: list[str] = []
