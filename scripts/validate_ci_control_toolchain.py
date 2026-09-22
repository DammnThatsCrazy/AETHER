#!/usr/bin/env python3
"""Validate the intentionally small dependency boundary for CI planning.

Classification and execution-plan generation must be able to run before the
application runtime is installed.  This gate checks both the installed
control-plane libraries and the import surface of the scripts that run in the
control environment.  It is deliberately AST-based: importing application
modules just to prove that they are not imported would defeat the boundary.
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTROL_PLANE_SCRIPTS = (
    "scripts/check_router.py",
    "scripts/impact_graph.py",
    "scripts/verification_disposition.py",
    "scripts/verification_execution_plan.py",
    "scripts/lib/impact_graph.py",
    "scripts/lib/verification_router.py",
    "scripts/lib/build_selection.py",
    "scripts/lib/test_suites.py",
    "scripts/lib/processes.py",
    "scripts/lib/ci_performance.py",
    "scripts/aggregate_verification_evidence.py",
    "scripts/suite_worker.py",
    "scripts/universal_fast.py",
    "scripts/validate_ci_performance_policy.py",
    "scripts/validate_ci_execution_contracts.py",
    "scripts/validate_execution_plan.py",
    "scripts/verify_candidate_evidence.py",
)

# These are application/runtime packages, not CI planning dependencies.  Keep
# this list explicit so adding a new heavy import is an intentional review
# decision rather than an accidental classifier slowdown.
FORBIDDEN_ROOTS = {
    "aiohttp",
    "aiokafka",
    "anthropic",
    "asyncpg",
    "boto3",
    "celery",
    "cryptography",
    "fastapi",
    "gremlinpython",
    "h3",
    "numpy",
    "pandas",
    "pydantic",
    "redis",
    "sklearn",
    "sqlalchemy",
    "xgboost",
}


def _root_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name.split(".", 1)[0]
    if isinstance(node, ast.ImportFrom) and node.module:
        return node.module.split(".", 1)[0]
    return None


def _forbidden_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        root = _root_name(node)
        if root in FORBIDDEN_ROOTS:
            found.add(root)
    return sorted(found)


def main() -> int:
    errors: list[str] = []
    for module in ("yaml", "jsonschema"):
        try:
            importlib.import_module(module)
        except ImportError as exc:
            errors.append(f"missing ci-control dependency {module!r}: {exc}")

    for relative in CONTROL_PLANE_SCRIPTS:
        path = ROOT / relative
        if not path.is_file():
            # The execution-plan module is introduced with this contract; a
            # missing control-plane surface is a hard failure, never a skip.
            errors.append(f"missing registered CI control-plane script: {relative}")
            continue
        forbidden = _forbidden_imports(path)
        if forbidden:
            errors.append(f"{relative} imports application runtime package(s): {', '.join(forbidden)}")

    try:
        from scripts.lib.test_suites import load_suites

        load_suites(ROOT / "config" / "test_suites.yaml")
    except Exception as exc:  # noqa: BLE001 - this is a fail-closed boundary gate
        errors.append(f"dependency profile/suite registry validation failed: {exc}")

    result = {
        "schema_version": 1,
        "status": "PASS" if not errors else "FAILED",
        "control_plane_scripts": list(CONTROL_PLANE_SCRIPTS),
        "forbidden_runtime_roots": sorted(FORBIDDEN_ROOTS),
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
