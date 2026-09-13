"""Versioned task-profile runtime tests — VersionPolicy, VersionResolver, store.

Covers ADR-008 D3 version resolution for task profiles: EXPLICIT / LATEST /
PINNED policy selection, deterministic fail-closed behavior on unknown profiles
and unavailable versions, and the versioned store's get/latest/list over a small
synthetic set of :class:`TaskProfileView` objects. Plain asserts only.
"""

from __future__ import annotations

from services.model_runtime.routing.profiles import (
    ProfileRegistry,
    TaskProfileView,
)
from services.model_runtime.task_profiles.versioning import (
    ProfileVersionError,
    VersionPolicy,
    VersionResolver,
    VersionedProfileStore,
)
from shared.model_governance.generated_task_profiles import TASK_PROFILES


def _raises(exc_type, fn, *args, **kwargs) -> bool:
    """Return True when ``fn(*args, **kwargs)`` raises ``exc_type``."""
    try:
        fn(*args, **kwargs)
    except exc_type:
        return True
    return False


# ---------------------------------------------------------------------------
# VersionPolicy
# ---------------------------------------------------------------------------


def test_version_policy_values_match_enum():
    assert VersionPolicy.EXPLICIT.value == "explicit"
    assert VersionPolicy.LATEST.value == "latest"
    assert VersionPolicy.PINNED.value == "pinned"
    # str-backed enum so policy values are plain, serializable strings.
    assert isinstance(VersionPolicy.EXPLICIT, str)
    assert VersionPolicy.EXPLICIT == "explicit"
    assert set(VersionPolicy) == {
        VersionPolicy.EXPLICIT,
        VersionPolicy.LATEST,
        VersionPolicy.PINNED,
    }
    assert VersionPolicy.EXPLICIT is not VersionPolicy.LATEST
    assert VersionPolicy.EXPLICIT != VersionPolicy.PINNED


# ---------------------------------------------------------------------------
# VersionResolver
# ---------------------------------------------------------------------------


def test_resolver_default_derives_versions_from_registry():
    resolver = VersionResolver()
    assert resolver.available_versions("noesis_query_planning") == (1,)
    # Every generated profile registers at version 1.
    for raw in TASK_PROFILES:
        assert resolver.available_versions(raw["profileId"]) == (1,)


def test_resolver_explicit_happy_path():
    resolver = VersionResolver(version_map={"task_a": (1, 2, 3)})
    assert resolver.resolve("task_a", policy=VersionPolicy.EXPLICIT, requested_version=2) == 2
    assert resolver.resolve("task_a", policy=VersionPolicy.EXPLICIT, requested_version=1) == 1


def test_resolver_explicit_missing_version_errors():
    resolver = VersionResolver(version_map={"task_a": (1, 2, 3)})
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy=VersionPolicy.EXPLICIT,
    )
    # LATEST default does not require a requested version, but EXPLICIT does.
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy=VersionPolicy.EXPLICIT,
        requested_version=None,
    )


def test_resolver_explicit_not_available_version_errors():
    resolver = VersionResolver(version_map={"task_a": (1, 2, 3)})
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy=VersionPolicy.EXPLICIT,
        requested_version=5,
    )
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy=VersionPolicy.EXPLICIT,
        requested_version=0,
    )


def test_resolver_latest_picks_max_available():
    resolver = VersionResolver(version_map={"task_a": (1, 3, 2)})
    assert resolver.resolve("task_a", policy=VersionPolicy.LATEST) == 3
    # available_versions is deterministic (sorted, de-duplicated).
    assert resolver.available_versions("task_a") == (1, 2, 3)


def test_resolver_latest_is_default_policy():
    resolver = VersionResolver(version_map={"task_a": (4, 2, 8)})
    assert resolver.resolve("task_a") == 8  # LATEST when policy is omitted
    assert resolver.resolve("task_a", policy=VersionPolicy.LATEST) == 8


def test_resolver_pinned_accepts_positive_int():
    resolver = VersionResolver(version_map={"task_a": (1,)})
    # A pin may precede the registry: the requested version need not be among
    # the currently available versions, only a positive int.
    assert resolver.resolve("task_a", policy=VersionPolicy.PINNED, requested_version=7) == 7
    assert resolver.resolve("task_a", policy=VersionPolicy.PINNED, requested_version=1) == 1


def test_resolver_pinned_requires_requested_version():
    resolver = VersionResolver(version_map={"task_a": (1,)})
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy=VersionPolicy.PINNED,
    )
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy=VersionPolicy.PINNED,
        requested_version=None,
    )


def test_resolver_pinned_rejects_non_positive():
    resolver = VersionResolver(version_map={"task_a": (1,)})
    for bad in (0, -1, -5):
        assert _raises(
            ProfileVersionError,
            resolver.resolve,
            "task_a",
            policy=VersionPolicy.PINNED,
            requested_version=bad,
        ), f"PINNED should reject requested_version={bad!r}"
    # bool is an int subclass but not a valid version.
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy=VersionPolicy.PINNED,
        requested_version=True,
    )


def test_resolver_unknown_profile_errors_all_policies():
    resolver = VersionResolver(version_map={"task_a": (1,)})
    for policy in VersionPolicy:
        assert _raises(
            ProfileVersionError,
            resolver.resolve,
            "missing_profile",
            policy=policy,
            requested_version=1,
        ), f"unknown profile should error under {policy!r}"
    assert _raises(ProfileVersionError, resolver.available_versions, "missing_profile")


def test_resolver_default_registry_unknown_profile_errors():
    resolver = VersionResolver()
    assert _raises(ProfileVersionError, resolver.resolve, "does_not_exist")
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "does_not_exist",
        policy=VersionPolicy.EXPLICIT,
        requested_version=1,
    )


def test_resolver_invalid_policy_errors():
    resolver = VersionResolver(version_map={"task_a": (1,)})
    # A plain string is not a VersionPolicy member -- fail-closed.
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy="explicit",
        requested_version=1,
    )
    assert _raises(
        ProfileVersionError,
        resolver.resolve,
        "task_a",
        policy=None,
        requested_version=1,
    )


# ---------------------------------------------------------------------------
# VersionedProfileStore
# ---------------------------------------------------------------------------


def _synthetic_set():
    """A small synthetic set: entity_classification v1, noesis v1 + v2."""
    registry = ProfileRegistry()
    entity_v1 = registry.get("entity_classification")
    noesis_v1 = registry.get("noesis_query_planning")
    raw_v2 = dict(TASK_PROFILES[0])
    raw_v2["version"] = 2
    noesis_v2 = TaskProfileView(raw_v2)
    return registry, (entity_v1, noesis_v1, noesis_v2)


def test_versioned_store_get_latest_list_over_synthetic_set():
    registry, (entity_v1, noesis_v1, noesis_v2) = _synthetic_set()
    store = VersionedProfileStore(profiles=[noesis_v1, noesis_v2, entity_v1])

    assert store.get("noesis_query_planning", 1) is noesis_v1
    assert store.get("noesis_query_planning", 2) is noesis_v2
    assert store.get("entity_classification", 1) is entity_v1
    assert store.latest("noesis_query_planning") is noesis_v2
    assert store.latest("entity_classification") is entity_v1

    listed = store.list()
    assert listed == (entity_v1, noesis_v1, noesis_v2)
    # Deterministic (profile_id, version) ordering.
    assert tuple(p.profile_id for p in listed) == (
        "entity_classification",
        "noesis_query_planning",
        "noesis_query_planning",
    )
    assert tuple(p.version for p in listed) == (1, 1, 2)


def test_versioned_store_get_unknown_version_errors():
    registry, _ = _synthetic_set()
    store = VersionedProfileStore(profiles=[registry.get("entity_classification")])
    assert _raises(ProfileVersionError, store.get, "entity_classification", 2)
    assert _raises(ProfileVersionError, store.get, "entity_classification", 0)


def test_versioned_store_unknown_profile_errors():
    registry, _ = _synthetic_set()
    store = VersionedProfileStore(profiles=[registry.get("entity_classification")])
    assert _raises(ProfileVersionError, store.latest, "missing_profile")
    assert _raises(ProfileVersionError, store.get, "missing_profile", 1)


def test_versioned_store_defaults_to_registry():
    store = VersionedProfileStore()
    listed = store.list()
    assert len(listed) == len(TASK_PROFILES)
    assert all(isinstance(profile, TaskProfileView) for profile in listed)
    for raw in TASK_PROFILES:
        assert store.get(raw["profileId"], raw["version"]).profile_id == raw["profileId"]
        assert store.latest(raw["profileId"]).version == raw["version"]
