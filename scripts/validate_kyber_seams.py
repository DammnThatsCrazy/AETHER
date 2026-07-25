#!/usr/bin/env python3
"""Prove every declared Kyber cross-package seam still resolves.

Kyber's packages call each other through function-level imports guarded by
``try/except ImportError``, so one plane being unavailable degrades that plane
instead of failing the request. The cost of that guard is that a *wrong* module
path or symbol name looks exactly like an absent one — a broken integration
reports success and each side's own tests stay green.

Two defects shipped that way in the first Kyber release: offboarding silently
skipped device and scope revocation because it imported a module that does not
exist, and Kyber access decisions never reached ``security_policy_decisions``
because the call passed seven keyword arguments the target does not accept.

This gate imports each declared target and introspects it for real:

  1. the module imports,
  2. the singleton (when declared) exists on it,
  3. the attribute exists and is callable,
  4. every keyword the caller passes is accepted by the signature, and
  5. the positional arity the caller relies on is available.

A rename now fails CI instead of degrading in production. The declaration lives
in ``services/kyber/seams.py`` — one entry per cross-package call.

Note on ``optional``: a seam marked optional means the *caller* tolerates the
plane being absent. It does not weaken this gate. If the module imports, the
target must be correct — tolerating absence must never mask a typo.
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "seam-validator")
sys.path.insert(0, str(BACKEND))

FAILURES: list[str] = []
CHECKED = 0


def fail(seam, message: str) -> None:
    FAILURES.append(f"{seam.caller}\n      -> {message}")


def _accepts(sig: inspect.Signature, keyword: str) -> bool:
    """True when the signature accepts ``keyword`` by name."""
    for name, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True  # **kwargs swallows anything
        if name == keyword and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            return True
    return False


def _positional_capacity(sig: inspect.Signature) -> int:
    """How many positional arguments the callable accepts (``self`` excluded)."""
    count = 0
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            return 1_000
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            count += 1
    return count


def check(seam) -> None:
    global CHECKED
    import importlib

    try:
        module = importlib.import_module(seam.module)
    except ImportError as exc:
        # `optional` describes whether the CALLER degrades gracefully when the
        # plane is missing at runtime. It never excuses a module that does not
        # exist: every declared seam names a module inside this repository, so
        # an ImportError here means the declaration is wrong or the module was
        # renamed — which is exactly the defect this gate exists to catch.
        # An earlier revision of this validator let optional seams skip on
        # ImportError and consequently MISSED the very defect it was written
        # for (offboarding importing `devices.service`, which never existed).
        fail(
            seam,
            f"module {seam.module!r} does not import: {exc}. "
            f"A declared seam must name a real module — `optional` covers "
            f"runtime unavailability, not a wrong path.",
        )
        return

    target_owner = module
    if seam.singleton is not None:
        target_owner = getattr(module, seam.singleton, None)
        if target_owner is None:
            available = sorted(
                n for n in dir(module) if n.endswith("_service") and not n.startswith("_")
            )
            fail(
                seam,
                f"{seam.module}.{seam.singleton} does not exist. "
                f"Singletons actually exported: {available or 'none'}",
            )
            return

    target = getattr(target_owner, seam.attribute, None)
    if target is None:
        owner_label = f"{seam.module}.{seam.singleton}" if seam.singleton else seam.module
        available = sorted(
            n for n in dir(target_owner) if not n.startswith("_") and callable(getattr(target_owner, n, None))
        )
        fail(
            seam,
            f"{owner_label}.{seam.attribute} does not exist. "
            f"Callables actually available: {available or 'none'}",
        )
        return

    if not callable(target):
        fail(seam, f"{seam.attribute} is not callable")
        return

    try:
        sig = inspect.signature(target)
    except (TypeError, ValueError):  # builtins / C-implemented callables
        CHECKED += 1
        return

    for keyword in seam.keywords:
        if not _accepts(sig, keyword):
            fail(
                seam,
                f"{seam.attribute}{sig} does not accept keyword {keyword!r} "
                f"— the caller passes it",
            )

    capacity = _positional_capacity(sig)
    if seam.positional > capacity:
        fail(
            seam,
            f"{seam.attribute}{sig} accepts {capacity} positional argument(s) "
            f"but the caller passes {seam.positional}",
        )

    CHECKED += 1


def main() -> int:
    try:
        from services.kyber.seams import SEAMS
    except ImportError as exc:
        print(f"FAIL — services/kyber/seams.py is not importable: {exc}")
        return 1

    print("=" * 70)
    print("  Kyber cross-package seam integrity")
    print("=" * 70)

    for seam in SEAMS:
        check(seam)

    print(f"  seams declared: {len(SEAMS)}   verified: {CHECKED}")
    print("-" * 70)

    if FAILURES:
        print(f"  RESULT: FAIL — {len(FAILURES)} broken seam(s)\n")
        for failure in FAILURES:
            print(f"    ✗ {failure}")
        print(
            "\n  A seam breaks when a target is renamed or its signature changes "
            "without\n  the caller following. Because Kyber's cross-package calls are "
            "guarded by\n  try/except ImportError, this would otherwise degrade "
            "silently at runtime\n  rather than failing here. Fix the caller, or update "
            "services/kyber/seams.py\n  if the seam legitimately moved."
        )
        print("=" * 70)
        return 1

    print("  RESULT: PASS — every declared seam resolves and accepts its arguments")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
