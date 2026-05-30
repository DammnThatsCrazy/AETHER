#!/usr/bin/env python3
"""Lightweight TypeScript circular dependency check for CI.

The Repo Health workflow previously used `npx madge`, which requires fetching an
extra package during validation. This script provides the small subset we need:
scan TypeScript/TSX source roots, resolve local and workspace-alias imports, and
fail when an import cycle is found.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

IMPORT_RE = re.compile(
    r"(?:import\s+(?:type\s+)?(?:[\s\S]*?\s+from\s+)?|export\s+(?:type\s+)?[\s\S]*?\s+from\s+|import\s*\()"
    r"['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)

EXTENSIONS = (".ts", ".tsx")
INDEX_FILES = tuple(f"index{ext}" for ext in EXTENSIONS)

ALIAS_ROOTS = {
    "@kyber/": Path("frontend/kyber/src"),
    "@aether/shared/": Path("packages/shared/src"),
    "@aether/web/": Path("packages/web/src"),
    "@aether/react-native/": Path("packages/react-native/src"),
}


def source_files(roots: list[Path]) -> set[Path]:
    files: set[Path] = set()
    for root in roots:
        if not root.exists():
            raise SystemExit(f"Source root does not exist: {root}")
        for path in root.rglob("*"):
            if path.suffix in EXTENSIONS and "node_modules" not in path.parts:
                files.add(path.resolve())
    return files


def resolve_candidate(candidate: Path, known_files: set[Path]) -> Path | None:
    candidate = candidate.resolve()
    if candidate in known_files:
        return candidate

    for ext in EXTENSIONS:
        with_ext = candidate.with_suffix(ext).resolve()
        if with_ext in known_files:
            return with_ext

    if candidate.is_dir() or not candidate.suffix:
        for index_name in INDEX_FILES:
            index_file = (candidate / index_name).resolve()
            if index_file in known_files:
                return index_file

    return None


def resolve_import(specifier: str, importer: Path, known_files: set[Path], repo_root: Path) -> Path | None:
    if specifier.startswith("."):
        return resolve_candidate(importer.parent / specifier, known_files)

    for alias, alias_root in ALIAS_ROOTS.items():
        if specifier.startswith(alias):
            remainder = specifier[len(alias):]
            return resolve_candidate(repo_root / alias_root / remainder, known_files)

    return None


def build_graph(files: set[Path], repo_root: Path) -> dict[Path, set[Path]]:
    graph: dict[Path, set[Path]] = {path: set() for path in files}
    for path in files:
        text = path.read_text(encoding="utf-8")
        for specifier in IMPORT_RE.findall(text):
            resolved = resolve_import(specifier, path, files, repo_root)
            if resolved is not None and resolved != path:
                graph[path].add(resolved)
    return graph


def find_cycles(graph: dict[Path, set[Path]]) -> list[list[Path]]:
    visiting: set[Path] = set()
    visited: set[Path] = set()
    stack: list[Path] = []
    cycles: list[list[Path]] = []
    seen: set[tuple[Path, ...]] = set()

    def visit(node: Path) -> None:
        if node in visited:
            return
        if node in visiting:
            start = stack.index(node)
            cycle = stack[start:] + [node]
            key = tuple(cycle)
            if key not in seen:
                seen.add(key)
                cycles.append(cycle)
            return

        visiting.add(node)
        stack.append(node)
        for dep in sorted(graph.get(node, ())):
            visit(dep)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)

    return cycles


def rel(path: Path, repo_root: Path) -> str:
    return str(path.relative_to(repo_root))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", help="Source roots to scan")
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    roots = [Path(root) for root in args.roots]
    files = source_files(roots)
    graph = build_graph(files, repo_root)
    cycles = find_cycles(graph)

    if cycles:
        print(f"Found {len(cycles)} circular dependency cycle(s):", file=sys.stderr)
        for cycle in cycles[:20]:
            print("  " + " -> ".join(rel(path, repo_root) for path in cycle), file=sys.stderr)
        if len(cycles) > 20:
            print(f"  ... {len(cycles) - 20} more", file=sys.stderr)
        return 1

    edge_count = sum(len(deps) for deps in graph.values())
    print(f"No circular dependencies found ({len(files)} files, {edge_count} local edges).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
