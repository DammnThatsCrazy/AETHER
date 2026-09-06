"""Reconciled Control Plane — managed-integration abstraction (Phase 0).

Phase 0 establishes the ``ManagedIntegration`` abstraction + reconcile
*skeleton* only. There is no live reconcile trigger and no actuator: drift is
classified, evidence is persisted, and applying a ChangeSet is explicitly
deferred (CP-08 boundary).

Submodules:
* ``contracts``   — vocabulary + view models (TS twin in packages/shared).
* ``availability``— CP-12 typed-availability helpers (never fabricate).
* ``desired_policy`` — desired-state assembly from release-channel policy.
* ``sensors``    — read-only observed-state adapters over existing authorities.
* ``reconciler`` — desired-vs-observed classification (steps 1-11 of blueprint
  §32); produces DRAFT change summaries, never applies them.
* ``repository`` — durable ``managed_integrations`` + ``reconcile_runs`` stores.
* ``routes``     — read-only operator surface (``/v1/admin/kyber/managed-integrations``).
"""

from services.managed_integrations.availability import (
    is_availability,
    availability_from_readiness,
)
from services.managed_integrations.contracts import (
    DEFAULT_MANAGED_RELEASE_CHANNEL,
    DesiredStateSpec,
    DriftRecord,
    ManagedIntegrationView,
    ObservedStateSnapshot,
    ReconcileRunView,
)
from services.managed_integrations.desired_policy import (
    build_desired_state,
    minimum_runtime_version_for_channel,
)
from services.managed_integrations.reconciler import reconcile

__all__ = [
    "DEFAULT_MANAGED_RELEASE_CHANNEL",
    "DesiredStateSpec",
    "DriftRecord",
    "ManagedIntegrationView",
    "ObservedStateSnapshot",
    "ReconcileRunView",
    "availability_from_readiness",
    "build_desired_state",
    "is_availability",
    "minimum_runtime_version_for_channel",
    "reconcile",
]
