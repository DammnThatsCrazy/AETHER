"""Relationship Intelligence service — spine runtime caller + read surfaces.

Waves 2b/2c/2d/3b of the Social360 + Relationship Fidelity program. This package
owns ONE service: the first runtime caller of the relationship-fidelity engine
(:class:`~.coordinator.RelationshipSpineCoordinator`), the D-05 consent gate
(:mod:`.consent`), the canonical read helpers over the Computation Substrate
(:mod:`.reads`) and the read-only ``/v1/relationships`` REST surface
(:mod:`.routes`).

Every behavior is honest and flag-gated: with ``AETHER_SOCIAL360_ENABLED`` unset
the read surface reports ``feature_disabled`` degraded states, the consent gate
is a NO-OP, and no fidelity vector is persisted unless the fidelity rollout mode
(``AETHER_RELATIONSHIP_FIDELITY_MODE``) allows it.
"""

from __future__ import annotations

from services.relationship_intelligence.coordinator import (
    RelationshipSpineCoordinator,
    SpineRunResult,
)

__all__ = [
    "RelationshipSpineCoordinator",
    "SpineRunResult",
]
