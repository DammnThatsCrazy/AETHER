#!/usr/bin/env python3
"""Fail when backend production code is not reachable from the application.

``config/backend_reachability.yaml`` names the entry modules, the packages that
are loaded by name at runtime, and the modules still unreachable against a ledger
row (``allow_unreachable``: a ``package`` and the ``modules`` in it, or a single
``path``). Every production module under
``services/api`` must be reachable from them through static imports
(absolute, relative, function-level), a dotted module name used as a string
constant, or a reference from outside the backend (a script, a workflow, a
Dockerfile, a registry file), unless it is listed under ``allow_unreachable``
with the debt-ledger row that owns the decision. An allowlist entry is itself an
error once its module is gone, has become reachable, or its ledger row has
disappeared, so the list can only shrink.

Tests are not entry points: a module that only a test imports is code nothing
runs. ``--report`` prints the unreachable modules and their size.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/backend_reachability.yaml"
LEDGER = ROOT / "config/debt_retirement_ledger.yaml"

_SKIP_DIRS = {"__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
# Files whose text can launch or register a backend module: a Dockerfile command,
# a compose or workflow step, a registry. Prose and generated indexes cannot.
_REFERENCE_SUFFIXES = (".py", ".yaml", ".yml", ".json", ".toml", ".sh", ".cfg", ".ini", ".tf", ".txt")
_REFERENCE_NAMES = ("Dockerfile", "Makefile")
# Descriptive registries (config/, the debt ledger, readiness evidence, reports) list
# paths without running them, and the allowlist itself names modules, so none of
# them can keep code reachable.
_IGNORED_REFERENCE_DIRS = ("docs/", "node_modules/", "packages/", "apps/", "docs/reference/reports/", "config/", ".artifacts/", ".claude/", ".codex/")


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return "tests" in parts or "test" in parts or name.startswith(("test_", "conftest")) or name.endswith("_test.py")


def backend_modules(root: Path, backend: str) -> dict[str, Path]:
    """Dotted module name -> file for every production module."""
    base = root / backend
    found: dict[str, Path] = {}
    for current, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(current) / name
            rel = path.relative_to(base).as_posix()
            if _is_test(rel):
                continue
            parts = rel[:-3].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                found["/".join(parts).replace("/", ".")] = path
    return found


def _resolve(name: str, known: dict[str, Path]) -> str | None:
    """The module a dotted name refers to: the longest existing prefix."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None


def _edges(path: Path, module: str, known: dict[str, Path]) -> set[str]:
    """Modules ``path`` imports, or names as a dotted string constant."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return set()
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: set[str] = set()

    def add(name: str) -> None:
        target = _resolve(name, known)
        if target:
            found.add(target)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".") if package else []
                base = base[: len(base) - (node.level - 1)]
                prefix = ".".join([*base, *([node.module] if node.module else [])])
            else:
                prefix = node.module or ""
            if prefix:
                add(prefix)
                for alias in node.names:
                    sub = f"{prefix}.{alias.name}"
                    if sub in known:
                        found.add(sub)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.split(":")[0]
            if value in known and _DOTTED.fullmatch(value):
                found.add(value)
    # importing a module imports its parent packages
    parts = module.split(".")
    for end in range(1, len(parts)):
        parent = ".".join(parts[:end])
        if parent in known:
            found.add(parent)
    return found


def _tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in out.split("\n") if line]


def outside_references(root: Path, backend: str, known: dict[str, Path]) -> dict[str, set[str]]:
    """Backend modules named by something other than backend production code.

    A script that imports a backend module, a workflow or Dockerfile that runs one,
    or a registry that lists one counts as a reference. Tests, prose and the
    frontend do not.
    """
    refs: dict[str, set[str]] = {}
    path_style = re.compile(re.escape(backend) + r"/([\w/]+?)(?:\.py)?(?![\w/])")
    for rel in _tracked_files(root):
        if rel.startswith(backend + "/") and rel.endswith(".py"):
            continue  # inside the backend: handled by the import graph
        if rel.startswith(_IGNORED_REFERENCE_DIRS) or _is_test(rel) or rel.endswith(".md"):
            continue
        if not (rel.endswith(_REFERENCE_SUFFIXES) or rel.rsplit("/", 1)[-1] in _REFERENCE_NAMES):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if rel.endswith(".py"):
            # A Python script reaches a module only by importing it or naming it as a
            # dotted module string. A path or name in a checklist (``Path(...).exists()``)
            # is descriptive evidence, not a caller.
            for target in _edges(root / rel, "scripts._outside", known):
                refs.setdefault(target, set()).add(rel)
            continue
        for match in _DOTTED.finditer(text):
            target = _resolve(match.group(0), known)
            if target:
                refs.setdefault(target, set()).add(rel)
        for match in path_style.finditer(text):
            target = _resolve(match.group(1).replace("/", "."), known)
            if target:
                refs.setdefault(target, set()).add(rel)
    return refs


def _under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def analyse(config: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Reachable and unreachable modules for the configured backend (no policy applied)."""
    backend = config.get("root", "services/api")
    known = backend_modules(root, backend)
    roots: set[str] = {e for e in config.get("entries") or [] if e in known}
    for item in config.get("dynamic_packages") or []:
        path = item.get("path") if isinstance(item, dict) else None
        if isinstance(path, str):
            roots.update(m for m in known if _under(m, path))
    for pattern in config.get("generated_globs") or []:
        regex = re.compile(pattern)
        roots.update(m for m, p in known.items() if regex.search(p.relative_to(root / backend).as_posix()))
    references = outside_references(root, backend, known)
    roots.update(references)
    graph: dict[str, set[str]] = {}
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        module = stack.pop()
        if module in seen or module not in known:
            continue
        seen.add(module)
        if module not in graph:
            graph[module] = _edges(known[module], module, known)
        stack.extend(graph[module])
    unreachable = sorted(m for m in known if m not in seen)
    return {"known": known, "live": seen, "unreachable": unreachable, "roots": roots, "references": references}


def _lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ledger_ids(ledger: Path) -> set[str]:
    try:
        raw = yaml.safe_load(ledger.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return set()
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return {
        e["id"] for e in (entries if isinstance(entries, list) else [])
        if isinstance(e, dict) and isinstance(e.get("id"), str)
    }


def validate(config_path: Path = CONFIG, ledger: Path = LEDGER, root: Path = ROOT) -> list[str]:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot load backend reachability config: {exc}"]
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return ["schema_version must be 1"]
    errors: list[str] = []
    if raw.get("authority") != "backend-reachability":
        errors.append("authority must be backend-reachability")
    backend = raw.get("root")
    if not _text(backend) or not (root / backend).is_dir():
        return errors + [f"root {backend!r} must be a directory inside the repository"]
    entries = raw.get("entries")
    if not isinstance(entries, list) or not entries or not all(_text(e) for e in entries):
        return errors + ["entries must be a non-empty list of module names"]

    known = backend_modules(root, backend)
    for entry in entries:
        if entry not in known:
            errors.append(f"entry {entry!r} is not a backend module")
    for index, item in enumerate(raw.get("dynamic_packages") or []):
        label = f"dynamic_packages[{index}]"
        if not (isinstance(item, dict) and _text(item.get("path")) and _text(item.get("reason"))):
            errors.append(f"{label}: needs a non-empty path and reason")
        elif not any(_under(m, item["path"]) for m in known):
            errors.append(f"{label}: {item['path']} matches no backend module (delete the entry)")
    for index, pattern in enumerate(raw.get("generated_globs") or []):
        if not _text(pattern):
            errors.append(f"generated_globs[{index}]: must be a non-empty regular expression")

    ledger_ids = _ledger_ids(ledger)
    allow = raw.get("allow_unreachable") or []
    if not isinstance(allow, list):
        return errors + ["allow_unreachable must be a list"]
    allowed: set[str] = set()
    subtrees: set[str] = set()  # names from a ``path`` entry, which covers the whole package
    for index, item in enumerate(allow):
        label = f"allow_unreachable[{index}]"
        if not (isinstance(item, dict) and _text(item.get("ledger")) and _text(item.get("reason"))):
            errors.append(f"{label}: needs a ledger row and a reason")
            continue
        if item["ledger"] not in ledger_ids:
            errors.append(f"{label}: ledger row {item['ledger']!r} does not exist")
        names = _entry_modules(item)
        if names is None:
            errors.append(f"{label}: needs either a path, or a package and a non-empty list of modules")
            continue
        for name in names:
            if name in allowed:
                errors.append(f"{label}: {name} is listed twice")
            allowed.add(name)
            if _text(item.get("path")):
                subtrees.add(name)

    result = analyse({**raw, "dynamic_packages": [d for d in raw.get("dynamic_packages") or [] if isinstance(d, dict)]}, root)
    unreachable = set(result["unreachable"])
    def covers(name: str, module: str) -> bool:
        # A ``package`` + ``modules`` entry names exact modules: a listed package does not
        # cover modules added under it later. Only a ``path`` entry covers a subtree.
        return _under(module, name) if name in subtrees else module == name

    for name in sorted(allowed):
        if not any(covers(name, m) for m in result["known"]):
            errors.append(f"allow_unreachable {name}: no such module (delete the entry)")
        elif not any(covers(name, m) for m in unreachable):
            errors.append(f"allow_unreachable {name}: reachable now; remove it from the allowlist")
    for module in result["unreachable"]:
        if any(covers(name, module) for name in allowed):
            continue
        rel = result["known"][module].relative_to(root).as_posix()
        errors.append(
            f"{rel} is not reachable from the application; mount or import it, delete it, "
            "or list it under allow_unreachable with a ledger row"
        )
    return errors


def _entry_modules(item: dict[str, Any]) -> list[str] | None:
    """Dotted names an allowlist entry covers: ``path``, or ``package`` + ``modules``."""
    if _text(item.get("path")):
        return [item["path"]]
    package, modules = item.get("package"), item.get("modules")
    if _text(package) and isinstance(modules, list) and modules and all(_text(m) for m in modules):
        return [package if m == "." else f"{package}.{m}" for m in modules]
    return None


DOMAIN_PACKAGES = frozenset({"tenancy", "ingestion", "identity", "graph", "journeys", "intelligence", "value", "actions", "governance", "workers", "connectors", "replay", "billing"})


def report(config_path: Path = CONFIG, root: Path = ROOT) -> int:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    result = analyse(raw, root)
    known = result["known"]
    unreachable = result["unreachable"]
    print(f"{len(known)} production modules, {len(result['live'])} reachable, "
          f"{len(unreachable)} unreachable ({sum(_lines(known[m]) for m in unreachable)} lines)")
    packages: dict[str, list[str]] = {}
    for module in unreachable:
        parts = module.split(".")
        top = ".".join(parts[:2]) if len(parts) > 1 and parts[0] in DOMAIN_PACKAGES else parts[0]
        packages.setdefault(top, []).append(module)
    for top, mods in sorted(packages.items(), key=lambda kv: -sum(_lines(known[m]) for m in kv[1])):
        print(f"{sum(_lines(known[m]) for m in mods):6d} {len(mods):3d} {top}")
        for module in mods:
            print(f"         {_lines(known[module]):5d} {module}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print unreachable modules per package")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.report:
        return report()
    errors = validate()
    if errors:
        print("backend reachability: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    allowed = sum(len(_entry_modules(i) or []) for i in raw.get("allow_unreachable") or [] if isinstance(i, dict))
    print(f"backend reachability: OK ({allowed} allowed unreachable modules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
