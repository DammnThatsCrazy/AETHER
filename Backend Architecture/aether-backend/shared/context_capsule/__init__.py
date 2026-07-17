"""Context-capsule shared contracts.

Owns the privacy-shaped :class:`LocationObservation` (no raw IP, no lat/lon)
and the versioned :class:`ContextCapsule`, plus the deterministic
:func:`capsule_hash` used to detect capsule transitions. The taxonomy tuples
live in ``generated_taxonomy`` (Python twin of
``packages/shared/contracts/context-capsule-registry.json``); TS twin:
``packages/shared/context-capsule.ts``.
"""

from shared.context_capsule.models import (
    CAPSULE_HASH_FIELDS,
    ContextCapsule,
    LocationObservation,
    capsule_hash,
)

__all__ = [
    "CAPSULE_HASH_FIELDS",
    "ContextCapsule",
    "LocationObservation",
    "capsule_hash",
]
