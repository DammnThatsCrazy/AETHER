"""Backend test modules must import their suite helpers by a resolvable path.

``tests/`` and every sub-suite are packages, so pytest imports a module as
``tests.<suite>.<module>`` with ``services/backend`` on ``sys.path``. A bare
``from <suite>.conftest import ...`` (e.g. ``from ai_economics.factories``)
only resolves when the suite directory itself happens to be on ``sys.path``,
so the whole module fails to collect in a normal run. Suite helpers are
imported relatively (``from .conftest import ...``) or as ``tests.<suite>``.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = TESTS_ROOT.parent
REPO_ROOT = BACKEND_ROOT.parent.parent


def _top_level_importables() -> set[str]:
    names: set[str] = set()
    for root in (BACKEND_ROOT, REPO_ROOT):
        for entry in root.iterdir():
            if entry.is_dir() and (entry / "__init__.py").exists():
                names.add(entry.name)
            elif entry.suffix == ".py":
                names.add(entry.stem)
    return names


def test_no_test_module_imports_a_sibling_suite_by_bare_name():
    suites = {
        entry.name
        for entry in TESTS_ROOT.iterdir()
        if entry.is_dir() and (entry / "__init__.py").exists()
    }
    unresolvable = suites - _top_level_importables()
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module.split(".")[0] in unresolvable:
                    offenders.append(
                        f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}: {module}"
                    )
    assert offenders == [], (
        "import suite helpers relatively (from .conftest import ...) or as "
        "tests.<suite>...:\n" + "\n".join(offenders)
    )
