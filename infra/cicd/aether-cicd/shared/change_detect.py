"""
Aether CI/CD -- Monorepo Change Detection
Determines which services/packages changed relative to a base ref,
enabling selective CI/CD runs instead of always-build-everything.

Usage:
    changed = detect_changed_services()
    if "ingestion" in changed:
        run_ci_for("ingestion")
"""

from __future__ import annotations

from config.pipeline_config import CHANGE_DETECTION_CONFIG
from shared.runner import log, run_cmd


def _git_changed_files(base_ref: str = "origin/develop") -> list[str]:
    """Get list of files changed relative to base_ref using git diff."""
    result = run_cmd(f"git diff --name-only {base_ref}...HEAD", timeout=30)
    if not result.success:
        # If git diff fails (e.g., shallow clone), return empty -> run everything
        log(f"git diff failed ({result.stderr[:100]}), running full pipeline", stage="DETECT")
        return []
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def detect_changed_services(
    base_ref: str | None = None,
    changed_files: list[str] | None = None,
) -> set[str]:
    """
    Determine which services were affected by recent changes.

    Returns a set of service names (e.g. {"ingestion", "identity"}).
    Returns ALL services if:
      - Change detection is disabled
      - Any always_run_path was modified
      - git diff fails
      - No files changed (safety: run everything)

    Args:
        base_ref:       Git ref to diff against. Defaults to config value.
        changed_files:  Override file list (for testing).
    """
    config = CHANGE_DETECTION_CONFIG

    if not config.enabled:
        log("Change detection disabled, running full pipeline", stage="DETECT")
        return set(config.service_path_map.values())

    if base_ref is None:
        base_ref = config.base_ref

    files = changed_files if changed_files is not None else _git_changed_files(base_ref)

    if not files:
        log("No changed files detected, running full pipeline", stage="DETECT")
        return set(config.service_path_map.values())

    # Check if any always-run path was touched
    for f in files:
        for always_path in config.always_run_paths:
            if f.startswith(always_path):
                log(
                    f"Global path changed ({always_path}), running full pipeline",
                    stage="DETECT",
                )
                return set(config.service_path_map.values())

    # Map changed files to affected services
    affected: set[str] = set()
    for f in files:
        for path_prefix, svc_name in config.service_path_map.items():
            if f.startswith(path_prefix):
                affected.add(svc_name)

    if affected:
        log(f"Affected services: {', '.join(sorted(affected))}", stage="DETECT")
    else:
        log("No service paths matched, running full pipeline", stage="DETECT")
        return set(config.service_path_map.values())

    return affected
