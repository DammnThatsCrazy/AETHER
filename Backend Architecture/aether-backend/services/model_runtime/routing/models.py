"""Provider-neutral routing/policy data models for the Aether model-runtime.

Routing selects a model for a request according to a mode (``auto``,
``tenant_default``, ``explicit``, ``policy_required``), subjects every route to
entitlement checks, and records the selected route plus any fallback decision
for audit and observability.

Security constraints: these models are pure data. They must NEVER carry
credentials, API keys, authorization headers, or tenant-restricted request
content; ``model_id``/``model`` fields only. No DB access, no I/O.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict

from services.model_runtime.models import ModelProvider


class RoutingMode(str, enum.Enum):
    """How the harness selects a model for a routed request.

    NOTE: values must string-match ``ROUTING_MODES`` in the generated
    task-profile registry
    (``shared/model_governance/generated_task_profiles.py``).
    """

    AUTO = "auto"
    TENANT_DEFAULT = "tenant_default"
    EXPLICIT = "explicit"
    POLICY_REQUIRED = "policy_required"


class EntitlementDecision(BaseModel, frozen=True):
    """Result of an entitlement check for one model/tenant pair.

    Immutable: the check outcome is recorded once and never mutated.
    """

    model_id: str
    tenant_id: str
    entitled: bool
    reason: str  # why the route was granted or denied


class RouteSelection(BaseModel, frozen=True):
    """The outcome of routing BEFORE model invocation.

    Immutable: a selected route is a fact to be audited, not edited.
    ``fallback`` is True when a fallback replaced the requested route;
    ``fallback_reason`` explains why (unavailable, misconfigured, over budget).
    """

    model_id: str
    provider: ModelProvider
    mode: RoutingMode
    entitled: bool
    fallback: bool
    fallback_reason: str | None


class RouteAuditEntry(BaseModel):
    """Observability/audit record for a single routing decision.

    Mutable record (append-only in practice); unknown fields are rejected so a
    typo cannot silently drop audit data.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    profile_id: str | None
    requested_model: str | None
    selected_model: str
    mode: RoutingMode
    entitled: bool
    fallback: bool
    fallback_reason: str | None
    decision_ms: float
    correlation_id: str | None = None


class RoutingRequest(BaseModel):
    """What the router consumes to make a routing decision.

    ``mode`` None means "use the profile default (or ``auto``)". ``requested_model``
    carries the explicit/policy-mandated model id. ``entitled_model_ids`` is an
    optional allowlist; None means the route was not pre-filtered.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    profile_id: str | None = None
    mode: RoutingMode | None = None
    requested_model: str | None = None
    tenant_default_model: str | None = None
    entitled_model_ids: set[str] | None = None


class RoutingResolutionError(Exception):
    """Base error for routing/policy resolution failures."""


class RoutingNotEntitled(RoutingResolutionError):
    """Raised when a route is denied by entitlement checks."""


class RoutingUnavailable(RoutingResolutionError):
    """Raised when the requested route is unavailable/misconfigured."""


class RoutingPolicyViolation(RoutingResolutionError):
    """Raised when a request violates a routing policy."""


__all__ = [
    "EntitlementDecision",
    "RouteAuditEntry",
    "RouteSelection",
    "RoutingMode",
    "RoutingNotEntitled",
    "RoutingPolicyViolation",
    "RoutingRequest",
    "RoutingResolutionError",
    "RoutingUnavailable",
]
