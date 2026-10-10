"""Context enrichment must not be able to merge identities.

Location and behavioral context never merge identities alone. That guarantee
is structural: the context enrichment and capsule code have no import path into
identity resolution, so no flag is needed (a setting named
``AETHER_LOCATION_IDENTITY_MERGE_BLOCKED`` used to claim this and nothing read
it). This pins the structure, so adding such a path fails here rather than being
silently permitted by a flag that gates nothing.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "services" / "api"

CONTEXT_MODULES = (
    BACKEND / "ingestion/ingestion/context_enricher.py",
    BACKEND / "ingestion/ingestion/geo_provider.py",
    BACKEND / "shared/privacy/ip_hmac.py",
    *sorted((BACKEND / "shared/context_capsule").glob("*.py")),
)
IDENTITY_MODULE_PREFIXES = ("identity.identity", "services.resolution", "shared.identity")
MERGE_NAMES = ("merge_identit", "link_identit", "resolve_identit", "alias_identit")


def _module_name(path: Path) -> str:
    """Dotted module name of a backend file (``ingestion.ingestion.context_enricher``)."""
    parts = list(path.relative_to(BACKEND).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported_modules(tree: ast.AST, module: str, is_package: bool = False) -> list[str]:
    """Absolute names of every module a file imports, relative imports resolved."""
    package = module if is_package else module.rpartition(".")[0]
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".") if package else []
                base = base[: len(base) - (node.level - 1)]
                prefix = ".".join([*base, *([node.module] if node.module else [])])
            else:
                prefix = node.module or ""
            if prefix:
                modules.append(prefix)
                modules.extend(f"{prefix}.{alias.name}" for alias in node.names)
    return modules


def test_context_modules_exist() -> None:
    missing = [str(p.relative_to(REPO_ROOT)) for p in CONTEXT_MODULES if not p.is_file()]
    assert missing == [], f"context modules moved; update this guard: {missing}"


def _backend_modules(backend: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend)
        if "tests" in rel.parts or "__pycache__" in rel.parts or path.name.startswith("test_"):
            continue
        parts = list(rel.with_suffix("").parts)
        modules[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    return modules


def _closure(roots: list[str], modules: dict[str, Path]) -> dict[str, str]:
    """Every backend module reachable from ``roots`` through imports, with the importer that led to it."""
    seen: dict[str, str] = {}
    stack = [(root, "") for root in roots]
    while stack:
        module, via = stack.pop()
        if module in seen or module not in modules:
            continue
        seen[module] = via
        path = modules[module]
        for name in _imported_modules(ast.parse(path.read_text(encoding="utf-8")), module, path.name == "__init__.py"):
            parts = name.split(".")
            for end in range(len(parts), 0, -1):
                candidate = ".".join(parts[:end])
                if candidate in modules:
                    stack.append((candidate, module))
                    break
    return seen


def _identity_paths(roots: list[str], modules: dict[str, Path]) -> list[str]:
    seen = _closure(roots, modules)
    found = []
    for module in seen:
        if module.startswith(IDENTITY_MODULE_PREFIXES):
            chain, node = [module], module
            while seen.get(node):
                node = seen[node]
                chain.append(node)
            found.append(" <- ".join(chain))
    return found


def test_context_modules_cannot_reach_identity_resolution_through_any_import_chain() -> None:
    """A neutral facade that itself imports identity resolution would be a path too."""
    modules = _backend_modules(BACKEND)
    roots = [_module_name(p) for p in CONTEXT_MODULES]
    assert _identity_paths(roots, modules) == []


def test_the_closure_follows_indirect_and_relative_imports(tmp_path) -> None:
    (tmp_path / "identity/identity").mkdir(parents=True)
    (tmp_path / "ingestion/ingestion").mkdir(parents=True)
    for rel, text in {
        "identity/identity/__init__.py": "",
        "identity/identity/resolver.py": "def merge(): ...\n",
        "ingestion/ingestion/__init__.py": "",
        "ingestion/ingestion/facade.py": "from identity.identity import resolver\n",
        "ingestion/ingestion/enricher.py": "from . import facade\n",
        "ingestion/ingestion/clean.py": "import os\n",
    }.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    modules = _backend_modules(tmp_path)
    paths = _identity_paths(["ingestion.ingestion.enricher"], modules)
    assert paths and "ingestion.ingestion.facade" in paths[0] and "ingestion.ingestion.enricher" in paths[0]
    assert _identity_paths(["ingestion.ingestion.clean"], modules) == []


def test_context_modules_do_not_call_identity_merge_helpers() -> None:
    offenders = []
    for path in CONTEXT_MODULES:
        text = path.read_text(encoding="utf-8").lower()
        offenders.extend(f"{path.relative_to(REPO_ROOT)} mentions {name}" for name in MERGE_NAMES if name in text)
    assert offenders == [], offenders


def test_relative_imports_are_resolved_before_they_are_checked() -> None:
    tree = ast.parse("from ...identity.identity import repository\nfrom . import geo_provider\nimport os\n")
    resolved = _imported_modules(tree, "ingestion.ingestion.context_enricher")
    assert "identity.identity" in resolved
    assert "identity.identity.repository" in resolved
    assert "ingestion.ingestion.geo_provider" in resolved
    assert any(m.startswith(IDENTITY_MODULE_PREFIXES) for m in resolved)
    # An __init__ module is its own package.
    assert "shared.context_capsule.models" in _imported_modules(
        ast.parse("from .models import X\n"), "shared.context_capsule", is_package=True
    )
