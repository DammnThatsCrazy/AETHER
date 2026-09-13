"""Versioned task-profile runtime public API (ADR-008 D3/D4/D7).

:class:`TaskProfileService` is the facade the model runtime, the Aether UX, and
the Kyber control plane call to resolve a profile + version, render its prompt,
validate its output kind, and describe its execution bounds.

This package re-exports the Commit-7 modules:

* ``runtime`` — profile-version resolution and the task-profile runtime
  (:class:`ProfileVersionResolver`, :class:`TaskProfileRuntime`);
* ``prompt_loader`` — prompt catalog / safety / renderer
  (:class:`PromptCatalog`, :class:`PromptSafety`, :class:`PromptRenderer`,
  :class:`PromptInjectionError`, ``ALLOWED_PLACEHOLDERS``);
* ``output_schema`` — output-kind validation
  (:class:`OutputValidator`, :class:`OutputValidation`,
  :class:`SchemaOutputValidator`, :class:`OutputValidationError`);
* ``registry_api`` — profile query + display-safe summary
  (:class:`ProfileQuery`, :func:`profile_summary`, :func:`get_default_query`,
  :class:`ProfileRegistrySnapshot`);
* ``versioning`` — version policy / resolution
  (:class:`VersionPolicy`, :class:`VersionResolver`,
  :class:`ProfileVersionError`, :class:`VersionedProfileStore`);
* ``service`` — the facade (:class:`TaskProfileService`,
  :class:`ProfileResolutionError`).
"""

from __future__ import annotations

from services.model_runtime.task_profiles.output_schema import (
    OutputValidation,
    OutputValidationError,
    OutputValidator,
    SchemaOutputValidator,
)
from services.model_runtime.task_profiles.prompt_loader import (
    ALLOWED_PLACEHOLDERS,
    PromptCatalog,
    PromptInjectionError,
    PromptRenderer,
    PromptSafety,
)
from services.model_runtime.task_profiles.registry_api import (
    ProfileQuery,
    ProfileRegistrySnapshot,
    get_default_query,
    profile_summary,
)
from services.model_runtime.task_profiles.runtime import (
    ProfileVersionResolver,
    TaskProfileRuntime,
)
from services.model_runtime.task_profiles.service import (
    ProfileResolutionError,
    TaskProfileService,
)
from services.model_runtime.task_profiles.versioning import (
    ProfileVersionError,
    VersionPolicy,
    VersionResolver,
    VersionedProfileStore,
)

__all__ = [
    # task_profiles/runtime.py — profile-version resolution + runtime
    "ProfileVersionResolver",
    "TaskProfileRuntime",
    # task_profiles/prompt_loader.py — prompt catalog/safety/renderer
    "ALLOWED_PLACEHOLDERS",
    "PromptCatalog",
    "PromptInjectionError",
    "PromptRenderer",
    "PromptSafety",
    # task_profiles/output_schema.py — output-kind validation
    "OutputValidation",
    "OutputValidationError",
    "OutputValidator",
    "SchemaOutputValidator",
    # task_profiles/registry_api.py — profile query + display-safe summary
    "ProfileQuery",
    "ProfileRegistrySnapshot",
    "get_default_query",
    "profile_summary",
    # task_profiles/versioning.py — version policy / resolution
    "ProfileVersionError",
    "VersionPolicy",
    "VersionResolver",
    "VersionedProfileStore",
    # task_profiles/service.py — the facade
    "ProfileResolutionError",
    "TaskProfileService",
]
