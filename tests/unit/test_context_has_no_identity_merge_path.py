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
BACKEND = REPO_ROOT / "services" / "backend"

CONTEXT_MODULES = (
    BACKEND / "services/ingestion/context_enricher.py",
    BACKEND / "services/ingestion/geo_provider.py",
    BACKEND / "shared/privacy/ip_hmac.py",
    *sorted((BACKEND / "shared/context_capsule").glob("*.py")),
)
IDENTITY_MODULE_PREFIXES = ("services.identity", "services.resolution", "shared.identity")
MERGE_NAMES = ("merge_identit", "link_identit", "resolve_identit", "alias_identit")


def _module_name(path: Path) -> str:
    """Dotted module name of a backend file (``services.ingestion.context_enricher``)."""
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


def test_context_modules_do_not_import_identity_resolution() -> None:
    offenders = []
    for path in CONTEXT_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _imported_modules(tree, _module_name(path), path.name == "__init__.py"):
            if module.startswith(IDENTITY_MODULE_PREFIXES):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {module}")
    assert offenders == [], offenders


def test_context_modules_do_not_call_identity_merge_helpers() -> None:
    offenders = []
    for path in CONTEXT_MODULES:
        text = path.read_text(encoding="utf-8").lower()
        offenders.extend(f"{path.relative_to(REPO_ROOT)} mentions {name}" for name in MERGE_NAMES if name in text)
    assert offenders == [], offenders


def test_relative_imports_are_resolved_before_they_are_checked() -> None:
    tree = ast.parse("from ..identity import repository\nfrom . import geo_provider\nimport os\n")
    resolved = _imported_modules(tree, "services.ingestion.context_enricher")
    assert "services.identity" in resolved
    assert "services.identity.repository" in resolved
    assert "services.ingestion.geo_provider" in resolved
    assert any(m.startswith(IDENTITY_MODULE_PREFIXES) for m in resolved)
    # An __init__ module is its own package.
    assert "shared.context_capsule.models" in _imported_modules(
        ast.parse("from .models import X\n"), "shared.context_capsule", is_package=True
    )
