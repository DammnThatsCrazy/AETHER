#!/usr/bin/env python3
"""Fail when a backend settings field reads an environment variable that nothing reads.

A flag that no code consults is not a control: setting it changes nothing, yet
release flag lists, ``.env`` examples, capability overlays and runbooks present
it as one. "Flags describe capabilities" only holds if a flag gates something.

For every dataclass field in ``services/backend/config/settings.py`` whose
default reads an environment variable (``_env_bool("NAME", ...)`` and friends),
the field counts as **read** when any of these holds:

* its attribute name appears in production Python outside the field's own
  definition (``settings.comms.graph_enabled``, ``getattr(cfg, "x_enabled")``,
  ``self.x_enabled`` inside the settings module itself);
* its environment variable name appears as a literal in production Python
  (a direct ``os.environ`` read).

Test code does not count: a flag only a test reads is not a runtime control.
Fields that cannot be retired yet go in ``config/unread_settings_flags.yaml``
with the debt-ledger row that owns them and a reason; that list is shrink-only
(an entry that is read now, whose field is gone, or whose ledger row has
disappeared is an error).

Only backend Python counts as a reader: an environment variable consumed by a
different runtime (a Node service, a Terraform module) is not a field of this
module and does not belong in it.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, NamedTuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = "services/backend/config/settings.py"
ALLOWLIST = ROOT / "config/unread_settings_flags.yaml"
LEDGER = ROOT / "config/debt_retirement_ledger.yaml"

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".mypy_cache", ".pytest_cache"}


class Flag(NamedTuple):
    cls: str
    field: str
    env: str
    first_line: int
    last_line: int


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (
        "tests" in parts
        or "test" in parts
        or name.startswith(("test_", "conftest"))
        or name.endswith("_test.py")
    )


def _env_name(value: ast.AST | None) -> str | None:
    """The environment variable a field default reads, however it is wrapped.

    Handles ``_env_bool("X", ...)``, ``float(_env("X", ...))`` and
    ``field(default_factory=lambda: _env_list("X", ...))``.
    """
    if value is None:
        return None
    for node in ast.walk(value):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.startswith("_env"):
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value
    return None


def settings_flags(root: Path = ROOT) -> list[Flag]:
    """Env-backed dataclass fields in the settings module."""
    tree = ast.parse((root / SETTINGS).read_text(encoding="utf-8"))
    flags: list[Flag] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            env = _env_name(stmt.value)
            if env:
                flags.append(Flag(node.name, stmt.target.id, env, stmt.lineno, stmt.end_lineno or stmt.lineno))
    return flags


def _production_python(root: Path) -> Iterable[tuple[str, str]]:
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(current, root).replace(os.sep, "/")
        if rel_dir.startswith("docs/archive"):
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            rel = f"{rel_dir}/{name}" if rel_dir != "." else name
            if _is_test(rel):
                continue
            try:
                yield rel, (Path(current) / name).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue


def unread_flags(root: Path = ROOT) -> list[Flag]:
    flags = settings_flags(root)
    settings_lines = (root / SETTINGS).read_text(encoding="utf-8").split("\n")
    defined = {n for f in flags for n in range(f.first_line, f.last_line + 1)}
    settings_rest = "\n".join(line for i, line in enumerate(settings_lines, 1) if i not in defined)
    tokens: set[str] = set()
    for rel, text in _production_python(root):
        if rel != SETTINGS:
            tokens.update(_TOKEN.findall(text))
    tokens.update(_TOKEN.findall(settings_rest))
    unread: list[Flag] = []
    for flag in flags:
        if flag.field in tokens or flag.env in tokens:
            continue
        unread.append(flag)
    return unread


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


def _allowlist(path: Path, ledger_ids: set[str]) -> tuple[dict[str, str], list[str]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return {}, [f"cannot load unread settings flag allowlist: {exc}"]
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return {}, ["unread settings flag allowlist: schema_version must be 1"]
    allow = raw.get("allow") or []
    if not isinstance(allow, list):
        return {}, ["unread settings flag allowlist: allow must be a list"]
    errors: list[str] = []
    out: dict[str, str] = {}
    for i, item in enumerate(allow):
        label = f"allow[{i}]"
        if not (isinstance(item, dict) and _text(item.get("env")) and _text(item.get("ledger")) and _text(item.get("reason"))):
            errors.append(f"{label}: needs a non-empty env, ledger and reason")
            continue
        if item["ledger"] not in ledger_ids:
            errors.append(f"{label}: ledger row {item['ledger']!r} does not exist")
        if item["env"] in out:
            errors.append(f"{label}: {item['env']} is listed twice")
        out[item["env"]] = item["ledger"]
    return out, errors


def validate(root: Path = ROOT, allowlist: Path | None = None, ledger: Path | None = None) -> list[str]:
    allow, errors = _allowlist(allowlist or ALLOWLIST, _ledger_ids(ledger or LEDGER))
    flags = {f.env: f for f in settings_flags(root)}
    unread = {f.env: f for f in unread_flags(root)}
    for env, flag in sorted(unread.items()):
        if env in allow:
            continue
        errors.append(
            f"{flag.cls}.{flag.field} ({env}) is defined in settings but nothing reads it; "
            "delete it, or wire it to the behavior it claims to gate"
        )
    for env in sorted(allow):
        if env not in flags:
            errors.append(f"allowlist entry {env} no longer exists in settings; delete the entry")
        elif env not in unread:
            errors.append(f"allowlist entry {env} is read now; delete the entry")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print every unread flag")
    args = parser.parse_args(argv)
    if args.report:
        flags = unread_flags()
        for f in flags:
            print(f"{f.cls}.{f.field}  {f.env}")
        print(f"{len(flags)} unread of {len(settings_flags())} env-backed settings fields")
        return 0
    errors = validate()
    if errors:
        print("settings flags: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    allowed = len(_allowlist(ALLOWLIST, set())[0])
    print(f"settings flags: {len(settings_flags())} env-backed fields, all read ({allowed} allowed unread)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
