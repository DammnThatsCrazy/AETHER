#!/usr/bin/env python3
"""Aether Platform — toolchain validation gate.

Asserts that the interpreter running the gate can actually import every
dependency the release-critical test suites need.

Why this exists
---------------
``scripts/repo_doctor.py`` historically treated a missing optional dependency as
a reason to *skip* a suite, and ``skip()`` recorded ``passed=True``. On a machine
without ``scikit-learn`` the entire ML suite therefore reported green without
executing a single test. A gate that cannot run its tests must fail, not pass.

This script is the fail-closed replacement for that behaviour. It never skips and
never warns — a missing release-critical dependency is a non-zero exit.

Usage::

    python scripts/validate_toolchain.py            # all release-critical groups
    python scripts/validate_toolchain.py --group ml # one group
    python scripts/validate_toolchain.py --json     # machine-readable report
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ToolchainGroup:
    """A set of importable modules required by one family of gated suites.

    ``extra`` is the ``pyproject.toml`` optional-dependency group that provides
    the modules, and is quoted verbatim in the remediation message so the fix is
    copy-pasteable.
    """

    name: str
    extra: str
    modules: tuple[str, ...]
    rationale: str
    suites: tuple[str, ...] = field(default_factory=tuple)


# Module names are *import* names, not distribution names — `scikit-learn`
# installs as `sklearn`, `PyJWT` as `jwt`. Every entry below is required by a
# suite the release gate executes; adding a module here without a suite that
# needs it is not allowed.
GROUPS: tuple[ToolchainGroup, ...] = (
    ToolchainGroup(
        name="core",
        extra="dev",
        modules=("pytest", "yaml", "ruff"),
        rationale="the gate itself cannot run without a test runner, YAML parsing, and the linter",
        suites=("all",),
    ),
    ToolchainGroup(
        name="backend",
        extra="backend",
        modules=(
            "fastapi",
            "pydantic",
            "httpx",
            "starlette",
            "sqlalchemy",
            "alembic",
            "redis",
            "asyncpg",
            "jwt",
            "cryptography",
            "boto3",
            "graphql",
            "webauthn",
        ),
        rationale=(
            "the backend test tree imports the FastAPI app at module scope; without these "
            "the suite reports collection errors rather than results"
        ),
        suites=("Backend Architecture/aether-backend/tests",),
    ),
    ToolchainGroup(
        name="ml",
        extra="ml",
        modules=("sklearn", "joblib", "numpy", "pandas", "pyarrow", "xgboost", "scipy"),
        rationale=(
            "training, calibration, and artifact-loading tests are meaningless without the "
            "estimator and serialization stack; this is the group whose absence produced a "
            "false-green ML gate"
        ),
        suites=("ML Models/aether-ml/tests",),
    ),
    ToolchainGroup(
        name="security",
        extra="security",
        modules=("numpy",),
        rationale="extraction-defense tests operate on numeric embeddings",
        suites=("tests/security",),
    ),
)


class ToolchainError(RuntimeError):
    """Raised when a release-critical dependency cannot be imported."""


def _declared_distributions(extra: str) -> list[str]:
    """Return the distribution names declared by one pyproject optional-dependency extra.

    Import names and distribution names differ (``scikit-learn`` imports as
    ``sklearn``), so :data:`GROUPS` has to name modules explicitly. That table can
    silently fall behind ``pyproject.toml`` — exactly what happened when the Kyber
    device-trust work added ``webauthn`` to the backend extra: the module table did
    not know about it, so the gate passed while ``tests/security`` failed to collect.
    This reads the source of truth so the drift is caught mechanically.
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover — Python < 3.11
        return []

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    specs = data.get("project", {}).get("optional-dependencies", {}).get(extra, [])
    names: list[str] = []
    for spec in specs:
        # Strip environment markers, extras, and version constraints:
        # 'uvicorn[standard]>=0.30; python_version>"3.10"' -> 'uvicorn'
        name = spec.split(";")[0].split("[")[0]
        for operator in (">=", "<=", "==", "!=", "~=", ">", "<"):
            name = name.split(operator)[0]
        name = name.strip()
        # 'aether[security,agent,...]' style self-references have no distribution
        # of their own to verify here; the referenced extras are checked directly.
        if name and name != "aether":
            names.append(name)
    return names


def _uninstalled_distributions(extra: str) -> list[str]:
    """Return declared distributions of ``extra`` that are not installed."""
    from importlib.metadata import PackageNotFoundError, version

    missing: list[str] = []
    for dist in _declared_distributions(extra):
        try:
            version(dist)
        except PackageNotFoundError:
            missing.append(dist)
    return missing


def _missing_modules(group: ToolchainGroup) -> list[str]:
    """Return the group's modules that cannot be located.

    Uses ``find_spec`` rather than ``import`` so that a module which imports
    cleanly but crashes on execution is still reported by the deeper check in
    :func:`_broken_modules`.
    """
    missing: list[str] = []
    for module in group.modules:
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except (ImportError, ValueError):
            missing.append(module)
    return missing


def _broken_modules(group: ToolchainGroup, skip: Sequence[str]) -> list[tuple[str, str]]:
    """Return modules that resolve but raise on import.

    A Debian-packaged ``cryptography`` built against a different interpreter
    resolves via ``find_spec`` and then panics at import time. That failure mode
    is invisible to ``pip check``, so it has to be caught by actually importing.
    """
    broken: list[tuple[str, str]] = []
    for module in group.modules:
        if module in skip:
            continue
        try:
            importlib.import_module(module)
        except BaseException as exc:  # noqa: BLE001 — a pyo3 panic is not an Exception
            broken.append((module, f"{type(exc).__name__}: {exc}"))
    return broken


def check_group(group: ToolchainGroup) -> dict[str, object]:
    missing = _missing_modules(group)
    broken = _broken_modules(group, skip=missing)
    uninstalled = _uninstalled_distributions(group.extra)
    return {
        "group": group.name,
        "extra": group.extra,
        "ok": not missing and not broken and not uninstalled,
        "missing": missing,
        "broken": [{"module": m, "error": e} for m, e in broken],
        "uninstalled_distributions": uninstalled,
        "suites": list(group.suites),
        "remediation": f'{sys.executable} -m pip install -e ".[{group.extra}]"',
    }


def validate(groups: Sequence[ToolchainGroup]) -> list[dict[str, object]]:
    return [check_group(group) for group in groups]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--group",
        action="append",
        choices=[g.name for g in GROUPS],
        help="validate only the named group (repeatable); default is all groups",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selected = [g for g in GROUPS if not args.group or g.name in args.group]
    report = validate(selected)

    if args.json:
        print(json.dumps({"interpreter": sys.executable, "groups": report}, indent=2))
    else:
        print(f"Toolchain validation — interpreter: {sys.executable}\n")
        for entry in report:
            status = "OK" if entry["ok"] else "FAIL"
            print(f"  [{status}] {entry['group']} (extra: {entry['extra']})")
            for module in entry["missing"]:
                print(f"        missing: {module}")
            for item in entry["broken"]:
                print(f"        broken:  {item['module']} — {item['error']}")
            for dist in entry["uninstalled_distributions"]:
                print(f"        declared in pyproject but not installed: {dist}")

    failed = [e for e in report if not e["ok"]]
    if failed:
        print("\nRelease-critical dependencies are unavailable. These suites CANNOT run:")
        for entry in failed:
            for suite in entry["suites"]:
                print(f"  - {suite}")
        print("\nRemediate with:")
        for entry in failed:
            print(f"  {entry['remediation']}")
        print(
            "\nThis is a failure, not a skip. A suite that cannot execute must never be "
            "recorded as passing."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
