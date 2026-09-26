"""Derive the component-scoped build plan from canonical workspace metadata."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _under(paths: set[str], prefix: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for path in paths)


def _workspace_manifest(path: str) -> dict[str, Any]:
    manifest_path = ROOT / path / "package.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load workspace manifest {path!r}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        raise ValueError(f"workspace manifest {manifest_path} must declare a package name")
    return data


def _workspace_metadata() -> dict[str, dict[str, Any]]:
    try:
        root_manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load root package manifest: {exc}") from exc
    workspaces = root_manifest.get("workspaces") if isinstance(root_manifest, dict) else None
    if not isinstance(workspaces, list) or not all(isinstance(path, str) for path in workspaces):
        raise ValueError("package.json workspaces must be a list of paths")
    return {path: _workspace_manifest(path) for path in workspaces}


def _workspace_dependencies(manifests: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    by_name = {manifest["name"]: path for path, manifest in manifests.items()}
    dependencies: dict[str, set[str]] = {}
    for path, manifest in manifests.items():
        names: set[str] = set()
        for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            values = manifest.get(section, {})
            if isinstance(values, dict):
                names.update(name for name in values if name in by_name)
        dependencies[path] = {by_name[name] for name in names}
    return dependencies


def _buildable_workspaces(manifests: dict[str, dict[str, Any]]) -> set[str]:
    return {
        path
        for path, manifest in manifests.items()
        if isinstance(manifest.get("scripts"), dict) and manifest["scripts"].get("build")
    }


def _topological_build_order(
    selected: set[str], dependencies: dict[str, set[str]]
) -> list[str]:
    """Return dependency-first, stable workspace order for selected builds."""
    closure = set(selected)
    frontier = list(selected)
    while frontier:
        workspace = frontier.pop()
        for dependency in dependencies.get(workspace, set()):
            if dependency not in closure:
                closure.add(dependency)
                frontier.append(dependency)

    ordered: list[str] = []
    remaining = set(closure)
    while remaining:
        ready = sorted(
            workspace
            for workspace in remaining
            if not (dependencies.get(workspace, set()) & remaining)
        )
        if not ready:
            raise ValueError(
                "workspace dependency cycle prevents a dependency-first build: "
                + ", ".join(sorted(remaining))
            )
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


def _selected_workspaces(
    changed: set[str],
    *,
    global_change: bool,
    global_scopes: set[str],
    applications: set[str],
    packages: set[str],
) -> list[str]:
    manifests = _workspace_metadata()
    buildable = _buildable_workspaces(manifests)
    dependencies = _workspace_dependencies(manifests)

    if global_change and not global_scopes:
        # Root package metadata and delivery/verification inputs are global
        # graph inputs. Rebuild every workspace that declares a build script;
        # do not silently fall back to a backend-only image and skip Node
        # consumers of a changed lockfile.
        selected = set(buildable)
    else:
        selected = {path for path in buildable if _under(changed, path)}
        application_paths = {
            "aether": "frontend/aether",
            "kyber": "frontend/kyber",
            "docs": "frontend/docs",
            "demo": "frontend/demo",
            "olympus-marketing": "frontend/olympus-marketing",
            "aether-marketing": "frontend/aether-marketing",
            "site": "frontend/site",
        }
        selected.update(
            path
            for application, path in application_paths.items()
            if application in applications and path in buildable
        )
        package_paths = {
            "shared": "packages/shared",
            "web": "packages/web",
            "server": "packages/server",
            "react-native": "packages/react-native",
            "mobile-core": "packages/mobile-core",
        }
        selected.update(
            path
            for package, path in package_paths.items()
            if package in packages and path in buildable
        )
        if "node_dependency_graph" in global_scopes:
            selected.update(buildable)
        elif "shared_runtime_contract" in global_scopes:
            selected.update(
                path for path in buildable if path.startswith(("packages/", "frontend/"))
            )

    return _topological_build_order(selected, dependencies)


def select_builds(
    changed_files: Sequence[str],
    *,
    global_change: bool = False,
    global_scopes: Sequence[str] = (),
) -> dict[str, Any]:
    """Return the stable BuildSelection contract for one changed-path set.

    Workspace paths are derived from the root npm workspace manifest, and the
    returned ``workspaces`` list is dependency-first. The contract describes
    what the build authority must consume; it does not build, publish, or
    deploy anything.
    """
    changed = set(changed_files)
    scopes = set(global_scopes)
    applications: set[str] = set()
    packages: set[str] = set()
    sdk = {"ios": False, "android": False, "js": False}
    backend_image = _under(changed, "services/backend")

    for prefix, application in (
        ("frontend/aether", "aether"),
        ("frontend/kyber", "kyber"),
        ("frontend/aether-marketing", "aether-marketing"),
        ("frontend/olympus-marketing", "olympus-marketing"),
        ("frontend/site", "site"),
        ("frontend/docs", "docs"),
        ("frontend/demo", "demo"),
    ):
        if _under(changed, prefix):
            applications.add(application)
    for prefix, package in (
        ("packages/shared", "shared"),
        ("packages/web", "web"),
        ("packages/server", "server"),
        ("packages/react-native", "react-native"),
        ("packages/mobile-core", "mobile-core"),
        ("packages/mobile-ui", "mobile-ui"),
        ("packages/brand", "brand"),
        ("packages/config", "config"),
    ):
        if _under(changed, prefix):
            packages.add(package)
    if _under(changed, "frontend/aether") or _under(changed, "frontend/kyber"):
        packages.add("shared")
    # frontend/site serves packages/brand's marks as its Vite publicDir, a
    # filesystem dependency that no workspace manifest declares.
    if _under(changed, "packages/brand"):
        applications.add("site")
    if _under(changed, "packages/web") or _under(changed, "packages/react-native"):
        sdk["js"] = True
    sdk["ios"] = _under(changed, "packages/ios")
    sdk["android"] = _under(changed, "packages/android")

    if global_change and not scopes:
        backend_image = True

    if "python_dependency_graph" in scopes:
        backend_image = True
    if "verification_control_plane" in scopes:
        backend_image = False

    node_required = bool(
        applications
        or packages
        or sdk["js"]
        or "node_dependency_graph" in scopes
        or "shared_runtime_contract" in scopes
    )
    python_profiles = ["ci-control"]
    if backend_image or any(
        _under(changed, prefix)
        for prefix in (
            "services/backend",
            "services/agents",
            "services/compliance",
            "docs/archive/legacy-architecture/backend",
        )
    ):
        python_profiles.append("python-backend")
    if _under(changed, "services/ml") or "python_dependency_graph" in scopes:
        python_profiles.append("python-ml")
    if _under(changed, "services/agents"):
        python_profiles.append("python-agent")
    if _under(changed, "services/compliance"):
        python_profiles.append("python-security")
    if _under(changed, "tests"):
        python_profiles.append("python-root")
    artifact_groups = []
    if node_required:
        artifact_groups.append("node-workspaces")
    if backend_image:
        artifact_groups.append("backend-source")
    if not artifact_groups:
        artifact_groups.append("control-plane")

    return {
        "packages": sorted(packages),
        "applications": sorted(applications),
        "workspaces": _selected_workspaces(
            changed,
            global_change=global_change,
            global_scopes=scopes,
            applications=applications,
            packages=packages,
        ),
        "backend_image": backend_image,
        "sdk": sdk,
        "node_required": node_required,
        "python_profiles": sorted(set(python_profiles)),
        "artifact_groups": artifact_groups,
        "global_scopes": sorted(scopes),
    }


__all__ = ["select_builds"]
