#!/usr/bin/env python3
"""Fail when a backend settings field reads an environment variable that nothing reads.

A flag that no code consults is not a control: setting it changes nothing, yet
release flag lists, ``.env`` examples, capability overlays and runbooks present
it as one. "Flags describe capabilities" only holds if a flag gates something.

For every dataclass field in ``services/backend/config/settings.py`` whose
default reads an environment variable (``_env_bool("NAME", ...)`` and friends),
the field counts as **read** when any of these holds in production Python:

* its environment variable name appears as a string constant that is exactly
  that name (a direct ``os.environ`` or ``_env`` read), outside docstrings;
* its attribute is read in code (``settings.comms.x``, ``self.x``) or named by an
  exact string constant (``getattr(cfg, "x")``), where a name only one config
  class defines is credited on any such read, and a name several classes define
  (``enabled``, ``port``) is credited only to the class it is read through: its
  section on ``Settings``, a variable annotated with the class or bound from the
  section earlier in the same or an enclosing scope, or ``self.x`` inside the class.

Comments, docstrings and prose never count, and neither does test code: a flag
only a test reads is not a runtime control. Fields that cannot be retired yet go
in ``config/unread_settings_flags.yaml`` as ``Class.field`` with the debt-ledger
row that owns them and a reason. The list can only shrink: an entry that is read
now, whose field is gone, or whose ledger row has disappeared is an error, and an
entry outside ``PERMITTED_UNREAD`` (a constant in this file, reviewed with its
test) is an error.

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
PERMITTED_UNREAD = frozenset({"RuntimeConfig.ml_mode"})

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


class _Scan:
    """What one module reads: code names, exact string constants, and scoped credits."""

    def __init__(self, text: str, skip_lines: frozenset[int] = frozenset()) -> None:
        self.names: set[str] = set()
        self.strings: set[str] = set()
        self.tree: ast.AST | None
        try:
            self.tree = ast.parse(text)
        except SyntaxError:
            self.tree = None
            return
        bare: set[int] = set()
        # ast.walk yields a parent before its children, so a bare string statement
        # (a docstring) is recorded before the constant inside it is reached.
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Expr):
                if isinstance(node.value, ast.Constant):
                    bare.add(id(node.value))
                continue
            if getattr(node, "lineno", 0) in skip_lines:
                continue
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    self.names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.ctx, ast.Load):
                    self.names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in bare:
                self.strings.add(node.value)

    def credits(
        self, owner_names: set[str], classes: set[str], shared: set[str], skip_lines: frozenset[int]
    ) -> dict[str, set[str]]:
        """Owners each shared field name is read through, with lexical, ordered aliases.

        A name bound from a section or class is credited only to reads that come
        after the binding, in the same function or an enclosing one; a binding in
        another function proves nothing. ``self.x = settings.section`` binds ``x``
        for the whole class.
        """
        credited: dict[str, set[str]] = {}
        dynamic: set[str] = set()  # owners read through getattr(<owner>, <variable>)
        funcs: dict[str, list[str]] = {}  # function name -> parameter names (self excluded)
        call_owner: dict[tuple[str, int | str], str] = {}  # (callee, position or keyword) -> owner passed
        pending: list[tuple[str, str, str]] = []  # (field, enclosing function, parameter name)
        func_stack: list[str] = []
        if self.tree is None:
            return credited
        # scopes: list of (kind, bindings) where bindings maps name -> (owner, lineno)
        scopes: list[tuple[str, dict[str, tuple[str, int]]]] = [("module", {})]
        class_stack: list[str] = []

        def lookup(name: str | None, line: int, via_self: bool) -> str | None:
            if name is None:
                return None
            if name in owner_names or name in classes:
                return name
            for kind, bindings in reversed(scopes):
                if via_self and kind != "class":
                    continue
                if not via_self and kind == "class":
                    continue
                hit = bindings.get(name)
                if hit and (kind == "class" or hit[1] <= line):
                    return hit[0]
            return None

        def bind(target: ast.AST, owner: str, line: int) -> None:
            if isinstance(target, ast.Name):
                scopes[-1][1][target.id] = (owner, line)
            elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                for kind, bindings in reversed(scopes):
                    if kind == "class":
                        bindings[target.attr] = (owner, line)
                        break

        def credit(field_name: str, qualifier: ast.AST | None, line: int) -> None:
            if field_name not in shared or line in skip_lines:
                return
            owner: str | None = None
            if isinstance(qualifier, ast.Name) and qualifier.id == "self" and class_stack:
                owner = class_stack[-1]
            elif isinstance(qualifier, ast.Attribute) and isinstance(qualifier.value, ast.Name) and qualifier.value.id == "self":
                owner = lookup(qualifier.attr, line, via_self=True)
            else:
                name = _terminal(qualifier)
                owner = lookup(name, line, via_self=False)
                if owner is None and isinstance(qualifier, ast.Name) and func_stack and name in funcs.get(func_stack[-1], ()):
                    pending.append((field_name, func_stack[-1], name))
            if owner:
                credited.setdefault(field_name, set()).add(owner)

        def visit(node: ast.AST) -> None:
            if isinstance(node, ast.ClassDef):
                scopes.append(("class", {}))
                class_stack.append(node.name)
                for child in node.body:
                    visit(child)
                class_stack.pop()
                scopes.pop()
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                scopes.append(("function", {}))
                fname = node.name if not isinstance(node, ast.Lambda) else ""
                if not isinstance(node, ast.Lambda):
                    params = [a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]]
                    funcs[fname] = [p for p in params if p != "self"]
                    for arg in [*node.args.args, *node.args.kwonlyargs]:
                        ann = _terminal(arg.annotation) if arg.annotation is not None else None
                        if ann in classes:
                            scopes[-1][1][arg.arg] = (ann, node.lineno)  # type: ignore[assignment]
                func_stack.append(fname)
                for child in ast.iter_child_nodes(node):
                    visit(child)
                func_stack.pop()
                scopes.pop()
                return
            if isinstance(node, ast.Assign):
                visit(node.value)
                for bound in _bound_names(node.value):
                    if bound and (bound in owner_names or bound in classes):
                        for target in node.targets:
                            bind(target, bound, node.lineno)
                return
            if isinstance(node, ast.AnnAssign):
                ann = _terminal(node.annotation)
                if node.value is not None:
                    visit(node.value)
                if ann in classes:
                    bind(node.target, ann, node.lineno)  # type: ignore[arg-type]
                else:
                    for bound in _bound_names(node.value) if node.value is not None else []:
                        if bound and (bound in owner_names or bound in classes):
                            bind(node.target, bound, node.lineno)
                return
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                credit(node.attr, node.value, node.lineno)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("getattr", "hasattr")
                and len(node.args) >= 2
            ):
                if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    credit(node.args[1].value, node.args[0], node.lineno)
                else:
                    owner = lookup(_terminal(node.args[0]), node.lineno, via_self=False)
                    if owner:
                        dynamic.add(owner)
            if isinstance(node, ast.Call):
                callee = _terminal(node.func)
                if callee:
                    for position, arg in enumerate(node.args):
                        passed = lookup(_terminal(arg), node.lineno, via_self=False)
                        if passed:
                            call_owner[(callee, position)] = passed
                    for keyword in node.keywords:
                        passed = lookup(_terminal(keyword.value), node.lineno, via_self=False)
                        if passed and keyword.arg:
                            call_owner[(callee, keyword.arg)] = passed
            for child in ast.iter_child_nodes(node):
                visit(child)

        visit(self.tree)
        # A function that reads a field through an unannotated parameter is credited
        # to the owner the module passes it at a call site.
        for field_name, fname, param in pending:
            index = funcs[fname].index(param)
            owner = call_owner.get((fname, index)) or call_owner.get((fname, param))
            if owner:
                credited.setdefault(field_name, set()).add(owner)
        # A helper that reads ``getattr(<owner>, name)`` reads every shared field
        # name the module lists as a string.
        for name in self.strings & shared:
            credited.setdefault(name, set()).update(dynamic)
        return credited


def unread_flags(root: Path = ROOT) -> list[Flag]:
    """Fields no production code reads (see the module docstring for the rules)."""
    flags = settings_flags(root)
    mounted = _composites(root)
    classes = {f.cls for f in flags}
    sections = {name for names in mounted.values() for name in names}
    owner_names = sections | classes
    shared = {name for name, count in collections.Counter(f.field for f in flags).items() if count > 1}
    settings_text = (root / SETTINGS).read_text(encoding="utf-8")
    defined = frozenset(n for f in flags for n in range(f.first_line, f.last_line + 1))

    names: set[str] = set()
    strings: set[str] = set()
    credited: dict[str, set[str]] = {}

    def absorb(scan: _Scan, skip: frozenset[int], scoped: bool) -> None:
        names.update(scan.names)
        strings.update(scan.strings)
        if scoped:
            for key, owners in scan.credits(owner_names, classes, shared, skip).items():
                credited.setdefault(key, set()).update(owners)

    absorb(_Scan(settings_text, defined), defined, True)
    # A file can only read a field if it contains the field's name or environment
    # variable, so most files need no parse at all.
    interesting = {f.env for f in flags} | {f.field for f in flags}
    for rel, text in _production_python(root):
        if rel == SETTINGS:
            continue
        tokens = set(_TOKEN.findall(text))
        if not tokens & interesting:
            continue
        scan = _Scan(text)
        # A credit needs the file to name a section or class, and a shared field.
        absorb(scan, frozenset(), bool(tokens & owner_names and tokens & shared))

    unread: list[Flag] = []
    for flag in flags:
        if flag.env in strings:
            continue
        if flag.field not in names and flag.field not in strings:
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
        if not (isinstance(item, dict) and _text(item.get("field")) and _text(item.get("ledger")) and _text(item.get("reason"))):
            errors.append(f"{label}: needs a non-empty field (Class.field), ledger and reason")
            continue
        if item["ledger"] not in ledger_ids:
            errors.append(f"{label}: ledger row {item['ledger']!r} does not exist")
        if item["field"] not in permitted:
            errors.append(
                f"{label}: {item['field']} is not a permitted exception; delete the field instead "
                "(PERMITTED_UNREAD in scripts/validate_settings_flags.py is the reviewed limit)"
            )
        if item["field"] in out:
            errors.append(f"{label}: {item['field']} is listed twice")
        out[item["field"]] = item["ledger"]
    return out, errors


def validate(
    root: Path = ROOT,
    allowlist: Path | None = None,
    ledger: Path | None = None,
    permitted: frozenset[str] = PERMITTED_UNREAD,
) -> list[str]:
    allow, errors = _allowlist(allowlist or ALLOWLIST, _ledger_ids(ledger or LEDGER), permitted)
    flags = {f"{f.cls}.{f.field}": f for f in settings_flags(root)}
    unread = {f"{f.cls}.{f.field}": f for f in unread_flags(root)}
    for key, flag in sorted(unread.items()):
        if key in allow:
            continue
        errors.append(
            f"{key} ({flag.env}) is defined in settings but nothing reads it; "
            "delete it, or wire it to the behavior it claims to gate"
        )
    for key in sorted(allow):
        if key not in flags:
            errors.append(f"allowlist entry {key} no longer exists in settings; delete the entry")
        elif key not in unread:
            errors.append(f"allowlist entry {key} is read now; delete the entry")
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
