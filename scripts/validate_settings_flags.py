#!/usr/bin/env python3
"""Fail when a backend settings field reads an environment variable that nothing reads.

A flag that no code consults is not a control: setting it changes nothing, yet
release flag lists, ``.env`` examples, capability overlays and runbooks present
it as one. "Flags describe capabilities" only holds if a flag gates something.

For every dataclass field in ``services/backend/config/settings.py`` whose
default reads an environment variable (``_env_bool("NAME", ...)`` and friends),
the field counts as **read** when any of these holds:

* its attribute is read through its own config object: ``settings.comms.x``,
  ``getattr(settings.comms, "x")``, a variable annotated or assigned from its
  class or section, or ``self.x`` inside its own class. A name that only one
  config class defines is credited on any attribute read; a name several classes
  define (``enabled``, ``port``) must be read through the right one;
* its environment variable name appears as a literal in production Python
  (a direct ``os.environ`` read).

Test code does not count: a flag only a test reads is not a runtime control.
Fields that cannot be retired yet go in ``config/unread_settings_flags.yaml``
with the debt-ledger row that owns them and a reason. The list can only shrink:
an entry that is read now, whose field is gone, or whose ledger row has
disappeared is an error, and an entry outside ``PERMITTED_UNREAD`` (a constant in
this file, reviewed with its test) is an error.

Only backend Python counts as a reader: an environment variable consumed by a
different runtime (a Node service, a Terraform module) is not a field of this
module and does not belong in it.
"""

from __future__ import annotations

import argparse
import ast
import collections
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
# The only unread fields that may be allowlisted. Growing this set is a change to
# this file, so it is reviewed with its test and the retirement page (the
# ``settings_flags`` ownership category); a new allowlist entry alone cannot
# admit a new inert field.
PERMITTED_UNREAD = frozenset({"ML_MODE"})

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# The validator names permitted fields as string literals; it is not a reader.
_SELF = "scripts/validate_settings_flags.py"
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
            if _is_test(rel) or rel == _SELF:
                continue
            try:
                yield rel, (Path(current) / name).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue


def _terminal(node: ast.AST | None) -> str | None:
    """The last identifier of ``a.b.c`` (``c``), a name, or the callee of a call."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _terminal(node.func)
    return None


def _composites(root: Path) -> dict[str, set[str]]:
    """Config class name -> the attribute names it is mounted under on ``Settings``."""
    tree = ast.parse((root / SETTINGS).read_text(encoding="utf-8"))
    mounted: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and isinstance(stmt.annotation, ast.Name)
                ):
                    mounted.setdefault(stmt.annotation.id, set()).add(stmt.target.id)
    return mounted


def _bound_names(value: ast.AST) -> list[str | None]:
    """Identifiers a value expression stands for: ``settings.comms``, ``x or settings.comms``,
    ``getattr(settings, "comms", None)``, ``CommsConfig()``."""
    if isinstance(value, ast.IfExp):
        return _bound_names(value.body) + _bound_names(value.orelse)
    if isinstance(value, ast.BoolOp):
        return [name for part in value.values for name in _bound_names(part)]
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "getattr"
        and len(value.args) >= 2
        and isinstance(value.args[1], ast.Constant)
    ):
        return [value.args[1].value if isinstance(value.args[1].value, str) else None]
    return [_terminal(value)]


def _credits(text: str, owner_names: set[str], classes: set[str], shared: set[str], skip_lines: set[int]) -> dict[str, set[str]]:
    """For each shared field name read in ``text``: the config owners it is read through.

    One pass collects the reads and the names bound from a section or class; a
    read through a bound name is credited to what it was bound from.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    alias: dict[str, str] = {}
    reads: list[tuple[str, str | None]] = []

    def visit(node: ast.AST, owner_class: str | None) -> None:
        if isinstance(node, ast.ClassDef):
            owner_class = node.name
        elif isinstance(node, ast.Assign):
            targets = [t for t in (_terminal(x) for x in node.targets) if t]
            for bound in _bound_names(node.value):
                if bound in owner_names or bound in classes:
                    for name in targets:
                        alias[name] = bound  # type: ignore[assignment]
        elif isinstance(node, ast.AnnAssign):
            name, ann = _terminal(node.target), _terminal(node.annotation)
            if name and ann in classes:
                alias[name] = ann  # type: ignore[assignment]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                ann = _terminal(arg.annotation) if arg.annotation is not None else None
                if ann in classes:
                    alias[arg.arg] = ann  # type: ignore[assignment]
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr in shared:
            if node.lineno not in skip_lines:
                self_read = isinstance(node.value, ast.Name) and node.value.id == "self" and owner_class
                reads.append((node.attr, owner_class if self_read else _terminal(node.value)))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in shared
        ):
            first = node.args[0]
            self_read = isinstance(first, ast.Name) and first.id == "self" and owner_class
            reads.append((node.args[1].value, owner_class if self_read else _terminal(first)))
        for child in ast.iter_child_nodes(node):
            visit(child, owner_class)

    visit(tree, None)
    credited: dict[str, set[str]] = {}
    for field_name, qualifier in reads:
        if qualifier is None:
            continue
        owner = qualifier if qualifier in owner_names or qualifier in classes else alias.get(qualifier)
        if owner:
            credited.setdefault(field_name, set()).add(owner)
    return credited


def unread_flags(root: Path = ROOT) -> list[Flag]:
    """Fields no production code reads.

    A field is read when its environment variable name appears in production
    Python, or when its attribute is read through its own config object. An
    attribute name shared by several config classes (``enabled``, ``port``) is
    only credited to a class when the read goes through that class's mounted
    section on ``Settings`` (``settings.comms.x``), a class-annotated variable, or
    a name bound from one; ``something.enabled`` on an unrelated object proves
    nothing.
    """
    flags = settings_flags(root)
    mounted = _composites(root)
    classes = {f.cls for f in flags}
    sections = {name for names in mounted.values() for name in names}
    owner_names = sections | classes
    shared = {name for name, count in collections.Counter(f.field for f in flags).items() if count > 1}
    settings_text = (root / SETTINGS).read_text(encoding="utf-8")
    defined = {n for f in flags for n in range(f.first_line, f.last_line + 1)}
    settings_rest = "\n".join(line for i, line in enumerate(settings_text.split("\n"), 1) if i not in defined)
    tokens: set[str] = set(_TOKEN.findall(settings_rest))
    credited: dict[str, set[str]] = {}

    def add(found: dict[str, set[str]]) -> None:
        for name, owners in found.items():
            credited.setdefault(name, set()).update(owners)

    for rel, text in _production_python(root):
        if rel == SETTINGS:
            continue
        file_tokens = set(_TOKEN.findall(text))
        tokens.update(file_tokens)
        # A credit needs the file to name a section or class, and a shared field.
        if file_tokens & owner_names and file_tokens & shared:
            add(_credits(text, owner_names, classes, shared, set()))
    add(_credits(settings_text, owner_names, classes, shared, defined))

    unread: list[Flag] = []
    for flag in flags:
        if flag.env in tokens:
            continue
        if flag.field not in tokens:
            unread.append(flag)
        elif flag.field in shared and not (credited.get(flag.field, set()) & (mounted.get(flag.cls, set()) | {flag.cls})):
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


def _allowlist(path: Path, ledger_ids: set[str], permitted: frozenset[str] = PERMITTED_UNREAD) -> tuple[dict[str, str], list[str]]:
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
        if item["env"] not in permitted:
            errors.append(
                f"{label}: {item['env']} is not a permitted exception; delete the field instead "
                "(PERMITTED_UNREAD in scripts/validate_settings_flags.py is the reviewed limit)"
            )
        if item["env"] in out:
            errors.append(f"{label}: {item['env']} is listed twice")
        out[item["env"]] = item["ledger"]
    return out, errors


def validate(
    root: Path = ROOT,
    allowlist: Path | None = None,
    ledger: Path | None = None,
    permitted: frozenset[str] = PERMITTED_UNREAD,
) -> list[str]:
    allow, errors = _allowlist(allowlist or ALLOWLIST, _ledger_ids(ledger or LEDGER), permitted)
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
