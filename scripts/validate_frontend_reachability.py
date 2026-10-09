#!/usr/bin/env python3
"""Fail when a frontend app holds source files that nothing mounts.

``config/frontend_reachability.yaml`` names each app's entry points. Every
non-test ``.ts``/``.tsx`` file under the app's ``src`` must be reachable from
them through static imports, dynamic ``import()`` and re-exports, unless it is
listed under ``allow_unreachable`` with the debt-ledger row that owns the
decision. An allowlist entry is itself an error once the file is gone, has become
reachable, or its ledger row has disappeared, so the list can only shrink.

``--report`` prints the unreachable files and their size for every app.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/frontend_reachability.yaml"
LEDGER = ROOT / "config/debt_retirement_ledger.yaml"

SOURCE_SUFFIXES = (".ts", ".tsx")
RESOLVE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".svg")
_IMPORT = re.compile(
    r"""(?:import|export)\s[^'"`;]*?from\s*['"]([^'"]+)['"]"""
    r"""|import\s*['"]([^'"]+)['"]"""
    r"""|import\(\s*['"]([^'"]+)['"]\s*\)"""
    r"""|require\(\s*['"]([^'"]+)['"]\)"""
    r"""|new\s+URL\(\s*['"]([^'"]+)['"]""",
    re.S,
)
# Computed or glob imports cannot be followed statically; refuse them instead of
# silently reporting their targets as unreachable (or, worse, as reachable).
_UNRESOLVABLE = re.compile(r"import\.meta\.glob|require\.context|import\(\s*[`A-Za-z_$]")


def is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (
        "test" in parts
        or "__tests__" in parts
        or ".test." in name
        or ".spec." in name
        or name.endswith(".d.ts")
    )


def _source_files(src: Path) -> list[Path]:
    return sorted(
        p for p in src.rglob("*")
        if p.is_file() and p.suffix in SOURCE_SUFFIXES and "node_modules" not in p.parts
    )


def _resolve(importer: Path, spec: str, src: Path, alias: str) -> Path | None:
    if spec.startswith(alias + "/"):
        base = src / spec[len(alias) + 1:]
    elif spec.startswith("."):
        base = (importer.parent / spec).resolve()
    else:
        return None
    candidates = [base]
    candidates += [Path(str(base) + ext) for ext in RESOLVE_SUFFIXES]
    candidates += [base / f"index{ext}" for ext in RESOLVE_SUFFIXES]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _imports(path: Path, src: Path, alias: str) -> tuple[list[Path], bool]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return [], False
    found: list[Path] = []
    for match in _IMPORT.finditer(text):
        spec = next(group for group in match.groups() if group)
        target = _resolve(path, spec, src, alias)
        if target is not None:
            found.append(target)
    return found, bool(_UNRESOLVABLE.search(text))


def reachable(src: Path, alias: str, roots: list[Path]) -> tuple[set[Path], list[Path]]:
    """Files reachable from ``roots``, and files using imports that cannot be followed."""
    seen: set[Path] = set()
    opaque: list[Path] = []
    stack = [r.resolve() for r in roots]
    while stack:
        current = stack.pop()
        if current in seen or not current.is_file():
            continue
        seen.add(current)
        if current.suffix in SOURCE_SUFFIXES:
            targets, is_opaque = _imports(current, src, alias)
            if is_opaque:
                opaque.append(current)
            stack.extend(targets)
    return seen, opaque


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


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def analyse(app: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Unreachable files for one configured app (no policy applied)."""
    app_root = root / app["root"]
    src = app_root / "src"
    alias = app["alias"]
    entries = [app_root / e for e in app["entries"]]
    allowed = [app_root / a["path"] for a in app.get("allow_unreachable") or [] if isinstance(a, dict) and _text(a.get("path"))]
    live, opaque = reachable(src, alias, entries)
    live_with_allowed, opaque_allowed = reachable(src, alias, entries + allowed)
    sources = [
        p.resolve() for p in _source_files(src)
        if not is_test_path(p.relative_to(app_root).as_posix())
    ]
    return {
        "app_root": app_root.resolve(),
        "live": live,
        "live_with_allowed": live_with_allowed,
        "opaque": sorted(set(opaque) | set(opaque_allowed)),
        "unreachable": sorted(p for p in sources if p not in live_with_allowed),
        "sources": sources,
    }


def validate(config: Path = CONFIG, ledger: Path = LEDGER, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot load frontend reachability config: {exc}"]
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return ["schema_version must be 1"]
    if raw.get("authority") != "frontend-reachability":
        errors.append("authority must be frontend-reachability")
    apps = raw.get("apps")
    if not isinstance(apps, dict) or not apps:
        return errors + ["apps must be a non-empty mapping"]
    ledger_ids = _ledger_ids(ledger)

    for name, app in sorted(apps.items(), key=lambda kv: str(kv[0])):
        where = f"app {name!r}"
        if not isinstance(app, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        if not (_text(app.get("root")) and _text(app.get("alias"))):
            errors.append(f"{where}: root and alias must be non-empty strings")
            continue
        app_root = (root / app["root"]).resolve()
        if root.resolve() not in app_root.parents or not (app_root / "src").is_dir():
            errors.append(f"{where}: root {app['root']!r} must be a directory with a src folder inside the repository")
            continue
        entries = app.get("entries")
        if not isinstance(entries, list) or not entries or not all(_text(e) for e in entries):
            errors.append(f"{where}: entries must be a non-empty list of paths")
            continue
        missing_entries = [e for e in entries if not (app_root / e).resolve().is_file() or app_root not in (app_root / e).resolve().parents]
        if missing_entries:
            errors.append(f"{where}: entry points do not exist inside the app: {missing_entries}")
            continue

        allow = app.get("allow_unreachable") or []
        if not isinstance(allow, list):
            errors.append(f"{where}: allow_unreachable must be a list")
            continue
        allowed_paths: set[Path] = set()
        for index, item in enumerate(allow):
            label = f"{where} allow_unreachable[{index}]"
            if not isinstance(item, dict) or not (_text(item.get("path")) and _text(item.get("ledger")) and _text(item.get("reason"))):
                errors.append(f"{label}: needs non-empty path, ledger and reason")
                continue
            target = (app_root / item["path"]).resolve()
            if app_root not in target.parents or not target.is_file():
                errors.append(f"{label}: {item['path']} does not exist (delete the entry)")
                continue
            if item["ledger"] not in ledger_ids:
                errors.append(f"{label}: ledger row {item['ledger']!r} does not exist")
            if target in allowed_paths:
                errors.append(f"{label}: {item['path']} is listed twice")
            allowed_paths.add(target)

        result = analyse({**app, "allow_unreachable": [a for a in allow if isinstance(a, dict)]}, root)
        for path in result["opaque"]:
            rel = path.relative_to(app_root).as_posix()
            errors.append(f"{where}: {rel} uses an import that cannot be followed statically (glob or computed path)")
        for path in sorted(allowed_paths):
            if path in result["live"]:
                errors.append(
                    f"{where}: {path.relative_to(app_root).as_posix()} is reachable now; remove it from allow_unreachable"
                )
        for path in result["unreachable"]:
            rel = path.relative_to(app_root).as_posix()
            errors.append(
                f"{where}: {rel} is not reachable from the app entry points; mount it, delete it, "
                "or list it under allow_unreachable with a ledger row"
            )
    return errors


def report(config: Path = CONFIG, root: Path = ROOT) -> int:
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    for name, app in sorted(raw["apps"].items()):
        result = analyse(app, root)
        app_root = result["app_root"]
        total = sum(1 for _ in result["sources"])
        loc = lambda p: sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))  # noqa: E731
        print(f"{name}: {len(result['live'])} reachable, {total} non-test source files, "
              f"{len(result['unreachable'])} unreachable ({sum(loc(p) for p in result['unreachable'])} lines)")
        for path in result["unreachable"]:
            print(f"  {loc(path):5d} {path.relative_to(app_root).as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print unreachable files per app")
    args = parser.parse_args(argv)
    if args.report:
        return report()
    errors = validate()
    if errors:
        print("frontend reachability: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    allowed = sum(len(a.get("allow_unreachable") or []) for a in raw["apps"].values())
    print(f"frontend reachability: {len(raw['apps'])} app(s) OK ({allowed} allowed unreachable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
