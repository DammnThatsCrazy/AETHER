"""Task-profile registry bridge for the Aether model-runtime router.

Task profiles (canonical ``packages/shared/contracts/task-profile-registry.json``
and its generated Python twin ``shared/model_governance/generated_task_profiles.py``)
bind a model role, routing policy, guardrails, output kind, and latency/cost
bounds to a named harness task (ADR-008 D3/D4). This module is the
profile -> routing bridge: it validates a single profile as read-only data,
serves the registry, and applies a profile's routing policy to a
:class:`RoutingRequest`.

Security constraints:
* The registry is read-only data. Guardrail values are passed through
  opaquely -- the runtime enforces them, this module never does.
* This module never inspects, logs, or forwards secrets; it only ever carries
  profile metadata and routing-mode policy.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import cast

from pydantic import BaseModel, ConfigDict

from services.model_runtime.routing.models import (
    RoutingMode,
    RoutingPolicyViolation,
    RoutingRequest,
)
from shared.model_governance.generated_task_profiles import TASK_PROFILES

__all__ = [
    "ProfileNotFound",
    "ProfileRegistry",
    "TaskProfileView",
    "apply_profile",
    "routing_request_from_profile",
]

# Registry metadata carried alongside the policy fields that this view does not
# surface (the task profile's human-readable description). Allowed to be dropped
# during projection; any OTHER unknown field is rejected.
_IGNORED_METADATA = frozenset({"purpose"})


def _to_snake(name: str) -> str:
    """Map a registry camelCase (or kebab-case) key to snake_case.

    ``profileId -> profile_id``, ``maxTokens -> max_tokens``,
    ``timeoutMs -> timeout_ms``. Lowercase keys pass through unchanged.
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name.replace("-", "_")).lower()


class ProfileNotFound(KeyError):
    """Raised when a requested ``profile_id`` is absent from the registry.

    Subclasses :class:`KeyError` so existing ``dict``-style callers keep
    working while allowing a specific, named catch.
    """


class TaskProfileView(BaseModel):
    """Read-only, validated view of one task profile from the registry.

    The constructor takes the raw registry dict (camelCase keys as emitted by
    the JSON contract and the generated twin) and maps each key to snake_case.
    Descriptive metadata the view does not surface (``purpose``) is dropped;
    any other unknown field is rejected so a contract typo cannot silently drop
    policy. The model also ``extra="forbid"`` so no other construction path can
    smuggle in stray fields.

    Guardrail values are passed through opaquely: this view only carries them;
    the runtime enforces them.
    """

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    version: int
    model_role: str
    default_routing_mode: RoutingMode
    allowed_routing_modes: tuple[RoutingMode, ...]
    output_kind: str
    guardrails: tuple[str, ...]
    evidence_required: bool
    max_tokens: int
    timeout_ms: int
    max_retries: int

    def __init__(self, raw: Mapping[str, object], **kwargs: object) -> None:
        if kwargs:
            raise TypeError(
                "TaskProfileView() takes the raw registry dict; no keyword fields"
            )
        mapped = {_to_snake(key): value for key, value in raw.items()}
        declared = set(self.model_fields)
        unknown = set(mapped) - declared - _IGNORED_METADATA
        if unknown:
            raise ValueError(
                f"unknown task-profile fields: {sorted(unknown)}"
            )
        fields = {key: value for key, value in mapped.items() if key in declared}
        super().__init__(**fields)


def _default_registry() -> dict[str, Mapping[str, object]]:
    """Project the generated ``TASK_PROFILES`` tuple into id -> raw-dict form."""
    return {profile["profileId"]: profile for profile in TASK_PROFILES}


class ProfileRegistry:
    """Read-only registry of validated :class:`TaskProfileView` objects.

    ``raw`` maps a profile id to that profile's raw registry dict. It defaults
    to the generated task-profile registry. Only read methods are exposed; the
    backing mapping is immutable.
    """

    def __init__(self, raw: Mapping[str, object] | None = None) -> None:
        if raw is None:
            raw = _default_registry()
        views = {
            str(key): TaskProfileView(cast(Mapping[str, object], value))
            for key, value in raw.items()
        }
        self._profiles: Mapping[str, TaskProfileView] = MappingProxyType(views)

    def get(self, profile_id: str) -> TaskProfileView:
        """Return the validated profile for ``profile_id``.

        Raises :class:`ProfileNotFound` (a :class:`KeyError`) for unknown ids.
        """
        try:
            return self._profiles[profile_id]
        except KeyError:
            raise ProfileNotFound(profile_id) from None

    def all(self) -> tuple[TaskProfileView, ...]:
        """All profiles in registry insertion order."""
        return tuple(self._profiles.values())

    def ids(self) -> tuple[str, ...]:
        """All profile ids in registry insertion order."""
        return tuple(self._profiles)


def apply_profile(
    registry: ProfileRegistry, request: RoutingRequest
) -> RoutingRequest:
    """Bind a routing request to its task profile and return a NEW request.

    The input request is never mutated. The returned request has:

    * ``profile_id`` set (the request must already carry one -- a request with
      no profile cannot be policy-bound and raises ``RoutingPolicyViolation``);
    * ``mode`` resolved to the profile's ``default_routing_mode`` when the
      request left it as ``None``;
    * the resolved mode validated against the profile's ``allowed_routing_modes``
      (``RoutingPolicyViolation`` when disallowed).

    Raises ``ProfileNotFound`` when the request's profile id is unknown.
    """
    if request.profile_id is None:
        raise RoutingPolicyViolation(
            "apply_profile requires request.profile_id to be set"
        )
    profile = registry.get(request.profile_id)
    mode = request.mode if request.mode is not None else profile.default_routing_mode
    if mode not in profile.allowed_routing_modes:
        raise RoutingPolicyViolation(
            f"routing mode {mode.value!r} is not allowed for task profile "
            f"{profile.profile_id!r}"
        )
    return request.model_copy(update={"profile_id": profile.profile_id, "mode": mode})


def routing_request_from_profile(
    registry: ProfileRegistry,
    profile_id: str,
    *,
    tenant_id: str,
    requested_model: str | None = None,
    tenant_default_model: str | None = None,
    entitled_model_ids: set[str] | None = None,
) -> RoutingRequest:
    """Convenience constructor for a routing request bound to a task profile.

    The returned request carries the profile id and leaves ``mode`` as ``None``
    so :func:`apply_profile` resolves it from the profile's default routing
    mode. Raises ``ProfileNotFound`` for an unknown profile id.
    """
    profile = registry.get(profile_id)
    return RoutingRequest(
        tenant_id=tenant_id,
        profile_id=profile.profile_id,
        mode=None,
        requested_model=requested_model,
        tenant_default_model=tenant_default_model,
        entitled_model_ids=entitled_model_ids,
    )
