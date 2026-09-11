"""Derive the component-scoped build plan from the canonical changed paths."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _under(paths: set[str], prefix: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for path in paths)


def select_builds(
    changed_files: Sequence[str],
    *,
    global_change: bool = False,
) -> dict[str, Any]:
    """Return the stable BuildSelection contract for one changed-path set.

    This is deliberately a small path-to-artifact vocabulary owned by the
    verification spine.  It describes what the build authority must consume;
    it does not build, publish, or deploy anything.  Global changes conservatively
    require the backend image unless a more specific application/package was
    already selected.
    """
    changed = set(changed_files)
    applications: set[str] = set()
    packages: set[str] = set()
    sdk = {"ios": False, "android": False, "js": False}
    backend_image = _under(changed, "Backend Architecture/aether-backend")

    for prefix, application in (
        ("frontend/aether", "aether"),
        ("frontend/kyber", "kyber"),
        ("frontend/aether-marketing", "aether-marketing"),
        ("frontend/olympus-marketing", "olympus-marketing"),
        ("frontend/docs", "docs"),
    ):
        if _under(changed, prefix):
            applications.add(application)
    if _under(changed, "frontend/aether") or _under(changed, "frontend/kyber"):
        packages.add("shared")
    for prefix, package in (
        ("packages/shared", "shared"),
        ("packages/web", "web"),
        ("packages/react-native", "react-native"),
        ("ML Models/aether-ml", "ml"),
    ):
        if _under(changed, prefix):
            packages.add(package)
    if _under(changed, "packages/web") or _under(changed, "packages/react-native"):
        sdk["js"] = True
    sdk["ios"] = _under(changed, "packages/ios")
    sdk["android"] = _under(changed, "packages/android")

    if global_change and not (applications or packages or backend_image):
        backend_image = True
    return {
        "packages": sorted(packages),
        "applications": sorted(applications),
        "backend_image": backend_image,
        "sdk": sdk,
    }


__all__ = ["select_builds"]
