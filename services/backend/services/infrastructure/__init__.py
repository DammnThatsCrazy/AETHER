"""Infrastructure360 — the 19th intelligence projection vertical slice.

The infrastructure plane is a **canonical Aether domain** (entity kinds,
lifecycle states, deployments, relationships) and infrastructure360 is its
**intelligence projection** — a read-only 360 over canonical infrastructure
truth, never a competing system of record (ADR-010).

This package ships:

* :mod:`~services.infrastructure.contracts` — canonical infrastructure domain
  contracts (reusing the canonical ``EntityRef`` / ``EvidenceRef`` /
  ``PageRequest`` / ``TimeRangeFilter`` primitives, never re-declaring them);
* :mod:`~services.infrastructure.taxonomy` — entity kinds, the lifecycle
  state machine, relationship semantics, and the canonical fact categories
  (``infrastructure_facts`` / ``infrastructure_state`` / ``deployments``);
* :mod:`~services.infrastructure.provider` — the ``Infrastructure360Provider``
  implementing the plane's ``IntelligenceProjectionProvider`` Protocol
  (``graph_mutation_policy == "read_only"``: no write path);
* :mod:`~services.infrastructure.routes` — the read-only ``/v1/infrastructure``
  FastAPI router (all GET, tenant-scoped, ``infrastructure360.read``-gated).

The blueprint is ``docs/blueprints/infrastructure360.md``.
"""

from __future__ import annotations

from services.infrastructure.contracts import (
    Deployment,
    InfrastructureEntity,
    InfrastructureEntityType,
    InfrastructureRelationship,
    InfrastructureRelationshipType,
    InfrastructureState,
)
from services.infrastructure.provider import (
    CanonicalInfrastructureRead,
    Infrastructure360Provider,
    register_provider,
)
from services.infrastructure.routes import (
    EXPLORE_CAPABILITY,
    READ_CAPABILITY,
    create_router,
    router,
)
from services.infrastructure.taxonomy import (
    DEPLOYMENT_TARGET_KINDS,
    INFRASTRUCTURE_FACT_CATEGORIES,
    LEGAL_STATE_TRANSITIONS,
    RELATIONSHIP_SEMANTICS,
    SUPPORTED_ENTITY_KINDS,
    can_transition,
    is_valid_kind,
    is_valid_relationship,
    requires_redeploy,
)

__all__ = [
    "CanonicalInfrastructureRead",
    "DEPLOYMENT_TARGET_KINDS",
    "Deployment",
    "EXPLORE_CAPABILITY",
    "INFRASTRUCTURE_FACT_CATEGORIES",
    "Infrastructure360Provider",
    "InfrastructureEntity",
    "InfrastructureEntityType",
    "InfrastructureRelationship",
    "InfrastructureRelationshipType",
    "InfrastructureState",
    "LEGAL_STATE_TRANSITIONS",
    "READ_CAPABILITY",
    "RELATIONSHIP_SEMANTICS",
    "SUPPORTED_ENTITY_KINDS",
    "can_transition",
    "create_router",
    "is_valid_kind",
    "is_valid_relationship",
    "register_provider",
    "requires_redeploy",
    "router",
]
