"""Typed, fail-closed primitives for the change-aware verification router.

The YAML registry is intentionally kept as the human-editable source of
truth.  This module gives its consumers one validated representation and a
small impact-classification primitive.  It does not execute checks or mutate
the worktree.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

ROOT = Path(__file__).resolve().parents[2]
LANE_ORDER = ("fast", "pr", "integration", "regression", "release")
RISK_LEVELS = ("low", "medium", "high", "critical")

_TOP_LEVEL_KEYS = {"schema_version", "default_lane", "lanes", "checks", "domains", "global_paths"}
_CHECK_KEYS = {"owner", "risk", "command", "runtime_budget_seconds"}
_DOMAIN_KEYS = {"owner", "paths", "checks", "path_checks", "minimum_lane"}


class VerificationRouterConfigError(ValueError):
    """The verification registry is malformed and cannot be safely routed."""


@dataclass(frozen=True)
class CheckDefinition:
    id: str
    owner: str
    risk: str
    command: tuple[str, ...]
    runtime_budget_seconds: int


@dataclass(frozen=True)
class DomainDefinition:
    id: str
    owner: str
    paths: tuple[str, ...]
    checks: tuple[str, ...]
    path_checks: Mapping[str, tuple[str, ...]]
    minimum_lane: str


@dataclass(frozen=True)
class VerificationRouterConfig:
    schema_version: int
    default_lane: str
    lanes: Mapping[str, tuple[str, ...]]
    checks: Mapping[str, CheckDefinition]
    domains: Mapping[str, DomainDefinition]
    global_paths: tuple[str, ...]


@dataclass(frozen=True)
class VerificationImpact:
    """Deterministic impact classification for one changed-path set."""

    changed_files: tuple[str, ...]
    affected_domains: tuple[str, ...]
    global_change: bool
    minimum_lane: str
    selected_lane: str
    followup_required: bool
    selected_checks: tuple[str, ...]


def _error(where: str, message: str) -> VerificationRouterConfigError:
    return VerificationRouterConfigError(f"{where}: {message}")


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _error(where, f"expected a mapping, got {type(value).__name__}")
    return value


def _require_keys(value: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _error(where, f"unknown key(s): {', '.join(unknown)}")


def _require_nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(where, "must be a non-empty string")
    return value


def _require_string_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise _error(where, "must be a non-empty list of non-empty strings")
    if len(set(value)) != len(value):
        raise _error(where, "must not contain duplicates")
    return tuple(value)


def _known_check_ids(known_check_ids: set[str] | None) -> set[str]:
    if known_check_ids is not None:
        return set(known_check_ids)
    # Domain checks may refer to suite ids whose command is supplied by the
    # canonical test-suite registry rather than this router's check mapping.
    from scripts.lib.test_suites import load_suites

    return {suite.id for suite in load_suites(ROOT / "config" / "test_suites.yaml")}


def validate_router_registry(
    data: Any,
    *,
    known_check_ids: set[str] | None = None,
) -> VerificationRouterConfig:
    """Parse and strictly validate a raw verification-router mapping.

    ``known_check_ids`` is the set of externally resolved checks, normally
    suite ids from ``config/test_suites.yaml``.  Keeping this explicit makes
    the parser usable in focused tests without weakening production checks.
    """
    top = _require_mapping(data, "verification router")
    _require_keys(top, _TOP_LEVEL_KEYS, "verification router")

    if top.get("schema_version") != 1:
        raise _error("verification router.schema_version", "must be 1")
    default_lane = _require_nonempty_string(top.get("default_lane"), "verification router.default_lane")
    if default_lane not in LANE_ORDER:
        raise _error("verification router.default_lane", f"invalid lane {default_lane!r}")

    raw_lanes = _require_mapping(top.get("lanes"), "verification router.lanes")
    if set(raw_lanes) != set(LANE_ORDER):
        raise _error(
            "verification router.lanes",
            f"must define exactly {list(LANE_ORDER)!r}",
        )
    lanes: dict[str, tuple[str, ...]] = {}
    for lane in LANE_ORDER:
        lanes[lane] = _require_string_list(raw_lanes[lane], f"verification router.lanes.{lane}")

    raw_checks = _require_mapping(top.get("checks"), "verification router.checks")
    checks: dict[str, CheckDefinition] = {}
    for check_id, raw_check in raw_checks.items():
        check_id = _require_nonempty_string(check_id, "verification router.checks key")
        item = _require_mapping(raw_check, f"verification router.checks.{check_id}")
        _require_keys(item, _CHECK_KEYS, f"verification router.checks.{check_id}")
        owner = _require_nonempty_string(item.get("owner"), f"verification router.checks.{check_id}.owner")
        risk = _require_nonempty_string(item.get("risk"), f"verification router.checks.{check_id}.risk")
        if risk not in RISK_LEVELS:
            raise _error(f"verification router.checks.{check_id}.risk", f"invalid risk {risk!r}")
        command = _require_string_list(item.get("command"), f"verification router.checks.{check_id}.command")
        budget = item.get("runtime_budget_seconds")
        if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
            raise _error(
                f"verification router.checks.{check_id}.runtime_budget_seconds",
                "must be a positive integer",
            )
        if check_id in checks:
            raise _error("verification router.checks", f"duplicate check id {check_id!r}")
        checks[check_id] = CheckDefinition(check_id, owner, risk, command, budget)

    resolved_check_ids = set(checks) | _known_check_ids(known_check_ids)
    for lane, lane_checks in lanes.items():
        unknown = sorted(set(lane_checks) - resolved_check_ids)
        if unknown:
            raise _error(f"verification router.lanes.{lane}", f"unknown check(s): {', '.join(unknown)}")

    raw_domains = _require_mapping(top.get("domains"), "verification router.domains")
    domains: dict[str, DomainDefinition] = {}
    for domain_id, raw_domain in raw_domains.items():
        domain_id = _require_nonempty_string(domain_id, "verification router.domains key")
        item = _require_mapping(raw_domain, f"verification router.domains.{domain_id}")
        _require_keys(item, _DOMAIN_KEYS, f"verification router.domains.{domain_id}")
        owner = _require_nonempty_string(item.get("owner"), f"verification router.domains.{domain_id}.owner")
        paths = _require_string_list(item.get("paths"), f"verification router.domains.{domain_id}.paths")
        domain_checks = _require_string_list(item.get("checks"), f"verification router.domains.{domain_id}.checks")
        unknown = sorted(set(domain_checks) - resolved_check_ids)
        if unknown:
            raise _error(
                f"verification router.domains.{domain_id}.checks",
                f"unknown check(s): {', '.join(unknown)}",
            )
        raw_path_checks = item.get("path_checks", {})
        if not isinstance(raw_path_checks, dict):
            raise _error(
                f"verification router.domains.{domain_id}.path_checks",
                "must be a mapping of path patterns to check lists",
            )
        path_checks: dict[str, tuple[str, ...]] = {}
        for pattern, raw_checks in raw_path_checks.items():
            pattern = _require_nonempty_string(
                pattern, f"verification router.domains.{domain_id}.path_checks key"
            )
            selected = _require_string_list(
                raw_checks,
                f"verification router.domains.{domain_id}.path_checks.{pattern}",
            )
            unknown = sorted(set(selected) - resolved_check_ids)
            if unknown:
                raise _error(
                    f"verification router.domains.{domain_id}.path_checks.{pattern}",
                    f"unknown check(s): {', '.join(unknown)}",
                )
            path_checks[pattern] = selected
        minimum_lane = _require_nonempty_string(
            item.get("minimum_lane"), f"verification router.domains.{domain_id}.minimum_lane"
        )
        if minimum_lane not in LANE_ORDER:
            raise _error(
                f"verification router.domains.{domain_id}.minimum_lane",
                f"invalid lane {minimum_lane!r}",
            )
        if domain_id in domains:
            raise _error("verification router.domains", f"duplicate domain id {domain_id!r}")
        domains[domain_id] = DomainDefinition(
            domain_id, owner, paths, domain_checks, path_checks, minimum_lane
        )

    global_paths = _require_string_list(top.get("global_paths"), "verification router.global_paths")
    return VerificationRouterConfig(1, default_lane, lanes, checks, domains, global_paths)


def load_router_registry(path: str | Path, *, known_check_ids: set[str] | None = None) -> VerificationRouterConfig:
    """Load and validate a YAML verification-router registry."""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    if not resolved.exists():
        raise _error(str(resolved), "registry file does not exist")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise _error(str(resolved), f"invalid YAML: {exc}") from exc
    return validate_router_registry(raw, known_check_ids=known_check_ids)


def matches(path: str, pattern: str) -> bool:
    """Match repository-relative paths using the router's ``/**`` semantics."""
    import fnmatch

    return fnmatch.fnmatchcase(path, pattern) or (
        pattern.endswith("/**") and (path == pattern[:-3] or path.startswith(pattern[:-2]))
    )


def classify_impact(
    paths: Sequence[str],
    config: VerificationRouterConfig,
    requested_lane: str | None = None,
) -> VerificationImpact:
    """Classify changed paths and select checks without executing anything."""
    changed = tuple(sorted(set(paths)))
    affected: set[str] = set()
    global_change = any(
        any(matches(path, pattern) for pattern in config.global_paths) for path in changed
    )
    minimum_lane = "fast"
    # A path that is not owned by any registered domain is a new executable
    # or delivery surface until somebody registers it.  Treating that case as
    # a fast, low-risk change is precisely the silent-omission failure this
    # router is meant to prevent.  Keep the synthetic domain in the evidence
    # so the operator can see why the conservative lane was selected.
    matched_paths: set[str] = set()
    for domain_id, definition in config.domains.items():
        domain_matches = {
            path
            for path in changed
            if any(matches(path, pattern) for pattern in definition.paths)
        }
        if global_change or domain_matches:
            affected.add(domain_id)
            matched_paths.update(domain_matches)
            if LANE_ORDER.index(definition.minimum_lane) > LANE_ORDER.index(minimum_lane):
                minimum_lane = definition.minimum_lane

    unknown_paths = set(changed) - matched_paths
    if unknown_paths and not global_change:
        affected.add("unknown_component")
        minimum_lane = "integration"

    # Preserve the router's established behavior: with no requested lane, the
    # minimum lane for the affected paths is selected. ``default_lane`` is
    # retained as registry metadata for callers that need an explicit default.
    selected_lane = requested_lane or minimum_lane
    if selected_lane not in LANE_ORDER:
        raise ValueError(f"requested lane {selected_lane!r} is invalid")
    if selected_lane != "fast" and LANE_ORDER.index(selected_lane) < LANE_ORDER.index(minimum_lane):
        raise ValueError(f"requested lane {selected_lane!r} is below required minimum {minimum_lane!r}")

    check_ids: set[str] = set(config.lanes[selected_lane][:2])
    if LANE_ORDER.index(selected_lane) >= LANE_ORDER.index(minimum_lane):
        for domain_id in affected:
            # ``unknown_component`` is a deliberate synthetic owner.  Its
            # conservative integration lane supplies the checks; it has no
            # registry-defined domain checks of its own.
            if domain_id in config.domains:
                definition = config.domains[domain_id]
                domain_paths = {
                    path
                    for path in changed
                    if any(matches(path, pattern) for pattern in definition.paths)
                }
                path_checks: set[str] = set()
                for pattern, checks in definition.path_checks.items():
                    if any(matches(path, pattern) for path in domain_paths):
                        path_checks.update(checks)
                check_ids.update(path_checks or definition.checks)
    check_ids.update(config.lanes[selected_lane])
    return VerificationImpact(
        changed_files=changed,
        affected_domains=tuple(sorted(affected)),
        global_change=global_change,
        minimum_lane=minimum_lane,
        selected_lane=selected_lane,
        followup_required=LANE_ORDER.index(selected_lane) < LANE_ORDER.index(minimum_lane),
        selected_checks=tuple(sorted(check_ids)),
    )
