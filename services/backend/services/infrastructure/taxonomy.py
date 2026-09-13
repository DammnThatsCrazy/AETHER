"""Infrastructure taxonomy — entity kinds, lifecycle state machine, relationships.

This module is the **single canonical declaration** of the infrastructure
taxonomy the infrastructure360 projection (and any future consumer) reads:

* :data:`INFRASTRUCTURE_FACT_CATEGORIES` — the canonical authorities the
  projection reads over, matching the registry row's ``canonicalAuthorities``
  (``infrastructure_facts``, ``infrastructure_state``, ``deployments``).
* :data:`SUPPORTED_ENTITY_KINDS` — the closed set of
  :class:`~services.infrastructure.contracts.InfrastructureEntityType` values.
* :data:`LEGAL_STATE_TRANSITIONS` — a small legal-transition table for
  :class:`~services.infrastructure.contracts.InfrastructureState`. The headline
  invariant: ``FAILED -> ACTIVE`` is ILLEGAL without an intervening redeploy
  (``FAILED -> PROVISIONED -> DEPLOYING -> ACTIVE``). A direct repair-to-active
  claim is treated as a lie the taxonomy rejects.
* :data:`RELATIONSHIP_SEMANTICS` — the meaning of each
  :class:`~services.infrastructure.contracts.InfrastructureRelationshipType`.
* :data:`DEPLOYMENT_TARGET_KINDS` — the entity kinds a deployment may land on.

The module is **deterministic and pure**: no I/O, no imports beyond the
contracts, so it can be reasoned about and tested in isolation.
"""

from __future__ import annotations

from typing import Final

from services.infrastructure.contracts import (
    InfrastructureEntityType,
    InfrastructureRelationshipType,
    InfrastructureState,
)

__all__ = [
    "DEPLOYMENT_TARGET_KINDS",
    "INFRASTRUCTURE_FACT_CATEGORIES",
    "LEGAL_STATE_TRANSITIONS",
    "RELATIONSHIP_SEMANTICS",
    "SUPPORTED_ENTITY_KINDS",
    "can_transition",
    "is_valid_kind",
    "is_valid_relationship",
    "requires_redeploy",
]

# ── Canonical authority categories (registry `canonicalAuthorities`) ────────
# The projection reads these three authorities; a source that cannot be read
# degrades its sections — the provider never fabricates.
INFRASTRUCTURE_FACT_CATEGORIES: Final[tuple[str, ...]] = (
    "infrastructure_facts",
    "infrastructure_state",
    "deployments",
)

# ── Entity kinds ──────────────────────────────────────────────────────────────
SUPPORTED_ENTITY_KINDS: Final[tuple[InfrastructureEntityType, ...]] = (
    InfrastructureEntityType.SERVICE,
    InfrastructureEntityType.DATABASE,
    InfrastructureEntityType.CACHE,
    InfrastructureEntityType.QUEUE,
    InfrastructureEntityType.WORKER,
    InfrastructureEntityType.FUNCTION,
    InfrastructureEntityType.CONTAINER,
    InfrastructureEntityType.HOST,
    InfrastructureEntityType.NETWORK,
    InfrastructureEntityType.STORAGE,
    InfrastructureEntityType.GATEWAY,
    InfrastructureEntityType.ORCHESTRATOR,
)

# Kinds that can host a deployment (`DEPLOYED_ON` target).
DEPLOYMENT_TARGET_KINDS: Final[frozenset[InfrastructureEntityType]] = frozenset(
    {
        InfrastructureEntityType.HOST,
        InfrastructureEntityType.CONTAINER,
        InfrastructureEntityType.ORCHESTRATOR,
    }
)

# ── Lifecycle state machine ──────────────────────────────────────────────────
# A small legal-transition table. The key invariant: FAILED never transitions
# directly to ACTIVE (a failed entity must be re-provisioned / redeployed
# first). Every state is stable under self-transition (observation idempotence).
LEGAL_STATE_TRANSITIONS: Final[
    dict[InfrastructureState, frozenset[InfrastructureState]]
] = {
    InfrastructureState.PROVISIONED: frozenset(
        {
            InfrastructureState.PROVISIONED,
            InfrastructureState.DEPLOYING,
            InfrastructureState.MAINTENANCE,
            InfrastructureState.DEPROVISIONING,
            InfrastructureState.FAILED,
        }
    ),
    InfrastructureState.DEPLOYING: frozenset(
        {
            InfrastructureState.DEPLOYING,
            InfrastructureState.ACTIVE,
            InfrastructureState.DEGRADED,
            InfrastructureState.MAINTENANCE,
            InfrastructureState.FAILED,
        }
    ),
    InfrastructureState.ACTIVE: frozenset(
        {
            InfrastructureState.ACTIVE,
            InfrastructureState.DEGRADED,
            InfrastructureState.MAINTENANCE,
            InfrastructureState.DEPROVISIONING,
            InfrastructureState.FAILED,
        }
    ),
    InfrastructureState.DEGRADED: frozenset(
        {
            InfrastructureState.DEGRADED,
            InfrastructureState.ACTIVE,
            InfrastructureState.MAINTENANCE,
            InfrastructureState.DEPROVISIONING,
            InfrastructureState.FAILED,
        }
    ),
    InfrastructureState.MAINTENANCE: frozenset(
        {
            InfrastructureState.MAINTENANCE,
            InfrastructureState.ACTIVE,
            InfrastructureState.DEGRADED,
            InfrastructureState.DEPROVISIONING,
            InfrastructureState.FAILED,
            InfrastructureState.PROVISIONED,
        }
    ),
    InfrastructureState.DEPROVISIONING: frozenset(
        {
            InfrastructureState.DEPROVISIONING,
            InfrastructureState.PROVISIONED,
            InfrastructureState.UNKNOWN,
        }
    ),
    InfrastructureState.FAILED: frozenset(
        {
            InfrastructureState.FAILED,
            InfrastructureState.PROVISIONED,
            InfrastructureState.DEPLOYING,
            InfrastructureState.DEPROVISIONING,
            InfrastructureState.UNKNOWN,
            # NOTE: FAILED -> ACTIVE is deliberately ABSENT (needs a redeploy).
        }
    ),
    InfrastructureState.UNKNOWN: frozenset(InfrastructureState),
}


def can_transition(
    current: InfrastructureState, target: InfrastructureState
) -> bool:
    """True when ``current -> target`` is a legal lifecycle transition."""
    return target in LEGAL_STATE_TRANSITIONS[current]


def requires_redeploy(
    current: InfrastructureState, target: InfrastructureState
) -> bool:
    """True when reaching ``target`` from ``current`` requires a redeploy.

    The canonical case: ``FAILED -> ACTIVE`` is illegal without an intervening
    redeploy, so the *honest* route is ``FAILED -> PROVISIONED -> DEPLOYING ->
    ACTIVE`` — and any transition out of FAILED (other than staying FAILED /
    deprovisioning) is declared as requiring a redeploy.
    """
    return current is InfrastructureState.FAILED and (
        target is not InfrastructureState.FAILED
        and target is not InfrastructureState.DEPROVISIONING
        and target is not InfrastructureState.UNKNOWN
    )


# ── Relationship semantics ───────────────────────────────────────────────────
RELATIONSHIP_SEMANTICS: Final[
    dict[InfrastructureRelationshipType, str]
] = {
    InfrastructureRelationshipType.DEPENDS_ON: (
        "source depends on target; source availability is gated by target"
    ),
    InfrastructureRelationshipType.DEPLOYED_ON: (
        "source artifact is deployed onto target runtime (host/container/orchestrator)"
    ),
    InfrastructureRelationshipType.CONNECTS_TO: (
        "source connects to target across a network boundary"
    ),
    InfrastructureRelationshipType.COMPOSED_OF: (
        "source is composed of target (containment / part-of)"
    ),
    InfrastructureRelationshipType.SCALES_WITH: (
        "source scales with target (elasticity coupling)"
    ),
}


# ── Validation helpers ───────────────────────────────────────────────────────

def is_valid_kind(kind: InfrastructureEntityType) -> bool:
    """True when ``kind`` is a supported infrastructure entity kind."""
    return kind in SUPPORTED_ENTITY_KINDS


def is_valid_relationship(relationship_type: InfrastructureRelationshipType) -> bool:
    """True when ``relationship_type`` is a declared relationship semantics."""
    return relationship_type in RELATIONSHIP_SEMANTICS
