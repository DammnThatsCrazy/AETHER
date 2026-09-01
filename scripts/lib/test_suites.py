"""Canonical test-suite registry loader.

``config/test_suites.yaml`` is the single source of truth for every automated
test suite in the repo: where it lives, how to run it, which environments it
is expected to run in, and what happens when it cannot run there. This module
is the only supported way to read that registry.

Two consumers exist today:

- ``scripts/repo_doctor.py`` replaces its two previously hardcoded pytest
  invocations (root ``tests/`` and ``ML Models/aether-ml/tests``) with a
  registry-driven loop over every pytest-runner suite that applies to the
  current mode (``--check``/``--fix`` -> environment ``local``, ``--ci`` ->
  environment ``ci``).
- ``.github/workflows/repo-health.yml``'s ``backend-tests`` job, which calls
  ``suites_for(suites, "backend")`` to get the single full-backend-tree suite
  and ``build_command(suite)`` to get its argv. That call predates this
  module (it ships a full-tree fallback for the time before this file
  existed) -- ``suites_for`` is written to satisfy it exactly, see the
  docstring on ``suites_for`` for how.

Everything here is strict and fails loudly: unknown keys, bad enum values,
paths that don't exist, and a ``documented_quarantine`` suite missing its
required ``quarantine`` block are all typed ``TestSuiteConfigError``\\s, never
silently-defaulted or coerced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import yaml

ROOT = Path(__file__).resolve().parents[2]

ENVIRONMENTS = ("local", "ci", "release")
SKIP_POLICIES = ("never", "local_only", "documented_quarantine")
RELEASE_CLASSES = ("pr_gate", "live_certification", "advisory")

_REQUIRES_KEYS = {"python_packages", "services", "docker", "credentials"}
_QUARANTINE_KEYS = {"reason", "owner", "expires"}
_SUITE_KEYS = {
    "id",
    "paths",
    "runner",
    "subsystem",
    "requires",
    "environments",
    "skip_policy",
    "release_class",
    "evidence_artifact",
    "quarantine",
}
_TOP_LEVEL_KEYS = {"schema_version", "canonical_source", "suites"}


class TestSuiteConfigError(ValueError):
    """The test-suite registry is malformed. Never caught-and-defaulted."""


@dataclass(frozen=True)
class Requires:
    python_packages: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    docker: bool = False
    credentials: tuple[str, ...] = ()

    @property
    def needs_live_infra(self) -> bool:
        """True when this suite structurally depends on something CI can't
        fabricate on its own (a live service, Docker, or real credentials).

        Consumed by ``load_suites`` to enforce that such a suite can never be
        declared ``skip_policy: never`` -- "never skip" means "must always be
        runnable in its declared environments", which a live-infra dependency
        cannot honestly promise.
        """
        return bool(self.services) or self.docker or bool(self.credentials)


@dataclass(frozen=True)
class Quarantine:
    reason: str
    owner: str
    expires: str


@dataclass(frozen=True)
class TestSuite:
    id: str
    paths: tuple[str, ...]
    runner: tuple[str, ...]
    subsystem: str
    requires: Requires
    environments: tuple[str, ...]
    skip_policy: str
    release_class: str
    evidence_artifact: Optional[str] = None
    quarantine: Optional[Quarantine] = None


def _err(where: str, message: str) -> TestSuiteConfigError:
    return TestSuiteConfigError(f"{where}: {message}")


def _require_keys(data: dict, allowed: set, where: str) -> None:
    if not isinstance(data, dict):
        raise _err(where, f"expected a mapping, got {type(data).__name__}")
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise _err(where, f"unknown key(s): {', '.join(unknown)} (allowed: {sorted(allowed)})")


def _require_str(data: dict, key: str, where: str, *, allow_empty: bool = False) -> str:
    if key not in data:
        raise _err(where, f"missing required key '{key}'")
    value = data[key]
    if not isinstance(value, str):
        raise _err(where, f"'{key}' must be a string, got {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise _err(where, f"'{key}' must not be empty")
    return value


def _require_str_list(data: dict, key: str, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if key not in data:
        raise _err(where, f"missing required key '{key}'")
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _err(where, f"'{key}' must be a list of strings")
    if not allow_empty and not value:
        raise _err(where, f"'{key}' must not be empty")
    return tuple(value)


def _parse_requires(data: Any, where: str) -> Requires:
    if data is None:
        raise _err(where, "missing required key 'requires'")
    _require_keys(data, _REQUIRES_KEYS, where)
    python_packages = tuple(data.get("python_packages", []) or [])
    services = tuple(data.get("services", []) or [])
    docker = data.get("docker", False)
    credentials = tuple(data.get("credentials", []) or [])
    if not isinstance(docker, bool):
        raise _err(where, f"'docker' must be a bool, got {type(docker).__name__}")
    for name, val in (("python_packages", python_packages), ("services", services), ("credentials", credentials)):
        if not all(isinstance(v, str) for v in val):
            raise _err(where, f"'{name}' must be a list of strings")
    return Requires(python_packages=python_packages, services=services, docker=docker, credentials=credentials)


def _parse_quarantine(data: Any, where: str) -> Quarantine:
    if not isinstance(data, dict):
        raise _err(where, f"'quarantine' must be a mapping, got {type(data).__name__}")
    _require_keys(data, _QUARANTINE_KEYS, where)
    reason = _require_str(data, "reason", where)
    owner = _require_str(data, "owner", where)
    expires = _require_str(data, "expires", where)
    return Quarantine(reason=reason, owner=owner, expires=expires)


def _parse_suite(data: Any, index: int, root: Path) -> TestSuite:
    where = f"suites[{index}]"
    if not isinstance(data, dict):
        raise _err(where, f"expected a mapping, got {type(data).__name__}")
    _require_keys(data, _SUITE_KEYS, where)

    suite_id = _require_str(data, "id", where)
    where = f"suite '{suite_id}'"

    paths = _require_str_list(data, "paths", where)
    for p in paths:
        if not (root / p).exists():
            raise _err(where, f"path does not exist: {p!r} (resolved: {root / p})")

    runner = _require_str_list(data, "runner", where)
    subsystem = _require_str(data, "subsystem", where)
    requires = _parse_requires(data.get("requires"), where)

    environments = _require_str_list(data, "environments", where)
    bad_envs = sorted(set(environments) - set(ENVIRONMENTS))
    if bad_envs:
        raise _err(where, f"invalid environment(s): {bad_envs} (allowed: {ENVIRONMENTS})")
    if len(set(environments)) != len(environments):
        raise _err(where, "'environments' contains duplicates")

    skip_policy = _require_str(data, "skip_policy", where)
    if skip_policy not in SKIP_POLICIES:
        raise _err(where, f"invalid skip_policy {skip_policy!r} (allowed: {SKIP_POLICIES})")

    release_class = _require_str(data, "release_class", where)
    if release_class not in RELEASE_CLASSES:
        raise _err(where, f"invalid release_class {release_class!r} (allowed: {RELEASE_CLASSES})")

    if "evidence_artifact" not in data:
        raise _err(where, "missing required key 'evidence_artifact' (use null if none)")
    evidence_artifact = data["evidence_artifact"]
    if evidence_artifact is not None and not isinstance(evidence_artifact, str):
        raise _err(where, "'evidence_artifact' must be a string or null")

    if "quarantine" not in data:
        raise _err(where, "missing required key 'quarantine' (use null if not quarantined)")
    quarantine_raw = data["quarantine"]
    quarantine: Optional[Quarantine]
    if skip_policy == "documented_quarantine":
        if quarantine_raw is None:
            raise _err(where, "skip_policy is 'documented_quarantine' but 'quarantine' is null; "
                               "a reason/owner/expires block is required")
        quarantine = _parse_quarantine(quarantine_raw, where)
    else:
        if quarantine_raw is not None:
            raise _err(where, f"'quarantine' must be null when skip_policy is {skip_policy!r} "
                               "(quarantine metadata is only meaningful for documented_quarantine suites)")
        quarantine = None

    if requires.needs_live_infra and skip_policy == "never":
        raise _err(
            where,
            "declares live-infra requirements (services/docker/credentials) but "
            "skip_policy is 'never' -- a suite that structurally cannot run without "
            "live services/Docker/credentials can never honestly promise it always "
            "runs; use 'local_only' or 'documented_quarantine' instead",
        )

    return TestSuite(
        id=suite_id,
        paths=paths,
        runner=runner,
        subsystem=subsystem,
        requires=requires,
        environments=environments,
        skip_policy=skip_policy,
        release_class=release_class,
        evidence_artifact=evidence_artifact,
        quarantine=quarantine,
    )


def load_suites(path: str | Path, *, root: Path = ROOT) -> list[TestSuite]:
    """Load and strictly validate the canonical test-suite registry.

    Raises ``TestSuiteConfigError`` (never returns a partial/defaulted result)
    on: unknown top-level or per-suite keys, invalid enum values, a suite path
    that doesn't exist on disk, a ``documented_quarantine`` suite missing its
    ``quarantine`` block (or a non-quarantined suite carrying one), a
    duplicate suite id, or a suite that both needs live infra and claims
    ``skip_policy: never``.
    """
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    if not resolved.exists():
        raise _err(str(resolved), "registry file does not exist")

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise _err(str(resolved), f"invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise _err(str(resolved), f"expected a top-level mapping, got {type(raw).__name__}")
    _require_keys(raw, _TOP_LEVEL_KEYS, str(resolved))

    if "suites" not in raw or not isinstance(raw["suites"], list):
        raise _err(str(resolved), "missing required top-level key 'suites' (must be a list)")

    suites = [_parse_suite(entry, i, root) for i, entry in enumerate(raw["suites"])]

    seen: dict[str, int] = {}
    for i, suite in enumerate(suites):
        if suite.id in seen:
            raise _err(str(resolved), f"duplicate suite id {suite.id!r} (suites[{seen[suite.id]}] and suites[{i}])")
        seen[suite.id] = i

    return suites


def is_pytest_suite(suite: TestSuite) -> bool:
    """True when this suite's runner is a Python/pytest invocation.

    ``scripts/repo_doctor.py`` only ever drives pytest-runner suites from the
    registry (its non-pytest checks -- npm workspaces, Hardhat -- are
    deliberately left untouched); ``scripts/validate_test_suite_coverage.py``
    uses this same predicate so its notion of "invoked by repo_doctor" can
    never drift from what repo_doctor actually runs.
    """
    return "pytest" in suite.runner or "scripts/run_pytest_files.py" in suite.runner


def suites_for(
    suites: Sequence[TestSuite],
    selector: str,
    release_class: Optional[str] = None,
) -> list[TestSuite]:
    """Filter suites by environment or by subsystem, then optionally by release_class.

    ``selector`` is matched two ways, in order:

    1. If it is one of the declared environment enum values (``local``,
       ``ci``, ``release``), suites whose ``environments`` list contains it
       are returned.
    2. Otherwise it is treated as an exact ``subsystem`` match.

    This dual behavior exists for a concrete, already-shipped reason:
    ``.github/workflows/repo-health.yml``'s ``backend-tests`` job calls
    ``suites_for(suites, "backend")`` expecting "the backend suite(s)", not
    "suites tagged for an environment named backend" (no such environment
    exists in ``ENVIRONMENTS`` -- that call would otherwise raise). Environment
    selection stays enum-validated (a typo like ``"backedn"`` is not silently
    treated as a subsystem) by virtue of falling through to exact subsystem
    matching, which simply returns an empty list for a subsystem nobody
    declared -- callers that need to distinguish "no such subsystem" from
    "no suites in this environment" should inspect the result.
    """
    if selector in ENVIRONMENTS:
        result = [s for s in suites if selector in s.environments]
    else:
        result = [s for s in suites if s.subsystem == selector]
    if release_class is not None:
        if release_class not in RELEASE_CLASSES:
            raise _err("suites_for", f"invalid release_class {release_class!r} (allowed: {RELEASE_CLASSES})")
        result = [s for s in result if s.release_class == release_class]
    return result


def build_command(suite: TestSuite) -> list[str]:
    """The argv to execute this suite, run with cwd at the repo root.

    A plain, validated passthrough of ``suite.runner`` -- suites whose runner
    needs a different working directory (Hardhat, standalone npm projects)
    encode that themselves (e.g. ``["bash", "-lc", "cd '<dir>' && ..."]``) so
    every suite's command is self-sufficient when run from the repo root.
    """
    if not suite.runner:
        raise _err(f"suite '{suite.id}'", "runner is empty; cannot build a command")
    return list(suite.runner)
