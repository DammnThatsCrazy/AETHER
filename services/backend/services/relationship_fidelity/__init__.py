"""Relationship Fidelity service — M7 orchestration + consume-only persistence.

The runtime orchestration lives here (it imports ``services/computation`` /
``services`` layers, which ``shared/relationship_fidelity`` must not). It:

* reads the ``AETHER_RELATIONSHIP_FIDELITY_MODE`` flag defensively (default
  ``off`` — see the program ledger / rollout controls);
* computes the multidimensional fidelity vector via the substrate definitions;
* degrades independence to UNKNOWN when the M6 evidence engine is absent; and
* persists consume-only through ``services/computation/repositories.py``
  (no new DDL/table — a need for durable persistence beyond that repo would be
  recorded as a blocker, never migrated here).
"""

from services.relationship_fidelity.engine import (
    FIDELITY_MODES,
    RelationshipFidelityEngine,
    fidelity_mode,
)

# NOTE: named ``_default_engine`` (not ``engine``) so the submodule
# ``services.relationship_fidelity.engine`` is never shadowed by a package-level
# attribute of the same name.
_default_engine = RelationshipFidelityEngine()

__all__ = [
    "FIDELITY_MODES",
    "RelationshipFidelityEngine",
    "fidelity_mode",
    "_default_engine",
]
