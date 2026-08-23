"""TaskProfileService — facade over the versioned task-profile runtime.

The model runtime, the Aether UX, and the Kyber control plane call this
facade (ADR-008 D3/D4/D7) to resolve a task profile + version, render its
prompt, validate its output kind, and describe its execution bounds.

The service composes Commit-7's versioned task-profile modules (runtime,
prompt_loader, output_schema, registry_api, versioning) and Commit-5's
:class:`ProfileRegistry`. It never enforces guardrails itself -- it only
carries the profile's guardrail summary opaquely and lets the runtime
enforce them.

Security constraints: ``describe`` projects through :func:`profile_summary`
so the facade never emits secrets or un-allowlisted profile metadata, and
``prompt`` returns raw template text only from the catalog (no rendering, no
interpolation of caller-supplied tenant/instructions content).
"""

from __future__ import annotations

from services.model_runtime.routing.profiles import (
    ProfileRegistry,
    TaskProfileView,
)
from services.model_runtime.task_profiles.output_schema import (
    OutputValidation,
    SchemaOutputValidator,
)
from services.model_runtime.task_profiles.prompt_loader import PromptCatalog
from services.model_runtime.task_profiles.registry_api import profile_summary
from services.model_runtime.task_profiles.versioning import (
    VersionedProfileStore,
    VersionPolicy,
    VersionResolver,
)

__all__ = ["ProfileResolutionError", "TaskProfileService"]


class ProfileResolutionError(Exception):
    """Bad composition / unusable task-profile runtime state.

    Raised when the facade cannot fulfil a call because its composed
    components cannot produce the requested artifact (for example the prompt
    catalog has no prompt for the profile's role). It is NOT raised for an
    unknown profile id or a version-policy mismatch -- those surface as
    :class:`ProfileVersionError` from the resolver/store.
    """


class TaskProfileService:
    """Facade over the versioned task-profile runtime.

    Composes Commit-7 modules (runtime, prompt_loader, output_schema,
    registry_api, versioning) and Commit-5's :class:`ProfileRegistry`. Safe for
    the runtime, Aether UX, and Kyber control plane to call.
    """

    def __init__(
        self,
        registry: ProfileRegistry | None = None,
        *,
        prompt_catalog: PromptCatalog | None = None,
        output_validator: SchemaOutputValidator | None = None,
    ) -> None:
        self._registry = registry if registry is not None else ProfileRegistry()
        # Version policy resolution and the versioned view store (versioning.py)
        # are built from THIS registry so a custom registry is resolved with its
        # own versions, never the module-level default.
        self._resolver = VersionResolver(
            version_map={
                profile.profile_id: (profile.version,)
                for profile in self._registry.all()
            }
        )
        self._store = VersionedProfileStore(profiles=self._registry.all())
        self._prompt_catalog = (
            prompt_catalog if prompt_catalog is not None else PromptCatalog()
        )
        self._output_validator = (
            output_validator
            if output_validator is not None
            else SchemaOutputValidator()
        )

    def resolve(
        self,
        profile_id: str,
        *,
        version_policy: VersionPolicy = VersionPolicy.LATEST,
        requested_version: int | None = None,
    ) -> TaskProfileView:
        """Resolve ``profile_id`` to a validated :class:`TaskProfileView`.

        Version policy is delegated to :class:`VersionResolver` (keyword
        ``policy``) which returns the version int; the exact
        ``(profile_id, version)`` view is then fetched from
        :class:`VersionedProfileStore`. Raises :class:`ProfileVersionError`
        (fail-closed) for an unknown profile or an unavailable version.
        """
        version = self._resolver.resolve(
            profile_id,
            policy=version_policy,
            requested_version=requested_version,
        )
        return self._store.get(profile_id, version)

    def prompt(self, view: TaskProfileView) -> str:
        """Return the raw prompt text for the profile's role + version.

        Composed from :class:`PromptCatalog` keyed by ``view.model_role`` with
        the version taken from ``view.version``. Raises
        :class:`ProfileResolutionError` when the catalog cannot supply a
        non-empty prompt for that composition.
        """
        try:
            prompt = self._prompt_catalog.get(view.model_role, version=view.version)
        except KeyError as exc:
            raise ProfileResolutionError(
                f"no prompt available for task profile {view.profile_id!r} "
                f"(role {view.model_role!r}, version {view.version})"
            ) from exc
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProfileResolutionError(
                f"empty prompt for task profile {view.profile_id!r} "
                f"(role {view.model_role!r}, version {view.version})"
            )
        return prompt

    def validate_output(
        self, view: TaskProfileView, output: object
    ) -> OutputValidation:
        """Validate ``output`` against the profile's declared ``output_kind``.

        Composed from :class:`SchemaOutputValidator`. Returns an
        :class:`OutputValidation`; never raises for a shape mismatch.
        """
        return self._output_validator.validate(view.output_kind, output)

    def guardrail_summary(self, view: TaskProfileView) -> tuple[str, ...]:
        """Opaque guardrail summary for the profile (the runtime enforces)."""
        return view.guardrails

    def describe(self, view: TaskProfileView) -> dict[str, object]:
        """Display-safe summary of the profile's execution bounds.

        Projected through :func:`profile_summary` so only allowlisted,
        secret-free keys are emitted.
        """
        return profile_summary(view)
