"""Task-profile registry query API tests (ADR-008 D3).

Covers the read-only query surface the Kyber control plane and the model
runtime consume over the generated task-profile registry: role/output-kind/
guardrail filtering, control-plane summary, audit-safe profile projection, the
lazy module-level default query, and immutable registry snapshots.
"""
from __future__ import annotations

import importlib.util
import os

from services.model_runtime.task_profiles.registry_api import (
    ProfileQuery,
    ProfileRegistrySnapshot,
    get_default_query,
    profile_summary,
)
from shared.model_governance.generated_task_profiles import TASK_PROFILE_REGISTRY_VERSION

#: Absolute path to ``services/``/``shared/`` so a fresh module can be loaded
#: directly for the import-safety check without polluting shared state.
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

#: Keys every ``ProfileQuery.summary()`` result is expected to expose.
_SUMMARY_KEYS = frozenset({"version", "role_counts", "output_kind_counts", "profile_ids"})

#: Audit/display-safe field allowlist that ``profile_summary`` must never exceed.
_PROFILE_SUMMARY_ALLOWLIST = frozenset(
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


def test_default_query_by_role_includes_noesis_query_planning():
    profiles = get_default_query().by_role("planning")
    ids = tuple(p.profile_id for p in profiles)
    assert "noesis_query_planning" in ids
    assert ids == ("noesis_query_planning",)


def test_default_query_by_output_kind_includes_grounded_answer_synthesis():
    profiles = get_default_query().by_output_kind("grounded_answer")
    ids = tuple(p.profile_id for p in profiles)
    assert "grounded_answer_synthesis" in ids
    assert len(profiles) == 1
    assert profiles[0].profile_id == "grounded_answer_synthesis"


def test_default_query_with_guardrail_includes_both_evidence_profiles():
    profiles = get_default_query().with_guardrail("evidence_required")
    ids = set(p.profile_id for p in profiles)
    assert "grounded_answer_synthesis" in ids
    assert "evidence_summarization" in ids
    assert len(profiles) == 2


def test_default_query_summary_has_expected_keys_and_counts_agree():
    query = get_default_query()
    summary = query.summary()
    all_profiles = query.all()
    assert set(summary) == _SUMMARY_KEYS
    assert summary["version"] == TASK_PROFILE_REGISTRY_VERSION
    assert sum(summary["role_counts"].values()) == len(all_profiles)
    assert sum(summary["output_kind_counts"].values()) == len(all_profiles)
    assert summary["role_counts"]["planning"] == 1
    assert tuple(summary["profile_ids"]) == tuple(p.profile_id for p in all_profiles)


def test_profile_summary_is_deterministic_and_allowlisted():
    query = get_default_query()
    for profile in query.all():
        first = profile_summary(profile)
        second = profile_summary(profile)
        assert first == second
        assert set(first) == _PROFILE_SUMMARY_ALLOWLIST
        assert set(first) <= _PROFILE_SUMMARY_ALLOWLIST
        assert first["profile_id"] == profile.profile_id
        assert first["default_routing_mode"] == profile.default_routing_mode.value


def test_profile_registry_snapshot_round_trips():
    query = get_default_query()
    snapshot = ProfileRegistrySnapshot(
        version=TASK_PROFILE_REGISTRY_VERSION,
        profiles=tuple(profile_summary(p) for p in query.all()),
    )
    data = snapshot.model_dump()
    rebuilt = ProfileRegistrySnapshot(**data)
    assert rebuilt == snapshot
    assert snapshot.version == TASK_PROFILE_REGISTRY_VERSION
    assert len(snapshot.profiles) == len(query.all())
    assert tuple(p["profile_id"] for p in snapshot.profiles) == tuple(
        p.profile_id for p in query.all()
    )
    for entry in snapshot.profiles:
        assert set(entry) == _PROFILE_SUMMARY_ALLOWLIST


def test_get_default_query_is_cached_profile_query():
    first = get_default_query()
    second = get_default_query()
    assert isinstance(first, ProfileQuery)
    assert first is second


def test_module_import_has_zero_side_effects():
    # Loading the module in isolation must not build the default query; the
    # query is constructed lazily on first request.
    path = os.path.join(
        BACKEND_ROOT,
        "services",
        "model_runtime",
        "task_profiles",
        "registry_api.py",
    )
    spec = importlib.util.spec_from_file_location("_registry_api_import_safety", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._default_query is None
    query = mod.get_default_query()
    assert mod._default_query is not None
    assert query.all()
