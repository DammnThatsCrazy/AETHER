"""Versioned task-profile runtime for the Aether model-runtime (ADR-008 D3/D4).

Commit 5 (``routing/profiles.py``) built the profile -> routing bridge:
validated :class:`TaskProfileView` objects over the generated registry and
:func:`apply_profile`, which binds a profile's routing policy to a
:class:`RoutingRequest`. This module is the versioned RUNTIME on top of it:
resolving a profile version, enforcing action-kind guardrails, and executing a
task under a profile by binding its policy and asking the router for a
:class:`RouteSelection`. Model invocation is the model_runtime service's job
(Commit 5), not this module's.

Security:
* Guardrails are enforced here for ACTION-KIND only. The runtime never
  executes writes itself: a ``read_only`` profile is honored by refusing a
  write-ish action before any route is constructed.
* ``tenant_scope`` is a PRESENCE check (a scope token must be supplied), never
  a scope decision. The runtime never evaluates, mints, or widens scope; scope
  authority stays server-side with the caller.
* This module carries only model ids, profile metadata, and routing modes. It
  never touches credentials, tenant content, or secrets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from services.model_runtime.routing.models import (
    RoutingMode,
    RoutingPolicyViolation,
    RoutingRequest,
    RoutingUnavailable,
    RouteSelection,
)
from services.model_runtime.routing.profiles import (
    ProfileNotFound,
    ProfileRegistry,
    TaskProfileView,
    apply_profile,
)

if TYPE_CHECKING:
    from services.model_runtime.routing.engine import ModelRouter

__all__ = [
    "WRITE_KEYWORDS",
    "ProfileVersionNotFound",
    "ProfileVersionResolver",
    "TaskProfileRuntime",
]

# Action tokens the read_only guardrail treats as write-ish (ADR-008 D3). An
# action containing any of these tokens is a write; anything else is read.
WRITE_KEYWORDS: tuple[str, ...] = (
    "write",
    "create",
    "update",
    "delete",
    "insert",
    "drop",
    "grant",
    "revoke",
    "truncate",
)

# Registry default version. The generated registry ships every profile at
# version 1; keeping the default here means a future multi-version registry
# needs only a new mapping, not a change of call sites.
DEFAULT_PROFILE_VERSION = 1


class ProfileVersionNotFound(ProfileNotFound):
    """Raised when a profile exists but the requested ``version`` does not.

    Subclasses :class:`ProfileNotFound` (a :class:`KeyError`), so callers that
    already catch the unknown-profile error also catch an unknown version.
    """


class ProfileVersionResolver:
    """Resolves a ``profile_id`` to a specific, validated profile version.

    The generated registry is single-version (every profile is version 1), so
    the resolver indexes each profile by version and defaults to the registry
    version. It is designed for multi-version registries: ``versions`` injects
    extra ``{version: raw dict}`` mappings per profile id, each projected
    through :class:`TaskProfileView` exactly like the registry data.
    """

    def __init__(
        self,
        registry: ProfileRegistry,
        *,
        versions: Mapping[str, Mapping[int, Mapping[str, object]]] | None = None,
    ) -> None:
        self._by_profile: dict[str, dict[int, TaskProfileView]] = {}
        for profile in registry.all():
            self._by_profile.setdefault(profile.profile_id, {})[profile.version] = profile
        if versions:
            for profile_id, version_map in versions.items():
                bucket = self._by_profile.setdefault(profile_id, {})
                for version, raw in version_map.items():
                    bucket[version] = TaskProfileView(raw)

    def resolve(self, profile_id: str, *, version: int | None = None) -> TaskProfileView:
        """Return the exact ``version`` of ``profile_id``, else the default.

        Raises :class:`ProfileNotFound` for an unknown profile id and
        :class:`ProfileVersionNotFound` for a known profile with an unknown
        version.
        """
        versions = self._by_profile.get(profile_id)
        if versions is None:
            raise ProfileNotFound(profile_id)
        if version is not None:
            view = versions.get(version)
            if view is None:
                raise ProfileVersionNotFound(f"{profile_id}@v{version}")
            return view
        view = versions.get(DEFAULT_PROFILE_VERSION)
        if view is None:
            raise ProfileVersionNotFound(
                f"{profile_id} has no default version {DEFAULT_PROFILE_VERSION}"
            )
        return view


class TaskProfileRuntime:
    """Executes a task under a task profile (versioned runtime).

    ``registry`` is the read-only :class:`ProfileRegistry`; ``router`` is the
    Commit 5 :class:`ModelRouter`, imported lazily so this module loads cleanly
    during concurrent development. The runtime resolves the profile version,
    enforces action-kind guardrails, binds the routing policy via
    :func:`apply_profile`, and returns the router's :class:`RouteSelection`.
    """

    def __init__(
        self,
        registry: ProfileRegistry,
        router: ModelRouter | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = ProfileVersionResolver(registry)
        # ModelRouter is only imported (and required) at execute time.
        self._router: ModelRouter | None = router

    def profile(self, profile_id: str) -> TaskProfileView:
        """Resolve ``profile_id`` to its default validated profile version."""
        return self._resolver.resolve(profile_id)

    def validate_guardrails(
        self,
        profile: TaskProfileView,
        requested_actions: Sequence[str] | None = None,
        *,
        scope_token: str | None = None,
    ) -> list[str]:
        """Return reasons each guardrail blocks the request (empty = pass).

        A ``read_only`` profile rejects any write-ish action (containing a
        :data:`WRITE_KEYWORDS` token). A ``tenant_scope`` profile requires a
        non-empty ``scope_token`` -- a presence check only; the runtime never
        evaluates the token's meaning.
        """
        reasons: list[str] = []
        guardrails = frozenset(profile.guardrails)

        if "read_only" in guardrails:
            for action in requested_actions or ():
                if self._is_write_action(action):
                    reasons.append(
                        f"read_only profile rejects write action {action!r}"
                    )

        if "tenant_scope" in guardrails and not scope_token:
            reasons.append("tenant_scope guardrail requires a scope token")

        return reasons

    async def execute(
        self,
        *,
        profile_id: str,
        tenant_id: str,
        messages: list[dict[str, str]],
        requested_model: str | None = None,
        mode: RoutingMode | None = None,
        requested_actions: Sequence[str] | None = None,
        scope_token: str | None = None,
    ) -> RouteSelection:
        """Route one task under ``profile_id`` and return the selection.

        Resolves the profile version, rejects malformed task messages, enforces
        the profile's action-kind guardrails (raising
        :class:`RoutingPolicyViolation` with joined reasons on a violation),
        binds the routing policy with :func:`apply_profile`, and returns the
        router's selection. Raises :class:`RoutingUnavailable` when no router
        is configured. Model invocation is out of scope.
        """
        profile = self.profile(profile_id)
        self._validate_messages(messages)

        reasons = self.validate_guardrails(
            profile, requested_actions=requested_actions, scope_token=scope_token
        )
        if reasons:
            raise RoutingPolicyViolation("; ".join(reasons))

        router = self._router
        if router is None:
            raise RoutingUnavailable("task profile runtime has no router configured")

        request = RoutingRequest(
            tenant_id=tenant_id,
            profile_id=profile.profile_id,
            mode=mode,
            requested_model=requested_model,
        )
        bound = apply_profile(self._registry, request)
        return await router.route(bound)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _is_write_action(action: str) -> bool:
        """Whether ``action`` is write-ish (contains a WRITE_KEYWORDS token)."""
        lowered = action.lower()
        return any(token in lowered for token in WRITE_KEYWORDS)

    @staticmethod
    def _validate_messages(messages: list[dict[str, str]]) -> None:
        """Gate malformed task messages before any guardrail or route work."""
        if not isinstance(messages, list):
            raise RoutingPolicyViolation(
                "task messages must be a list of {role, content} dicts"
            )
        for message in messages:
            if not isinstance(message, dict):
                raise RoutingPolicyViolation(
                    "task messages must be dicts with role and content"
                )
            if "role" not in message or "content" not in message:
                raise RoutingPolicyViolation(
                    "task message requires both 'role' and 'content'"
                )
