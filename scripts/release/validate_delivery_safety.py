#!/usr/bin/env python3
"""Delivery-safety validator — fail the build on unsafe delivery patterns.

This is the permanent gate that D11 promotes from the D2/D4/D7-style regression
checks. It scans the delivery path (``services/delivery/**`` +
``services/notification_intelligence/**``) and fails when any of five unsafe
patterns appear:

  1. DIRECT_ADAPTER_DISPATCH — a provider adapter (``services/delivery/adapters/*``)
     is invoked outside the sanctioned pipeline. The only places allowed to call
     ``.dispatch(...)`` on an adapter are ``services/delivery/worker.py`` (the
     durable DeliveryWorker) and ``services/notification_intelligence/delivery_router.py``
     (the notification router); the adapters directory itself is exempt for
     internal delegation (marketing -> webhook, ticketing -> linear/jira, ...).
     Any other caller bypasses the queue/lease/retry/receipt pipeline and risks
     unmanaged, unreconciled outbound sends.

  2. FIRE_AND_FORGET_TASK — ``asyncio.create_task`` / ``loop.create_task`` /
     ``asyncio.ensure_future`` on delivery-critical work with no handle stored
     and no ``await``/``cancel``. Such a task can be silently dropped at
     shutdown, losing a notification. A stored handle that is later awaited or
     cancelled (e.g. the DeliveryWorker's poll loop) is fine; a task managed by
     ``asyncio.gather`` is fine; an inline ``await`` is fine.

  3. UNCONFIGURED_ROUTER — a route/deliver/dispatch function returns a success
     result without ever referencing a channel/recipient configuration. That is
     a silent no-op that looks like success (nothing was contacted).

  4. ZERO_CHANNEL_SUCCESS — a delivery returns success on an empty
     channel/recipient branch (``if not channels: return success``). This
     violates the program's "no zero-channel false success" invariant — the
     correct behaviour is to return an empty result / failure / raise so the
     unknown stays unknown.

  5. SIMULATED_PROVIDER_RECEIPT — a provider-shaped local fake or simulator is
     produced as a receipt without an environment guard. Provider fakes are only
     legitimate behind ``settings.env in (LOCAL, DEV)`` / ``_guard_fake()``; a
     fake must fail closed outside local/dev. Literal ``sim-`` ids are rejected
     by ``AdapterReceipt`` at runtime, so a construction with one here is a
     deliberate bypass of the honesty contract.

Detection is AST-based (never imports backend code) and deliberately
conservative so legitimate uses — ``asyncio.gather`` in the router, the worker's
stored + awaited poll-loop task, adapter-to-adapter delegation, the env-guarded
provider fake in ``_notification_base.py`` — do not raise false positives.

Usage: python scripts/release/validate_delivery_safety.py
"""
from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, main_guard, repo_root  # noqa: E402

_BACKEND_REL = Path("Backend Architecture") / "aether-backend"

# Scan scope: the delivery path and the notification intelligence delivery path.
SCAN_SUBTREES = ("services/delivery", "services/notification_intelligence")

ADAPTERS_PKG = "services.delivery.adapters"
ADAPTERS_DIR = "services/delivery/adapters/"

# The only files sanctioned to invoke a provider adapter's ``dispatch``. The
# worker owns the durable queue/lease/receipt pipeline; the router owns the
# per-channel notification fan-out. Everything else must go through one of them.
SANCTIONED_DISPATCH_FILES = frozenset({
    "services/delivery/worker.py",
    "services/notification_intelligence/delivery_router.py",
})

# Success-result types the detectors reason about.
RESULT_TYPES = frozenset({"DeliveryResult", "AdapterReceipt", "ProviderReceipt"})

# Router-ish method/function names whose success results must be configuration-backed.
ROUTER_FUNC_NAMES = frozenset({"route", "deliver", "dispatch", "_deliver_one", "send", "notify"})

# Identifiers that count as "configuration / recipient / destination present".
CONFIG_TOKENS = frozenset({
    "channel", "channels", "recipient", "recipients", "url", "chat_id", "to",
    "target", "targets", "webhook", "token", "device_token", "address", "config",
    "provider_config", "channel_config", "notification", "payload", "credential",
    "credentials", "channel_type", "eligible", "destination", "endpoint", "secret",
})

# Markers that prove a fake/simulator producer is guarded to local/dev only.
ENV_GUARD_MARKERS = (
    "settings.env",
    "Environment.LOCAL",
    "Environment.DEV",
    "_fake_allowed",
    "_guard_fake",
    "_is_local_development",
    "AETHER_ENV",
)

# Human-readable guidance per pattern, used in every violation report.
_PATTERN_DOCS: dict[str, tuple[str, str]] = {
    "DIRECT_ADAPTER_DISPATCH": (
        "a provider adapter is invoked outside the delivery worker/router pipeline — "
        "this bypasses the queue, lease, retry and durable-receipt path",
        "route the send through the DeliveryWorker queue or DeliveryRouter instead of "
        "calling the adapter directly",
    ),
    "FIRE_AND_FORGET_TASK": (
        "a delivery/notification-critical coroutine is scheduled without a stored handle "
        "that is awaited or cancelled — the task is silently dropped at shutdown",
        "store the task on an instance/name and await or cancel it in the shutdown path, "
        "or await it inline / run it under asyncio.gather",
    ),
    "UNCONFIGURED_ROUTER": (
        "a route/deliver/dispatch function returns a success result without referencing any "
        "channel/recipient configuration — a silent no-op that looks like success",
        "verify the channel/recipient/destination configuration (and fail closed) before "
        "returning a success result",
    ),
    "ZERO_CHANNEL_SUCCESS": (
        "a delivery returns success on an empty channel/recipient branch — the "
        "'no zero-channel false success' invariant",
        "return an empty result, a failure result, or raise when no channels/recipients "
        "are configured — never report success for zero contacts",
    ),
    "SIMULATED_PROVIDER_RECEIPT": (
        "a provider-shaped local fake / simulator receipt is produced without an "
        "environment guard — it must fail closed outside local/dev",
        "guard fake/simulator receipt production behind settings.env in (LOCAL, DEV) "
        "(e.g. _guard_fake()) so it is impossible in staging/production",
    ),
}


@dataclass(frozen=True)
class Violation:
    """One unsafe delivery pattern occurrence."""

    pattern: str
    rel_path: str
    lineno: int
    why: str
    fix: str


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _expr_str(node: Optional[ast.AST]) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return ""


def _root_name(node: ast.AST) -> str:
    """The bottom-most Name of an attribute chain (``self._registry`` -> ``self``)."""
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    if isinstance(cur, ast.Name):
        return cur.id
    return ""


def _build_parent_map(tree: ast.Module) -> dict[int, Optional[ast.AST]]:
    parents: dict[int, Optional[ast.AST]] = {}

    def visit(node: ast.AST, parent: Optional[ast.AST]) -> None:
        parents[id(node)] = parent
        for child in ast.iter_child_nodes(node):
            visit(child, node)

    visit(tree, None)
    return parents


def _imported_names(tree: ast.Module) -> dict[str, set[str]]:
    """``{module: {imported names}}`` for every import in the module."""
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = {a.asname or a.name for a in node.names}
            out.setdefault(node.module, set()).update(names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                out.setdefault(a.name, set()).add(a.asname or a.name.rsplit(".", 1)[-1])
    return out


def _adapter_imported_names(imports: dict[str, set[str]]) -> set[str]:
    """Names imported from ``services.delivery.adapters`` (classes/instances)."""
    names: set[str] = set()
    for mod, module_names in imports.items():
        if mod == ADAPTERS_PKG or mod.startswith(ADAPTERS_PKG + "."):
            names.update(module_names)
    return names


def _is_empty_check(test: ast.AST) -> bool:
    """True for emptiness-style tests: ``not X``, ``X == []``, ``len(X) == 0``,
    ``X == ""``, ``X is None``. Positive guards (``if channels:``) are excluded —
    success on a *non-empty* guard is legitimate."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return True
    if isinstance(test, ast.Compare):
        for op, comp in zip(test.ops, test.comparators):
            if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(comp, ast.Constant) \
                    and comp.value is None:
                return True
            if isinstance(op, ast.Eq):
                if isinstance(comp, (ast.List, ast.Tuple)) and not comp.elts:
                    return True
                if isinstance(comp, ast.Constant) and comp.value in (0, "", False):
                    return True
            if isinstance(op, ast.Lt) and isinstance(comp, ast.Constant) \
                    and comp.value == 1:
                return True
    return False


def _result_success_literal(call: ast.Call) -> Optional[bool]:
    """Whether a DeliveryResult construction declares ``success=True``/``False``
    as a constant, or None when it is derived (a Name/expression)."""
    for kw in call.keywords:
        if kw.arg == "success" and isinstance(kw.value, ast.Constant):
            return bool(kw.value.value)
    # DeliveryResult(success, channel_type, ...) as positional #0.
    if call.args and isinstance(call.args[0], ast.Constant):
        return bool(call.args[0].value)
    return None


def _enclosing_function_def(node: ast.AST, parents: dict[int, Optional[ast.AST]]) -> Optional[ast.FunctionDef]:
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur
        cur = parents.get(id(cur))
    return None


def _func_source_lines(node: ast.AST, tree: ast.Module) -> list[str]:
    try:
        return ast.get_source_segment(_src_for(tree), node).splitlines()
    except Exception:  # pragma: no cover - defensive
        return []


def _src_for(_tree: ast.Module) -> str:
    return getattr(_tree, "_source", "")


def _env_guarded(func: Optional[ast.FunctionDef], tree: ast.Module) -> bool:
    if func is None:
        return False
    segment = ast.get_source_segment(_src_for(tree), func) or ""
    return any(marker in segment for marker in ENV_GUARD_MARKERS)


def _is_fake_named(name: str) -> bool:
    lowered = name.lower()
    return ("fake" in lowered) or ("sim" in lowered)


# ---------------------------------------------------------------------------
# Pattern 1 — direct adapter dispatch outside the worker/router pipeline
# ---------------------------------------------------------------------------

def _receiver_reaches_adapter(receiver: ast.AST, adapter_names: set[str]) -> bool:
    """Heuristic: does the receiver of a ``.dispatch(...)`` call reach a
    provider adapter (imported name, adapter instantiation, or registry get)?"""
    if isinstance(receiver, ast.Name):
        return receiver.id in adapter_names
    if isinstance(receiver, ast.Call):
        inner = receiver.func
        if isinstance(inner, ast.Name):
            return inner.id in adapter_names
        if isinstance(inner, ast.Attribute) and inner.attr in ("get", "get_or_raise", "default"):
            expr = _expr_str(inner.value)
            return ("registry" in expr.lower()) or ("adapter" in expr.lower())
    if isinstance(receiver, ast.Attribute):
        return _root_name(receiver) in adapter_names or receiver.attr in adapter_names
    return False


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in target.elts:
            out.extend(_target_names(elt))
        return out
    return []


def _adapter_reaching_names(tree: ast.Module) -> set[str]:
    """Names that provably hold a provider adapter: imported adapter names plus
    names assigned from an adapter instantiation or registry get (``adapter =
    ProviderAdapterRegistry.default().get_or_raise(...)``). Fixed-point over a
    few passes so chained aliases resolve too."""
    imports = _imported_names(tree)
    reaching = set(_adapter_imported_names(imports))
    for _ in range(3):
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and node.value is not None:
                if _receiver_reaches_adapter(node.value, reaching):
                    for t in node.targets:
                        for name in _target_names(t):
                            if name not in reaching:
                                reaching.add(name)
                                changed = True
            elif isinstance(node, ast.AnnAssign) and node.value is not None \
                    and isinstance(node.target, ast.Name) \
                    and _receiver_reaches_adapter(node.value, reaching) \
                    and node.target.id not in reaching:
                reaching.add(node.target.id)
                changed = True
        if not changed:
            break
    return reaching


def _detect_direct_adapter_dispatch(rel_path: str, tree: ast.Module) -> list[Violation]:
    reaching = _adapter_reaching_names(tree)
    if not reaching:
        return []
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "dispatch":
            continue
        if _receiver_reaches_adapter(func.value, reaching):
            why, fix = _PATTERN_DOCS["DIRECT_ADAPTER_DISPATCH"]
            violations.append(Violation(
                pattern="DIRECT_ADAPTER_DISPATCH",
                rel_path=rel_path,
                lineno=node.lineno,
                why=why,
                fix=fix,
            ))
    return violations


# ---------------------------------------------------------------------------
# Pattern 2 — fire-and-forget task scheduling on delivery-critical work
# ---------------------------------------------------------------------------

def _is_task_creator(node: ast.Call, asyncio_names: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in ("create_task", "ensure_future"):
        base = func.value
        if isinstance(base, ast.Name) and base.id == "asyncio":
            return True
        root = _root_name(base)
        if "loop" in root.lower():
            return True
        # get_event_loop()/asyncio.get_running_loop().create_task(...)
        if isinstance(base, ast.Call):
            inner = base.func
            inner_str = _expr_str(inner)
            if "loop" in inner_str.lower():
                return True
        return False
    if isinstance(func, ast.Name) and func.id in ("create_task", "ensure_future") \
            and func.id in asyncio_names:
        return True
    return False


def _is_gather_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "gather"
    if isinstance(func, ast.Name):
        return func.id == "gather"
    return False


def _managed_by_gather(node: ast.AST, parents: dict[int, Optional[ast.AST]]) -> bool:
    """True when the created task sits inside a gather call's argument tree
    (``asyncio.gather(asyncio.create_task(f()), ...)`` or ``*[...]`` builds)."""
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, ast.Call):
            return _is_gather_call(cur)
        if isinstance(cur, ast.stmt):
            return False
        cur = parents.get(id(cur))
    return False


def _expr_awaited_or_cancelled(tree: ast.Module, target: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Await):
            if _expr_str(node.value) == target:
                return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "cancel":
            if _expr_str(node.func.value) == target:
                return True
    return False


def _passed_to_gather(tree: ast.Module, target: str) -> bool:
    """True when ``target`` is referenced (directly, starred, or inside a list
    literal) as an argument to ``asyncio.gather`` — the collection's tasks are
    awaited by the gather."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_gather_call(node):
            continue
        for arg in node.args:
            if _expr_str(arg) == target:
                return True
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Name) and sub.id == target:
                    return True
                if isinstance(sub, ast.Attribute) and _expr_str(sub) == target:
                    return True
    return False


# Collection/comprehension nodes a create_task result may sit inside before
# reaching its storage statement (``tasks = [asyncio.create_task(...) ...]``,
# ``tasks.append(...)``, ``asyncio.gather(*[...])``).
_TRANSPARENT_COLLECTIONS = (
    ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Starred, ast.comprehension,
)


def _storage_context(node: ast.AST, parents: dict[int, Optional[ast.AST]]) -> Optional[ast.AST]:
    """The statement-level context (Assign / AnnAssign / Call(append) / Expr / ...)
    that owns the created task, climbing out of collection/comprehension wrappers."""
    ctx = parents.get(id(node))
    while ctx is not None and isinstance(ctx, _TRANSPARENT_COLLECTIONS):
        ctx = parents.get(id(ctx))
    return ctx


def _task_managed(node: ast.Call, parents: dict[int, Optional[ast.AST]],
                  tree: ast.Module) -> tuple[bool, str]:
    """Classify a create_task/ensure_future call: is the task's handle retained
    and eventually awaited/cancelled/gathered, or silently dropped?"""
    ctx = _storage_context(node, parents)

    if isinstance(ctx, ast.Await):
        return True, "awaited inline"

    if _managed_by_gather(node, parents):
        return True, "managed by asyncio.gather"

    if isinstance(ctx, (ast.Assign, ast.AnnAssign)):
        targets = ctx.targets if isinstance(ctx, ast.Assign) else [ctx.target]
        stored = [t for t in targets if _expr_str(t)]
        if not stored:
            return False, "task result stored without a nameable handle"
        for t in stored:
            t_str = _expr_str(t)
            if _expr_awaited_or_cancelled(tree, t_str) or _passed_to_gather(tree, t_str):
                return True, f"handle {t_str!r} stored and later awaited/cancelled/gathered"
        return False, "handle stored but never awaited, cancelled or gathered — " \
                      "silently dropped at shutdown"

    if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute) \
            and ctx.func.attr == "append":
        # tasks.append(asyncio.create_task(...)) — the handle lives in the
        # collection; it is managed only if that collection is gathered/awaited.
        handle = _expr_str(ctx.func.value)
        if handle and (_expr_awaited_or_cancelled(tree, handle) or _passed_to_gather(tree, handle)):
            return True, f"collection {handle!r} later gathered"
        return False, "task appended to a collection that is never gathered/awaited"

    if isinstance(ctx, ast.Expr):
        return False, "fire-and-forget: task result discarded, not stored or awaited"

    return False, "task created without a managed handle"


def _detect_fire_and_forget(rel_path: str, tree: ast.Module) -> list[Violation]:
    imports = _imported_names(tree)
    asyncio_names = imports.get("asyncio", set())
    parents = _build_parent_map(tree)
    why, fix = _PATTERN_DOCS["FIRE_AND_FORGET_TASK"]
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_task_creator(node, asyncio_names):
            continue
        managed, detail = _task_managed(node, parents, tree)
        if not managed:
            violations.append(Violation(
                pattern="FIRE_AND_FORGET_TASK", rel_path=rel_path,
                lineno=node.lineno, why=f"{why} ({detail})", fix=fix,
            ))
    return violations


# ---------------------------------------------------------------------------
# Patterns 3 & 4 — silent success (no configuration referenced / zero channels)
# ---------------------------------------------------------------------------

def _is_success_result(call: ast.Call) -> bool:
    """A DeliveryResult with truthy success, or an AdapterReceipt/ProviderReceipt
    (which by construction claims a real delivery happened)."""
    if not isinstance(call.func, ast.Name):
        return False
    if call.func.id not in RESULT_TYPES:
        return False
    if call.func.id == "DeliveryResult":
        return _result_success_literal(call) is True
    return True


def _returns_success(return_value: ast.AST) -> bool:
    if isinstance(return_value, ast.Call):
        return _is_success_result(return_value)
    if isinstance(return_value, (ast.List, ast.Tuple)):
        return any(isinstance(elt, ast.Call) and _is_success_result(elt)
                   for elt in return_value.elts)
    return False


def _body_references_config(func: ast.AST) -> bool:
    """Whether the function's statements reference any channel/recipient/destination
    configuration (as a name or attribute) — excluding the parameter list itself,
    so a ``deliver(self, notification, config, credentials)`` that never touches
    ``config`` is correctly treated as unconfigured."""
    for stmt in func.body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name) and n.id in CONFIG_TOKENS:
                return True
            if isinstance(n, ast.Attribute) and n.attr in CONFIG_TOKENS:
                return True
    return False


def _iter_returns(func: ast.AST):
    for node in ast.walk(func):
        if isinstance(node, ast.Return):
            yield node


def _detect_unconfigured_router(rel_path: str, tree: ast.Module) -> list[Violation]:
    why, fix = _PATTERN_DOCS["UNCONFIGURED_ROUTER"]
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in ROUTER_FUNC_NAMES:
            continue
        if _body_references_config(node):
            continue
        for ret in _iter_returns(node):
            if ret.value is not None and _returns_success(ret.value):
                violations.append(Violation(
                    pattern="UNCONFIGURED_ROUTER", rel_path=rel_path,
                    lineno=ret.lineno, why=why, fix=fix,
                ))
    return violations


def _detect_zero_channel_success(rel_path: str, tree: ast.Module) -> list[Violation]:
    why, fix = _PATTERN_DOCS["ZERO_CHANNEL_SUCCESS"]
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not _is_empty_check(node.test):
            continue
        test_names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if not (test_names & CONFIG_TOKENS):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Return) and stmt.value is not None \
                    and _returns_success(stmt.value):
                violations.append(Violation(
                    pattern="ZERO_CHANNEL_SUCCESS", rel_path=rel_path,
                    lineno=stmt.lineno, why=why, fix=fix,
                ))
    return violations


# ---------------------------------------------------------------------------
# Pattern 5 — simulated / provider-shaped fake receipts without an env guard
# ---------------------------------------------------------------------------

def _receipt_external_id_literal(call: ast.Call) -> Optional[str]:
    """The literal string used as ``external_id``, or None if derived."""
    ext: Optional[ast.AST] = None
    for kw in call.keywords:
        if kw.arg == "external_id":
            ext = kw.value
            break
    if ext is None and call.args:
        ext = call.args[0]
    if isinstance(ext, ast.Constant) and isinstance(ext.value, str):
        return ext.value
    return None


def _looks_like_fake_id(value: str) -> bool:
    """Fake/simulator-shaped external_id. ``"fake"`` here is a strong signal
    because we only reach it for *literal* external_ids that already sit in a
    receipt construction — a legit provider never mints a fake id."""
    lowered = value.lower()
    return ("sim-" in lowered) or ("-local-" in lowered) or ("@fake." in lowered) \
        or ("fake" in lowered) or (lowered.startswith("sim"))


def _detect_simulated_receipts(rel_path: str, tree: ast.Module) -> list[Violation]:
    parents = _build_parent_map(tree)
    why, fix = _PATTERN_DOCS["SIMULATED_PROVIDER_RECEIPT"]
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id not in RESULT_TYPES:
            continue
        literal_id = _receipt_external_id_literal(node)
        enclosing = _enclosing_function_def(node, parents)
        fake_producer = enclosing is not None and _is_fake_named(enclosing.name)
        if literal_id is not None and _looks_like_fake_id(literal_id):
            if enclosing is not None and _env_guarded(enclosing, tree):
                continue  # env-guarded fake is the sanctioned local/dev posture
            violations.append(Violation(
                pattern="SIMULATED_PROVIDER_RECEIPT", rel_path=rel_path,
                lineno=node.lineno, why=why, fix=fix,
            ))
            continue
        if fake_producer and not _env_guarded(enclosing, tree):
            violations.append(Violation(
                pattern="SIMULATED_PROVIDER_RECEIPT", rel_path=rel_path,
                lineno=node.lineno, why=why,
                fix=fix + " (a fake-named receipt producer must be env-guarded)",
            ))
    return violations


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def analyze(rel_path: str, source: str) -> list[Violation]:
    """Analyse one file's source (relative to the backend root). Pure function —
    the unit tests drive this directly with inline fixture strings."""
    rel_path = rel_path.replace("\\", "/")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    setattr(tree, "_source", source)

    violations: list[Violation] = []

    # Pattern 1 applies only outside the sanctioned pipeline and adapter internals
    # (marketing -> webhook, ticketing -> linear/jira delegation is legitimate).
    if rel_path not in SANCTIONED_DISPATCH_FILES \
            and not rel_path.startswith(ADAPTERS_DIR):
        violations.extend(_detect_direct_adapter_dispatch(rel_path, tree))

    violations.extend(_detect_fire_and_forget(rel_path, tree))
    violations.extend(_detect_unconfigured_router(rel_path, tree))
    violations.extend(_detect_zero_channel_success(rel_path, tree))
    violations.extend(_detect_simulated_receipts(rel_path, tree))
    return violations


PATTERN_ORDER = (
    "DIRECT_ADAPTER_DISPATCH",
    "FIRE_AND_FORGET_TASK",
    "UNCONFIGURED_ROUTER",
    "ZERO_CHANNEL_SUCCESS",
    "SIMULATED_PROVIDER_RECEIPT",
)


def run(root: Path) -> int:
    r = Reporter("DELIVERY SAFETY — unsafe delivery patterns fail the build")
    backend = root / _BACKEND_REL
    all_violations: list[Violation] = []
    scanned_files = 0
    for subtree in SCAN_SUBTREES:
        base = backend / subtree
        if not base.exists():
            continue
        for py in sorted(base.rglob("*.py")):
            rel = py.relative_to(backend).as_posix()
            all_violations.extend(analyze(rel, py.read_text(encoding="utf-8")))
            scanned_files += 1

    by_pattern: dict[str, list[Violation]] = {}
    for v in all_violations:
        by_pattern.setdefault(v.pattern, []).append(v)

    for pattern in PATTERN_ORDER:
        found = by_pattern.get(pattern, [])
        if not found:
            r.ok(f"{pattern}: no unsafe delivery patterns detected")
            continue
        for v in found:
            print(f"    ✗ {v.rel_path}:{v.lineno}  {v.pattern}")
            print(f"        why: {v.why}")
            print(f"        fix: {v.fix}")
        r.fail(f"{pattern}: {len(found)} violation(s)")

    r.require(scanned_files > 0,
              f"scanned {scanned_files} delivery-path files",
              "no delivery-path files found to scan")
    return r.finish()


def main() -> int:
    return run(repo_root())


if __name__ == "__main__":
    main_guard(main)
