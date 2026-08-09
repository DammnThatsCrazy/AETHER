"""TaskProfileService facade tests — resolve, prompt, output validation, describe.

Covers the Commit-7 facade (ADR-008 D3/D4/D7) the model runtime, the Aether UX,
and the Kyber control plane call: versioned profile resolution, prompt loading,
output-kind validation, guardrail summary, and display-safe description.

The facade composes Commit-7 modules (runtime, prompt_loader, output_schema,
registry_api, versioning) and Commit-5's ProfileRegistry; these tests exercise
that composition end to end. Plain asserts only (no pytest fixtures/raises).
"""
from __future__ import annotations

import re

from services.model_runtime.routing.profiles import (
    ProfileRegistry,
    TaskProfileView,
)
from services.model_runtime.task_profiles import (
    ALLOWED_PLACEHOLDERS,
    OutputValidation,
    OutputValidationError,
    OutputValidator,
    ProfileQuery,
    ProfileRegistrySnapshot,
    ProfileResolutionError,
    ProfileVersionError,
    ProfileVersionResolver,
    PromptCatalog,
    PromptInjectionError,
    PromptRenderer,
    PromptSafety,
    SchemaOutputValidator,
    TaskProfileRuntime,
    TaskProfileService,
    VersionPolicy,
    VersionResolver,
    VersionedProfileStore,
    get_default_query,
    profile_summary,
)
from shared.model_governance.generated_task_profiles import TASK_PROFILES


#: Fields :func:`profile_summary` is allowed to emit (audit/display-safe).
_ALLOWED_DESCRIBE_KEYS = frozenset(
    {
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
    }
)

#: Key-name patterns that would indicate a secret/metadata leak in a summary.
#: Word-boundary anchored so the legitimate execution-bound field "max_tokens"
#: (an allowlisted summary key) is not flagged by the bare "token" hint.
_SECRET_KEY_RE = re.compile(
    r"\b(secret|password|api[_-]?key|token|credential|authorization|purpose)\b",
    re.IGNORECASE,
)


def _service() -> TaskProfileService:
    return TaskProfileService()


def test_package_imports_cleanly():
    # The package __init__ re-exports the full task_profiles public API.
    import services.model_runtime.task_profiles as task_profiles

    for name in (
        # runtime
        "ProfileVersionResolver",
        "TaskProfileRuntime",
        # prompt_loader
        "ALLOWED_PLACEHOLDERS",
        "PromptCatalog",
        "PromptInjectionError",
        "PromptRenderer",
        "PromptSafety",
        # output_schema
        "OutputValidation",
        "OutputValidationError",
        "OutputValidator",
        "SchemaOutputValidator",
        # registry_api
        "ProfileQuery",
        "ProfileRegistrySnapshot",
        "get_default_query",
        "profile_summary",
        # versioning
        "ProfileVersionError",
        "VersionPolicy",
        "VersionResolver",
        "VersionedProfileStore",
        # service
        "ProfileResolutionError",
        "TaskProfileService",
    ):
        assert hasattr(task_profiles, name), f"task_profiles missing export {name!r}"


def test_resolve_latest_returns_profile():
    service = _service()
    view = service.resolve("noesis_query_planning")
    assert isinstance(view, TaskProfileView)
    assert view.profile_id == "noesis_query_planning"
    assert view.version == 1
    assert view.output_kind == "query_plan"


def test_resolve_latest_matches_registry():
    service = _service()
    view = service.resolve("noesis_query_planning")
    registry_view = ProfileRegistry().get("noesis_query_planning")
    assert view == registry_view


def test_resolve_explicit_version():
    service = _service()
    view = service.resolve(
        "noesis_query_planning",
        version_policy=VersionPolicy.EXPLICIT,
        requested_version=1,
    )
    assert view.profile_id == "noesis_query_planning"
    assert view.version == 1


def test_resolve_pinned_version():
    service = _service()
    view = service.resolve(
        "noesis_query_planning",
        version_policy=VersionPolicy.PINNED,
        requested_version=1,
    )
    assert view.version == 1


def test_resolve_unknown_profile_raises():
    service = _service()
    raised = False
    try:
        service.resolve("does_not_exist")
    except ProfileVersionError:
        raised = True
    assert raised, "expected ProfileVersionError for an unknown profile"


def test_prompt_non_empty_for_noesis_query_planning():
    service = _service()
    view = service.resolve("noesis_query_planning")
    prompt = service.prompt(view)
    assert isinstance(prompt, str)
    assert prompt.strip()


def test_prompt_for_planning_role_is_safety_clean():
    service = _service()
    view = service.resolve("noesis_query_planning")
    prompt = service.prompt(view)
    assert PromptSafety.validate(prompt) == []


def test_prompt_raises_resolution_error_for_unknown_role():
    # A catalog that cannot supply the profile's role ("planning") is a bad
    # composition -> ProfileResolutionError, not a bare KeyError.
    service = TaskProfileService(
        prompt_catalog=PromptCatalog({"extraction": {1: "extract only"}})
    )
    view = service.resolve("noesis_query_planning")
    raised = False
    try:
        service.prompt(view)
    except ProfileResolutionError:
        raised = True
    assert raised, "expected ProfileResolutionError for a prompt-less role"


def test_service_honors_custom_prompt_catalog():
    service = TaskProfileService(
        prompt_catalog=PromptCatalog({"planning": {1: "custom planning prompt"}})
    )
    view = service.resolve("noesis_query_planning")
    assert service.prompt(view) == "custom planning prompt"


def test_validate_output_valid_query_plan_passes():
    service = _service()
    view = service.resolve("noesis_query_planning")
    valid_plan = {
        "steps": [
            {"intent": "find entities", "mode": "allowlisted"},
            {"intent": "resolve relations", "mode": "deterministic"},
        ],
    }
    result = service.validate_output(view, valid_plan)
    assert isinstance(result, OutputValidation)
    assert result.kind == "query_plan"
    assert result.valid is True
    assert result.errors == ()


def test_validate_output_invalid_query_plan_fails():
    service = _service()
    view = service.resolve("noesis_query_planning")
    invalid_plan = {"steps": [{"intent": "", "mode": "freeform"}]}
    result = service.validate_output(view, invalid_plan)
    assert result.kind == "query_plan"
    assert result.valid is False
    assert result.errors


def test_validate_output_rejects_raw_query_text():
    # A plan step that smuggles SQL is rejected before it can execute.
    service = _service()
    view = service.resolve("noesis_query_planning")
    plan_with_sql = {"steps": [{"intent": "select all rows", "mode": "allowlisted"}]}
    result = service.validate_output(view, plan_with_sql)
    assert result.valid is False
    assert result.errors


def test_validate_output_structural_mismatch_fails():
    service = _service()
    view = service.resolve("noesis_query_planning")
    result = service.validate_output(view, "not a query plan")
    assert result.kind == "query_plan"
    assert result.valid is False
    assert result.errors


def test_guardrail_summary_matches_registry():
    service = _service()
    view = service.resolve("noesis_query_planning")
    registry_view = ProfileRegistry().get("noesis_query_planning")
    assert service.guardrail_summary(view) == registry_view.guardrails
    assert service.guardrail_summary(view) == (
        "read_only",
        "tenant_scope",
        "allowlist_plan",
        "no_write_keywords",
        "no_injection",
    )


def test_describe_has_no_secrets_and_only_allowlisted_keys():
    service = _service()
    view = service.resolve("noesis_query_planning")
    summary = service.describe(view)
    assert isinstance(summary, dict)
    assert set(summary) <= _ALLOWED_DESCRIBE_KEYS, (
        f"unexpected summary keys: {sorted(set(summary) - _ALLOWED_DESCRIBE_KEYS)}"
    )
    for key in summary:
        assert not _SECRET_KEY_RE.search(key), (
            f"summary key {key!r} looks like a secret/metadata leak"
        )
    assert summary["profile_id"] == "noesis_query_planning"
    assert summary["version"] == 1
    assert summary["output_kind"] == "query_plan"
    assert summary["guardrails"] == view.guardrails


def test_describe_emits_string_routing_mode():
    service = _service()
    view = service.resolve("noesis_query_planning")
    summary = service.describe(view)
    # RoutingMode members are emitted as plain string values (JSON-safe).
    assert summary["default_routing_mode"] == "auto"
    assert summary["allowed_routing_modes"] == ("auto", "tenant_default", "explicit")


def test_guardrail_and_output_kind_of_every_registered_profile():
    # The facade resolves every generated profile and its summary is display-safe.
    service = _service()
    registry = ProfileRegistry()
    for raw in TASK_PROFILES:
        profile_id = raw["profileId"]
        view = service.resolve(profile_id)
        assert view == registry.get(profile_id)
        assert service.guardrail_summary(view) == tuple(raw["guardrails"])
        assert service.describe(view)["output_kind"] == raw["outputKind"]
