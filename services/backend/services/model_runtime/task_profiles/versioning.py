"""Versioned task-profile runtime (ADR-008 D3).

Task profiles carry a ``version`` (``"version": 1`` in the generated registry,
``shared/model_governance/generated_task_profiles.py``). This module resolves the
version an invocation should use -- explicitly, latest, or pinned -- and serves a
deterministic, read-only store of :class:`TaskProfileView` objects ordered by
``(profile_id, version)``.

Resolution rules (fail-closed):

* ``EXPLICIT`` -- the caller names the version and it MUST be present in the
  profile's available versions, else :class:`ProfileVersionError`.
* ``LATEST`` -- the maximum available version for the profile.
* ``PINNED`` -- the caller pins a positive int version. The pin may legally
  precede the registry (a version planned for a future release), so the pinned
  value is NOT checked against the available set; only that it is a positive
  int and that the profile_id is known.

Any unknown ``profile_id`` raises :class:`ProfileVersionError`; the resolver never
silently falls back to another version. Versions are pure integers -- no
credentials, no strings, no tenant data are ever handled here.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from services.model_runtime.routing.profiles import (
    ProfileRegistry,
    TaskProfileView,
)

__all__ = [
    "ProfileVersionError",
    "VersionPolicy",
    "VersionResolver",
    "VersionedProfileStore",
]


class ProfileVersionError(Exception):
    """Raised when a task-profile version cannot be resolved or located.

    Used for unknown ``profile_id`` values, EXPLICIT requests that omit a
    version or name an unavailable one, PINNED requests that omit or invalidate
    the pin, and store lookups that miss. Everything is fail-closed: an invalid
    request never resolves to a different version.
    """


class VersionPolicy(str, enum.Enum):
    """How an invocation's task-profile version is chosen (ADR-008 D3)."""

    EXPLICIT = "explicit"
    LATEST = "latest"
    PINNED = "pinned"


class VersionResolver:
    """Resolve which version of a task profile an invocation should use.

    ``version_map`` maps a ``profile_id`` to that profile's available versions.
    When omitted, the map is derived from the generated task-profile registry
    (each registered profile has exactly its registry version). Stored version
    tuples are normalized to sorted, de-duplicated ``tuple[int, ...]`` so
    resolution is deterministic regardless of the caller's input ordering.
    """

    def __init__(
        self,
        *,
        version_map: Mapping[str, tuple[int, ...]] | None = None,
    ) -> None:
        if version_map is None:
            registry = ProfileRegistry()
            version_map = {profile.profile_id: (profile.version,) for profile in registry.all()}
        normalized = {
            str(profile_id): tuple(sorted(set(versions)))
            for profile_id, versions in version_map.items()
        }
        self._version_map: Mapping[str, tuple[int, ...]] = MappingProxyType(normalized)

    def available_versions(self, profile_id: str) -> tuple[int, ...]:
        """Return the sorted available versions for ``profile_id``.

        Raises :class:`ProfileVersionError` for an unknown profile or a profile
        that has no registered versions (fail-closed, never an empty result).
        """
        try:
            versions = self._version_map[profile_id]
        except KeyError:
            raise ProfileVersionError(
                f"unknown task profile {profile_id!r}: no versions are registered"
            ) from None
        if not versions:
            raise ProfileVersionError(f"task profile {profile_id!r} has no available versions")
        return versions

    def resolve(
        self,
        profile_id: str,
        *,
        policy: VersionPolicy = VersionPolicy.LATEST,
        requested_version: int | None = None,
    ) -> int:
        """Resolve the version to use for ``profile_id`` under ``policy``.

        * ``EXPLICIT`` -- ``requested_version`` must be provided and present in
          the profile's available versions.
        * ``LATEST`` (default) -- the maximum available version.
        * ``PINNED`` -- ``requested_version`` must be a positive int; it is
          returned as-is without an availability check (a pin may precede the
          registry), but the ``profile_id`` must still be known.

        Any unknown ``profile_id`` raises :class:`ProfileVersionError`.
        """
        if not isinstance(policy, VersionPolicy):
            raise ProfileVersionError(
                f"invalid version policy {policy!r}; expected a VersionPolicy member"
            )
        if policy is VersionPolicy.EXPLICIT:
            if requested_version is None:
                raise ProfileVersionError(
                    f"EXPLICIT resolution for {profile_id!r} requires requested_version"
                )
            available = self.available_versions(profile_id)
            if requested_version not in available:
                raise ProfileVersionError(
                    f"version {requested_version!r} is not available for task profile "
                    f"{profile_id!r} (available: {available})"
                )
            return requested_version
        if policy is VersionPolicy.PINNED:
            if requested_version is None:
                raise ProfileVersionError(
                    f"PINNED resolution for {profile_id!r} requires requested_version"
                )
            if (
                not isinstance(requested_version, int)
                or isinstance(requested_version, bool)
                or requested_version <= 0
            ):
                raise ProfileVersionError(
                    f"pinned version for {profile_id!r} must be a positive int, "
                    f"got {requested_version!r}"
                )
            if profile_id not in self._version_map:
                raise ProfileVersionError(
                    f"unknown task profile {profile_id!r}: no versions are registered"
                )
            return requested_version
        # The only remaining member is LATEST.
        available = self.available_versions(profile_id)
        return max(available)


class VersionedProfileStore:
    """Read-only store of :class:`TaskProfileView` objects, versioned.

    Ordering is deterministic by ``(profile_id, version)`` ascending, so
    ``latest()`` is the final entry of a profile's ascending run. The backing
    structures are immutable.
    """

    def __init__(self, profiles: Sequence[TaskProfileView] | None = None) -> None:
        if profiles is None:
            registry = ProfileRegistry()
            profiles = registry.all()
        ordered = sorted(profiles, key=lambda p: (p.profile_id, p.version))
        by_key: dict[tuple[str, int], TaskProfileView] = {}
        by_id: dict[str, list[TaskProfileView]] = {}
        for profile in ordered:
            key = (profile.profile_id, profile.version)
            if key in by_key:
                raise ProfileVersionError(
                    f"duplicate task profile {profile.profile_id!r} at version {profile.version}"
                )
            by_key[key] = profile
            by_id.setdefault(profile.profile_id, []).append(profile)
        self._by_key: Mapping[tuple[str, int], TaskProfileView] = MappingProxyType(by_key)
        self._by_id: Mapping[str, tuple[TaskProfileView, ...]] = MappingProxyType(
            {profile_id: tuple(views) for profile_id, views in by_id.items()}
        )
        self._ordered: tuple[TaskProfileView, ...] = tuple(ordered)

    def get(self, profile_id: str, version: int) -> TaskProfileView:
        """Return the exact ``(profile_id, version)`` view.

        Raises :class:`ProfileVersionError` when the combination is not stored.
        """
        try:
            return self._by_key[(profile_id, version)]
        except KeyError:
            raise ProfileVersionError(
                f"no task profile {profile_id!r} at version {version}"
            ) from None

    def latest(self, profile_id: str) -> TaskProfileView:
        """Return the highest stored version of ``profile_id``.

        Raises :class:`ProfileVersionError` for an unknown profile.
        """
        try:
            versions = self._by_id[profile_id]
        except KeyError:
            raise ProfileVersionError(
                f"unknown task profile {profile_id!r}: no stored versions"
            ) from None
        return versions[-1]  # ascending by version, so the last is the max

    def list(self) -> tuple[TaskProfileView, ...]:
        """All stored views in deterministic ``(profile_id, version)`` order."""
        return self._ordered
