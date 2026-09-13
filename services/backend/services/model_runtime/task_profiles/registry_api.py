"""Read-only task-profile registry query API (ADR-008 D3).

The generated task-profile registry
(``shared/model_governance/generated_task_profiles.py``) is the single source
of truth for harness task profiles; the Kyber control plane and the model
runtime both consume this read API over it.  The module is a pure,
dependency-free read API: constructing a :class:`ProfileQuery` performs no I/O,
and the module-level default query is built lazily so importing this module has
zero side effects and it can be imported from anywhere.

Security constraints:

* ``profile_summary`` and :class:`ProfileRegistrySnapshot` are audit/display-safe:
  they surface only the documented profile metadata.  Task profiles carry no
  secrets, and this module never inspects, logs, or forwards any.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from services.model_runtime.routing.profiles import ProfileRegistry, TaskProfileView
from shared.model_governance.generated_task_profiles import TASK_PROFILE_REGISTRY_VERSION

__all__ = [
    "ProfileQuery",
    "ProfileRegistrySnapshot",
    "get_default_query",
    "profile_summary",
]

#: Field allowlist surfaced by :func:`profile_summary` -- audit/display-safe.
_SUMMARY_FIELDS: tuple[str, ...] = (
    "profile_id",
    "version",
    "model_role",
    "default_routing_mode",
    "allowed_routing_modes",
    "output_kind",
    "guardrails",
    "evidence_required",
    "max_tokens",
    "timeout_ms",
    "max_retries",
)


def profile_summary(view: TaskProfileView) -> dict[str, object]:
    """Project a task profile into an audit/display-safe plain dict.

    Only the fields in ``_SUMMARY_FIELDS`` are emitted -- no secrets, no
    metadata beyond the documented allowlist.  ``RoutingMode`` members are
    emitted as their string values so the dict is JSON-round-trippable.
    """
    return {
        "profile_id": view.profile_id,
        "version": view.version,
        "model_role": view.model_role,
        "default_routing_mode": view.default_routing_mode.value,
        "allowed_routing_modes": tuple(m.value for m in view.allowed_routing_modes),
        "output_kind": view.output_kind,
        "guardrails": view.guardrails,
        "evidence_required": view.evidence_required,
        "max_tokens": view.max_tokens,
        "timeout_ms": view.timeout_ms,
        "max_retries": view.max_retries,
    }


class ProfileQuery:
    """Read-only, side-effect-free query API over a :class:`ProfileRegistry`.

    Query methods return tuples of :class:`TaskProfileView` in registry
    insertion order.  The query holds no mutable state and performs no I/O, so
    it is safe to construct and share anywhere.
    """

    def __init__(self, registry: ProfileRegistry) -> None:
        self._registry = registry

    def by_role(self, role: str) -> tuple[TaskProfileView, ...]:
        """Profiles whose ``model_role`` matches ``role``."""
        return tuple(p for p in self._registry.all() if p.model_role == role)

    def by_output_kind(self, kind: str) -> tuple[TaskProfileView, ...]:
        """Profiles whose ``output_kind`` matches ``kind``."""
        return tuple(p for p in self._registry.all() if p.output_kind == kind)

    def with_guardrail(self, guardrail: str) -> tuple[TaskProfileView, ...]:
        """Profiles requiring ``guardrail``.

        The registry surfaces the ``evidence_required`` guardrail kind both as a
        literal guardrail string and as the first-class ``evidence_required``
        boolean, so both evidence-bearing profiles match it.
        """
        return tuple(
            p
            for p in self._registry.all()
            if guardrail in p.guardrails
            or (guardrail == "evidence_required" and p.evidence_required)
        )

    def all(self) -> tuple[TaskProfileView, ...]:
        """All profiles in registry insertion order."""
        return self._registry.all()

    def summary(self) -> dict[str, object]:
        """Registry metadata for control-plane display.

        Returns the registry version, counts per model role, counts per output
        kind, and the ordered list of profile ids.
        """
        profiles = self._registry.all()
        return {
            "version": TASK_PROFILE_REGISTRY_VERSION,
            "role_counts": dict(Counter(p.model_role for p in profiles)),
            "output_kind_counts": dict(Counter(p.output_kind for p in profiles)),
            "profile_ids": self._registry.ids(),
        }


class ProfileRegistrySnapshot(BaseModel, frozen=True):
    """Immutable snapshot of the task-profile registry for API responses.

    ``profiles`` carries :func:`profile_summary` dicts (audit/display-safe), so
    the snapshot serializes to JSON without leaking anything and round-trips
    through ``model_dump()`` / reconstruction.
    """

    model_config = ConfigDict(extra="forbid")

    version: str
    profiles: tuple[dict[str, object], ...]


_default_query: ProfileQuery | None = None


def get_default_query() -> ProfileQuery:
    """Return the module-level default query over the generated registry.

    Constructed lazily on first call so importing this module has zero side
    effects.  Subsequent calls return the same cached query.
    """
    global _default_query
    if _default_query is None:
        _default_query = ProfileQuery(ProfileRegistry())
    return _default_query
