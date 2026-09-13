"""Canonical infrastructure domain contracts (Infrastructure360 vertical slice).

These are the canonical domain contracts for the *infrastructure* plane that
the infrastructure360 projection reads over. A 360 is an intelligence projection
over canonical Aether truth — never a competing system of record — so these
models describe **infrastructure facts as canonical Aether state** (entity
kinds, lifecycle states, deployments, relationships), and the provider in
:mod:`services.infrastructure.provider` composes them into a read-only
projection.

Reuse, never redefine: ``ContractModel``, ``EntityRef``, ``EvidenceRef``,
``PageRequest`` and ``TimeRangeFilter`` are the canonical operational-intelligence
primitives imported from ``services/operational_intelligence/models.py``. This
package deliberately declares NO second ``EntityRef`` / ``EvidenceRef`` /
``PageRequest`` / time-range primitive — the no-redefinition rule of ADR-010
(and the vertical-slice checklist §2) is enforced by test.

The domain models are tolerant ``ContractModel`` subclasses (additive fields
allowed) because they are canonical domain state, not projection-plane wire
contracts — the projection plane fails closed on the *projection* contracts
(``shared/intelligence_projections/contracts.py``), which is the boundary that
matters.

Enum values are lower_snake strings so they serialize cleanly to JSON/TS and
match the repo's lowercase literal convention (e.g. ``EntityKind``).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

# Canonical primitives — single-monolith reuse, NEVER redefined in this package.
from services.operational_intelligence.models import (
    ContractModel,
    EntityRef,
    EvidenceRef,
    PageRequest,
    TimeRangeFilter,
)

__all__ = [
    "ContractModel",
    "Deployment",
    "EntityRef",
    "EvidenceRef",
    "InfrastructureEntity",
    "InfrastructureEntityType",
    "InfrastructureRelationship",
    "InfrastructureRelationshipType",
    "InfrastructureState",
    "PageRequest",
    "TimeRangeFilter",
]


class InfrastructureEntityType(str, Enum):
    """The canonical kinds of infrastructure entity the projection understands.

    A closed, extensible vocabulary: new kinds are added to this enum (and to
    ``services/infrastructure/taxonomy.py``) — never to the provider — keeping
    the projection a reader over canonical vocabulary.
    """

    SERVICE = "service"
    DATABASE = "database"
    CACHE = "cache"
    QUEUE = "queue"
    WORKER = "worker"
    FUNCTION = "function"
    CONTAINER = "container"
    HOST = "host"
    NETWORK = "network"
    STORAGE = "storage"
    GATEWAY = "gateway"
    ORCHESTRATOR = "orchestrator"


class InfrastructureState(str, Enum):
    """Lifecycle state of an infrastructure entity.

    Legal transitions are declared in ``services/infrastructure/taxonomy.py``
    (a small legal-transition table). Notable: ``FAILED -> ACTIVE`` is ILLEGAL
    without an intervening redeploy (``FAILED -> PROVISIONED -> DEPLOYING ->
    ACTIVE``); the state machine treats a direct repair-to-active as a lie.
    """

    PROVISIONED = "provisioned"
    DEPLOYING = "deploying"
    ACTIVE = "active"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    DEPROVISIONING = "deprovisioning"
    FAILED = "failed"
    UNKNOWN = "unknown"


class InfrastructureRelationshipType(str, Enum):
    """Canonical infrastructure relationship (edge) semantics.

    Each type's meaning is declared once in ``services/infrastructure/taxonomy.py``
    (``RELATIONSHIP_SEMANTICS``) so the projection and any future consumer agree
    on what an edge means.
    """

    DEPENDS_ON = "depends_on"
    DEPLOYED_ON = "deployed_on"
    CONNECTS_TO = "connects_to"
    COMPOSED_OF = "composed_of"
    SCALES_WITH = "scales_with"


class InfrastructureRelationship(ContractModel):
    """One directed infrastructure relationship between two entities."""

    id: str
    tenant_id: str
    source_id: str
    target_id: str
    relationship_type: InfrastructureRelationshipType
    attributes: dict[str, Any] = {}


class Deployment(ContractModel):
    """A canonical deployment record.

    ``infra_entity_ref`` names the infrastructure entity the artifact deploys
    onto (e.g. the host / orchestrator id) — the projection uses it to join a
    deployment to its runtime home.
    """

    id: str
    tenant_id: str
    service_id: str
    artifact_ref: str
    state: InfrastructureState
    started_at: str
    completed_at: Optional[str] = None
    version: str
    infra_entity_ref: str


class InfrastructureEntity(ContractModel):
    """A canonical infrastructure entity (a fact, not a view).

    ``deployment_refs`` are the ids of the :class:`Deployment` records that ran
    on this entity; ``relationship_refs`` are the ids of
    :class:`InfrastructureRelationship` records touching it. Both are *refs* —
    the records themselves stay in the canonical authorities the projection
    reads.
    """

    id: str
    tenant_id: str
    kind: InfrastructureEntityType
    state: InfrastructureState
    display_name: str
    attributes: dict[str, Any] = {}
    deployment_refs: list[str] = []
    relationship_refs: list[str] = []
