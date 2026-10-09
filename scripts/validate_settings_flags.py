#!/usr/bin/env python3
"""Fail when a backend settings field reads an environment variable that nothing reads.

A flag that no code consults is not a control: setting it changes nothing, yet
release flag lists, ``.env`` examples, capability overlays and runbooks present
it as one. "Flags describe capabilities" only holds if a flag gates something.

For every dataclass field in ``services/backend/config/settings.py`` whose
default reads an environment variable (``_env_bool("NAME", ...)`` and friends),
the field counts as **read** when any of these holds in production Python:

* its environment variable name is the key of an environment read: an argument of
  ``os.getenv`` or of an ``*env*`` helper or ``environ.get``, an ``environ[...]``
  subscript, or ``"NAME" in environ`` (a name merely listed in a tuple, dict or
  string elsewhere is not a read);
* its attribute is read in code (``settings.comms.x``, ``self.x``) or named by an
  exact string constant (``getattr(cfg, "x")``) through its own config object: its
  section on ``Settings``, a variable annotated with the class or bound from the
  section earlier in the same or an enclosing scope (a later assignment of anything
  else drops the binding), a parameter the module passes the section at a call site
  (only when one function has that name), or ``self.x`` inside the class. The same
  attribute name on an unrelated object (``args.port``) proves nothing, for every
  field, not only for names several classes share.

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
BACKEND = "services/backend"
SETTINGS = f"{BACKEND}/config/settings.py"
ALLOWLIST = ROOT / "config/unread_settings_flags.yaml"
LEDGER = ROOT / "config/debt_retirement_ledger.yaml"
# The only unread fields that may be allowlisted. Growing this set is a change to
# this file, so it is reviewed with its test and the retirement page (the
# ``settings_flags`` ownership category); a new allowlist entry alone cannot
# admit a new inert field.
PERMITTED_UNREAD = frozenset(
    {
        "RuntimeConfig.ml_mode",
        "TrustPlaneConfig.trust_plane_enabled",
        "KyberWorkforceConfig.session_cookie_secure",
    }
)

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


def _is_env(node: ast.AST | None) -> bool:
    """``os.environ``, ``environ``, ``env`` and the like: an object that holds environment variables."""
    name = _terminal(node)
    return name is not None and ("environ" in name.lower() or name.lower() in {"env", "_env"})


def _env_lookup_keys(node: ast.AST, consts: dict[str, str]) -> list[str]:
    """String constants (or names bound to one) this node uses as the key of an environment read."""
    keys: list[ast.AST] = []
    if isinstance(node, ast.Call):
        lowered = (_terminal(node.func) or "").lower()
        reader = lowered == "getenv" or bool(set(lowered.split("_")) & {"env", "getenv", "environ", "dotenv"})
        accessor = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "pop", "setdefault"}
            and _is_env(node.func.value)
        )
        if reader or accessor:
            keys.extend(node.args[:1])
            keys.extend(keyword.value for keyword in node.keywords if keyword.arg in {"name", "key", "var"})
    elif isinstance(node, ast.Subscript) and _is_env(node.value):
        keys.append(node.slice)
    elif isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        if any(_is_env(comparator) for comparator in node.comparators):
            keys.append(node.left)
    found: list[str] = []
    for key in keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            found.append(key.value)
        elif isinstance(key, ast.Name) and key.id in consts:
            found.append(consts[key.id])
    return found


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
        self.strings: set[str] = set()  # every non-docstring string constant
        self.dynamic_owners: set[str] = set()  # owners read through getattr(<owner>, <variable>)
        self.imports: dict[str, tuple[str, str]] = {}  # local name -> (dotted module, original name)
        self.collections: dict[str, set[str]] = {}  # module-level NAME = (<string constants>)
        self.env_keys: set[str] = set()  # string constants used as an environment lookup key
        self.tree: ast.AST | None
        try:
            self.tree = ast.parse(text)
        except SyntaxError:
            self.tree = None
            return
        consts: dict[str, str] = {}  # NAME = "LITERAL" anywhere in the module
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = (node.module, alias.name)
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        consts[target.id] = node.value.value
        for node in getattr(self.tree, "body", []):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, (ast.Tuple, ast.List, ast.Set))
                and node.value.elts
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts)
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.collections[target.id] = {e.value for e in node.value.elts}
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
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in bare:
                self.strings.add(node.value)
            for key in _env_lookup_keys(node, consts):
                self.env_keys.add(key)

    def credits(
        self, owner_names: set[str], classes: set[str], fields: set[str], skip_lines: frozenset[int]
    ) -> dict[str, set[str]]:
        """Owners each field name is read through, with lexical, ordered aliases.

        A name bound from a section or class is credited only to reads that come
        after the binding, in the same function or an enclosing one; a binding in
        another function proves nothing, and assigning anything else to the name
        (or taking it as a parameter) drops the binding. ``self.x = settings.section``
        binds ``x`` for the whole class.
        """
        credited: dict[str, set[str]] = {}
        dynamic: set[str] = set()  # owners read through getattr(<owner>, <variable>)
        funcs: dict[str, list[list[str]]] = {}  # function name -> parameter names of each definition (self excluded)
        call_owner: dict[tuple[str, int | str], set[str]] = {}  # (callee, position or keyword) -> owners passed
        pending: list[tuple[str, str, str]] = []  # (field, enclosing function, parameter name)
        func_stack: list[str] = []
        if self.tree is None:
            return credited
        # Functions that only ever return a section or config class (``return settings.storage_plane``).
        returns: dict[str, str] = {}
        for fn in ast.walk(self.tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}
                # ``return cfg`` of a parameter hands back what the caller passed: it is not
                # another owner, so ``cfg or settings.x`` and ``if cfg is not None: return cfg``
                # both leave the function standing for the section it falls back to.
                values = [
                    r.value
                    for r in ast.walk(fn)
                    if isinstance(r, ast.Return)
                    and r.value is not None
                    and not (isinstance(r.value, ast.Name) and r.value.id in params)
                ]
                owners = {
                    n for v in values for n in _bound_names(v) if n and (n in owner_names or n in classes)
                }
                if values and len(owners) == 1 and all(
                    any(n in owners for n in _bound_names(v)) for v in values
                ):
                    returns[fn.name] = next(iter(owners))
        # scopes: list of (kind, bindings) where bindings maps name -> (owner, lineno);
        # an owner of None records that the name was rebound to something else
        scopes: list[tuple[str, dict[str, tuple[str | None, int]]]] = [("module", {})]
        class_stack: list[str] = []

        def lookup(name: str | None, line: int, via_self: bool) -> str | None:
            if name is None:
                return None
            if name == "settings" and "Settings" in classes and not via_self:
                return "Settings"  # the module-level singleton: ``settings.debug``
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

        def bind(target: ast.AST, owner: str | None, line: int) -> None:
            if isinstance(target, ast.Name):
                scopes[-1][1][target.id] = (owner, line)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for element in target.elts:
                    bind(element, None, line)
            elif isinstance(target, ast.Starred):
                bind(target.value, None, line)
            elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                for kind, bindings in reversed(scopes):
                    if kind == "class":
                        bindings[target.attr] = (owner, line)
                        break

        def credit(field_name: str, qualifier: ast.AST | None, line: int) -> None:
            if field_name not in fields or line in skip_lines:
                return
            owner: str | None = None
            if isinstance(qualifier, ast.Name) and qualifier.id == "self" and class_stack:
                owner = class_stack[-1]
            elif isinstance(qualifier, ast.Attribute) and isinstance(qualifier.value, ast.Name) and qualifier.value.id == "self":
                owner = lookup(qualifier.attr, line, via_self=True)
            else:
                for name in (_bound_names(qualifier) if qualifier is not None else []):
                    owner = lookup(name, line, via_self=False)
                    if owner is None and isinstance(qualifier, ast.Call) and name in returns:
                        owner = returns[name]  # ``self._plane().x`` where ``_plane`` returns a section
                    if owner:
                        break
                if owner is None and isinstance(qualifier, ast.Name) and func_stack and func_stack[-1]:
                    pending.append((field_name, func_stack[-1], qualifier.id))
            if owner:
                credited.setdefault(field_name, set()).add(owner)

        def visit_target(target: ast.AST) -> None:
            """An assignment target can itself contain reads (``a.b[c.d] = ...``)."""
            if isinstance(target, ast.Name):
                return
            if isinstance(target, (ast.Tuple, ast.List)):
                for element in target.elts:
                    visit_target(element)
            elif isinstance(target, ast.Starred):
                visit_target(target.value)
            elif isinstance(target, ast.Attribute):
                visit(target.value)
            elif isinstance(target, ast.Subscript):
                visit(target.value)
                visit(target.slice)

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
                every = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                for arg in (*every, *filter(None, (node.args.vararg, node.args.kwarg))):
                    scopes[-1][1][arg.arg] = (None, node.lineno)  # a parameter shadows an outer binding
                if not isinstance(node, ast.Lambda):
                    funcs.setdefault(fname, []).append([a.arg for a in every if a.arg != "self"])
                    for arg in [*node.args.args, *node.args.kwonlyargs]:
                        ann = _terminal(arg.annotation) if arg.annotation is not None else None
                        if ann in classes:
                            scopes[-1][1][arg.arg] = (ann, node.lineno)
                func_stack.append(fname)
                for child in ast.iter_child_nodes(node):
                    visit(child)
                func_stack.pop()
                scopes.pop()
                return
            if isinstance(node, ast.Assign):
                visit(node.value)
                owners = [b for b in _bound_names(node.value) if b and (b in owner_names or b in classes)]
                if not owners and isinstance(node.value, ast.Call):
                    called = _terminal(node.value.func)
                    if called in returns:  # ``cfg = _resolve_config(cfg)``
                        owners = [returns[called]]
                for target in node.targets:
                    bind(target, owners[0] if owners else None, node.lineno)
                    visit_target(target)
                return
            if isinstance(node, ast.AnnAssign):
                ann = _terminal(node.annotation)
                if node.value is not None:
                    visit(node.value)
                owners = [b for b in (_bound_names(node.value) if node.value is not None else []) if b and (b in owner_names or b in classes)]
                bind(node.target, ann if ann in classes else (owners[0] if owners else None), node.lineno)
                visit_target(node.target)
                return
            if isinstance(node, ast.AugAssign):
                visit(node.value)
                bind(node.target, None, node.lineno)
                visit_target(node.target)
                return
            if isinstance(node, (ast.For, ast.AsyncFor)):
                visit(node.iter)
                bind(node.target, None, node.lineno)
                for child in [*node.body, *node.orelse]:
                    visit(child)
                return
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    visit(item.context_expr)
                    if item.optional_vars is not None:
                        bind(item.optional_vars, None, node.lineno)
                for child in node.body:
                    visit(child)
                return
            if isinstance(node, ast.NamedExpr):
                visit(node.value)
                bind(node.target, None, node.lineno)
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
                            call_owner.setdefault((callee, position), set()).add(passed)
                    for keyword in node.keywords:
                        passed = lookup(_terminal(keyword.value), node.lineno, via_self=False)
                        if passed and keyword.arg:
                            call_owner.setdefault((callee, keyword.arg), set()).add(passed)
            for child in ast.iter_child_nodes(node):
                visit(child)

        visit(self.tree)
        # A function that reads a field through an unannotated parameter is credited
        # to the owners the module passes it at its call sites, when one function has
        # that name (two definitions sharing a name cannot be told apart by name).
        for field_name, fname, param in pending:
            definitions = funcs.get(fname, [])
            if len(definitions) != 1 or param not in definitions[0]:
                continue
            index = definitions[0].index(param)
            for owner in call_owner.get((fname, index), set()) | call_owner.get((fname, param), set()):
                credited.setdefault(field_name, set()).add(owner)
        # A helper that reads ``getattr(<owner>, name)`` reads every field name the
        # module lists as a string.
        for name in self.strings & fields:
            credited.setdefault(name, set()).update(dynamic)
        self.dynamic_owners = dynamic
        return credited


def unread_flags(root: Path = ROOT) -> list[Flag]:
    """Fields no production code reads (see the module docstring for the rules)."""
    flags = settings_flags(root)
    mounted = _composites(root)
    classes = {f.cls for f in flags}
    sections = {name for names in mounted.values() for name in names}
    owner_names = sections | classes
    fields = {f.field for f in flags}
    settings_text = (root / SETTINGS).read_text(encoding="utf-8")
    defined = frozenset(n for f in flags for n in range(f.first_line, f.last_line + 1))

    env_keys: set[str] = set()
    credited: dict[str, set[str]] = {}

    def absorb(scan: _Scan, skip: frozenset[int], scoped: bool) -> None:
        env_keys.update(scan.env_keys)
        if scoped:
            for key, owners in scan.credits(owner_names, classes, fields, skip).items():
                credited.setdefault(key, set()).update(owners)

    absorb(_Scan(settings_text, defined), defined, True)
    # Most files name neither an environment variable nor a section, so need no parse.
    env_names = {f.env for f in flags}
    scans: dict[str, _Scan] = {}
    for rel, text in _production_python(root):
        if rel == SETTINGS:
            continue
        tokens = set(_TOKEN.findall(text))
        # An environment read needs the variable's name in the file; a credit needs a
        # section or class name (a module that loops ``getattr(section, name)`` over an
        # imported tuple names no field itself, but it does name the section).
        if not tokens & env_names and not tokens & owner_names:
            continue
        scan = _Scan(text)
        scans[rel] = scan
        # A credit needs the file to name a section or class.
        absorb(scan, frozenset(), bool(tokens & owner_names))
    # A module that reads ``getattr(<owner>, name)`` for a tuple of names it imports
    # (``for name in REQUIRED_FLAGS``) reads every field that tuple lists.
    for scan in scans.values():
        for module, original in scan.imports.values():
            home = scans.get(f"{BACKEND}/{module.replace('.', '/')}.py")
            for name in (home.collections.get(original, set()) if home else set()) & fields:
                credited.setdefault(name, set()).update(scan.dynamic_owners)

    unread: list[Flag] = []
    for flag in flags:
        if flag.env in env_keys:
            continue
        if not credited.get(flag.field, set()) & (mounted.get(flag.cls, set()) | {flag.cls}):
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
