#!/usr/bin/env python3
"""Validate TypeScript public package/export boundaries for AETHER SDK packages.

This gate is intentionally static and fast. It verifies that package metadata
points at existing declaration/runtime entrypoints, package export maps are not
stale, generated declarations do not expose private deep imports, and declaration
imports are reachable from published files.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIRS = [ROOT / "packages" / "shared", ROOT / "packages" / "web", ROOT / "packages" / "react-native"]
PRIVATE_IMPORT_PATTERNS = [
    re.compile(r"import\(['\"]\.\/src/"),
    re.compile(r"from ['\"]\.\/src/"),
]



def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for nested in value.values():
            out.extend(_as_list(nested))
        return out
    return []


def _resolve_package_path(pkg_dir: Path, rel: str) -> Path:
    return pkg_dir / rel.lstrip("./")


def _check_path(errors: list[str], pkg_dir: Path, pkg_name: str, field: str, rel: str) -> None:
    if "*" in rel:
        matches = list(pkg_dir.glob(rel.lstrip("./")))
        if not matches:
            errors.append(f"{pkg_name} {field} wildcard matches no files: {rel}")
        return
    target = _resolve_package_path(pkg_dir, rel)
    if not target.exists():
        errors.append(f"{pkg_name} {field} points at missing file: {rel}")


def _declaration_import_target_exists(decl: Path, specifier: str) -> bool:
    if not specifier.startswith("."):
        return True
    base = (decl.parent / specifier).resolve()
    candidates = [base, base.with_suffix(".d.ts"), base / "index.d.ts"]
    return any(path.exists() for path in candidates)


def _validate_declaration(pkg_name: str, decl: Path, errors: list[str]) -> None:
    if not decl.exists():
        return
    body = decl.read_text(encoding="utf-8")
    for pattern in PRIVATE_IMPORT_PATTERNS:
        if pattern.search(body):
            errors.append(f"{pkg_name} declaration exposes private/deep relative import in {decl.relative_to(ROOT)}")
    for specifier in re.findall(r"(?:from|import\()\s*['\"]([^'\"]+)['\"]", body):
        if not _declaration_import_target_exists(decl, specifier):
            errors.append(
                f"{pkg_name} declaration {decl.relative_to(ROOT)} imports missing declaration target {specifier!r}"
            )


def _has_public_barrel(pkg_dir: Path) -> bool:
    return any((pkg_dir / rel).exists() for rel in ["src/index.ts", "src/index.tsx", "index.ts"])


def _is_dist_path(rel: str) -> bool:
    return rel.startswith("./dist/") or rel.startswith("dist/")


def validate_package(pkg_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = pkg_dir / "package.json"
    if not manifest_path.exists():
        return [f"missing package.json for {pkg_dir.relative_to(ROOT)}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pkg_name = manifest.get("name", str(pkg_dir.relative_to(ROOT)))

    if not _has_public_barrel(pkg_dir):
        errors.append(f"{pkg_name} has no public source barrel (src/index.ts[x] or index.ts)")

    dist_dir = pkg_dir / "dist"
    dist_built = dist_dir.exists()

    for field in ["types", "main", "module"]:
        rel = manifest.get(field)
        if isinstance(rel, str):
            # Skip dist-path checks when dist hasn't been built yet — the package
            # must be built before these artifacts can be verified.
            if _is_dist_path(rel) and not dist_built:
                continue
            _check_path(errors, pkg_dir, pkg_name, field, rel)

    exports = manifest.get("exports", {})
    if exports:
        for rel in _as_list(exports):
            if rel.startswith("./"):
                if _is_dist_path(rel) and not dist_built:
                    continue
                _check_path(errors, pkg_dir, pkg_name, "exports", rel)
    elif manifest.get("private") is not True:
        errors.append(f"{pkg_name} has no package exports map")

    types_rel = manifest.get("types")
    if isinstance(types_rel, str):
        root_decl = _resolve_package_path(pkg_dir, types_rel)
        if dist_built or not _is_dist_path(types_rel):
            _validate_declaration(pkg_name, root_decl, errors)

    if dist_built:
        for decl in sorted(dist_dir.rglob("*.d.ts")):
            _validate_declaration(pkg_name, decl, errors)

    return errors


def main() -> int:
    errors: list[str] = []
    for pkg_dir in PACKAGE_DIRS:
        errors.extend(validate_package(pkg_dir))
    if errors:
        print("TypeScript public export/package boundary validation failed:")
        for err in errors:
            print(f"  - {err}")
        print("\nRemediation: run npm run build, export public declaration types from package barrels, and update package.json exports.")
        return 1
    print("TypeScript public export/package boundary validation passed for @aether/shared, @aether/web, and @aether/react-native.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
