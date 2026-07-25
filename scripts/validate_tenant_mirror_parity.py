#!/usr/bin/env python3
"""Prove the Kyber Tenant Mirror still cannot recompute a tenant-visible value.

The mirror rests on one invariant: the tenant-visible result Aether returns for
a tenant, query and contract version is *the same* result the Tenant Mirror
returns. Kyber may add operator diagnostics; it may never derive a tenant-visible
number of its own. If it did, an operator investigating a tenant would be
debugging a second implementation of the tenant's product.

That invariant is only structural if the mirror package owns no calculations,
and "owns no calculations" is only enforceable if something checks. Three things
are checked here:

  1. **Coverage, both directions.** Every ``tenant_parity_required`` surface in
     ``packages/shared/contracts/kyber-feature-surface-manifest.json`` must have
     a resolver in ``SURFACE_VERTEX_TYPES``, and nothing else may. A coverage map
     that silently stops covering a surface is worse than no map: the surface
     still renders, it just renders unwatched.

  2. **Imports.** Every import in ``services/kyber/mirror/*.py`` is matched
     against a positive, shrink-only allowlist. Importing anything that derives
     a value — a calculator, the graph client, a product service — fails here
     rather than in production. The allowlist is shrink-only in both senses: an
     import outside it is an error, and a first-party entry that nothing imports
     any more is *also* an error, because a stale allowance is how the next
     forbidden import gets waved through.

  3. **Presentation keys.** ``PRESENTATION_KEYS`` names the keys stripped before
     digesting. Every one must carry a stated reason, and none may collide with
     a key that carries a tenant-observable value — a mis-listed key makes the
     digest agree while the tenant sees a difference, which is a false PASS on
     the one thing this gate exists to prove.

The check is deliberately not "does the mirror produce the right numbers". It
cannot: the numbers come from the tenant's own data. What it can prove is that
the mirror has no way to produce numbers at all.
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
MIRROR = BACKEND / "services" / "kyber" / "mirror"
MANIFEST = ROOT / "packages" / "shared" / "contracts" / "kyber-feature-surface-manifest.json"

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "tenant-mirror-validator")
sys.path.insert(0, str(BACKEND))

FAILURES: list[str] = []

#: Module prefixes the mirror package may import. Positive rather than negative
#: on purpose: a forbidden-prefix list has to predict every calculation module
#: anyone will ever write, and it is wrong the first time someone writes a new
#: one. This list is small enough to read, and every entry is justified.
ALLOWED_IMPORT_PREFIXES: tuple[str, ...] = (
    # Intra-package. The mirror's own contracts, parity and service.
    "services.kyber.mirror",
    # The ONLY sanctioned path into a tenant's own data.
    "services.kyber.graph.scoped_gateway",
    # Authorization vocabulary. Constants and enums; decides nothing here.
    "services.kyber.access.capabilities",
    "services.kyber.access.disclosure",
    "services.kyber.access.dependencies",
    # Shared primitives: response envelope, errors, logging, clock.
    "shared.common.common",
    "shared.logger.logger",
    # The canonical instant parser. Timestamp normalisation must not be
    # reimplemented, or "equal" would mean something different here.
    "shared.temporal.instant",
    # Value-state *vocabulary* only — the enum, never the calculators in
    # shared.measurement.compute / registry / uncertainty / sufficiency.
    "shared.measurement.value_states",
)

#: Prefixes whose staleness is checked. Third-party and stdlib churn for
#: reasons that have nothing to do with this invariant, so only first-party
#: allowances have to earn their place.
SHRINK_ONLY_PREFIXES: tuple[str, ...] = tuple(
    p for p in ALLOWED_IMPORT_PREFIXES if p.startswith(("services.", "shared."))
)

#: Third-party and stdlib roots the package may use. No calculation lives here.
ALLOWED_ROOTS: frozenset[str] = frozenset({
    "__future__", "ast", "dataclasses", "datetime", "decimal", "enum",
    "functools", "hashlib", "json", "pathlib", "re", "typing", "uuid",
    "fastapi", "pydantic",
})

#: Named for the error message only. An import matching one of these is not
#: merely outside the allowlist — it is a calculation, and saying so makes the
#: failure self-explanatory.
CALCULATION_PREFIXES: tuple[str, ...] = (
    "shared.measurement.compute",
    "shared.measurement.registry",
    "shared.measurement.sufficiency",
    "shared.measurement.uncertainty",
    "shared.measurement.restatement",
    "shared.graph.graph",
    "repositories.",
    "services.analytics",
    "services.metrics",
)

#: Keys that carry a tenant-observable value and may never be stripped before
#: digesting. Kept here as well as in ``parity.py`` so the gate does not depend
#: on the module it is gating to define its own escape hatch.
NEVER_PRESENTATION: frozenset[str] = frozenset({
    "amount", "balance", "count", "created_at", "currency", "email", "id",
    "name", "occurred_at", "score", "state", "status", "timestamp", "total",
    "truncated", "updated_at", "value", "vertex_id", "vertex_type",
})


def fail(check: str, message: str) -> None:
    FAILURES.append(f"{check}\n      -> {message}")


# ── 1. Coverage ──────────────────────────────────────────────────────────────


def check_coverage(surface_vertex_types: dict) -> int:
    if not MANIFEST.is_file():
        fail("coverage", f"manifest missing: {MANIFEST}")
        return 0
    manifest = json.loads(MANIFEST.read_text())
    required = {
        str(entry.get("feature_id"))
        for entry in manifest.get("surfaces", [])
        if entry.get("tenant_parity_required")
    }
    declared = set(surface_vertex_types)

    for feature_id in sorted(required - declared):
        fail(
            "coverage",
            f"manifest surface {feature_id!r} requires tenant parity but "
            f"SURFACE_VERTEX_TYPES declares no resolver for it — the surface "
            f"would render unwatched",
        )
    for feature_id in sorted(declared - required):
        fail(
            "coverage",
            f"SURFACE_VERTEX_TYPES declares {feature_id!r}, which is not a "
            f"parity-required manifest surface — stale coverage, remove it or "
            f"regenerate the manifest",
        )
    for feature_id, types in sorted(surface_vertex_types.items()):
        if not types:
            fail(
                "coverage",
                f"{feature_id!r} declares an empty vertex-type tuple; an empty "
                f"resolver reads to an operator as an empty tenant",
            )
    return len(required)


def check_augmentations(diagnostic_sections: tuple) -> None:
    """The five diagnostic sections must be exactly what the manifest declares."""
    if not MANIFEST.is_file():
        return
    manifest = json.loads(MANIFEST.read_text())
    for entry in manifest.get("surfaces", []):
        if not entry.get("tenant_parity_required"):
            continue
        declared = tuple(entry.get("operator_augmentations") or ())
        if declared != tuple(diagnostic_sections):
            fail(
                "diagnostics",
                f"{entry.get('feature_id')!r} declares operator_augmentations "
                f"{list(declared)} but DIAGNOSTIC_SECTIONS is "
                f"{list(diagnostic_sections)} — the envelope and the manifest "
                f"must name the same sections",
            )
            return  # one report is enough; they are generated identically


# ── 2. Imports ───────────────────────────────────────────────────────────────


def _imported_modules(path: Path) -> list[tuple[str, int]]:
    """Every module named by an import in one file, with its line number.

    Relative imports are resolved against the mirror package so that
    ``from ..graph.scoped_gateway import ...`` is checked as the absolute path
    it actually resolves to, not waved through as a bare name.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    package = "services.kyber.mirror"
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)]) if node.level > 1 else package
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            found.append((module, node.lineno))
    return found


def check_imports() -> tuple[int, set[str]]:
    used_prefixes: set[str] = set()
    scanned = 0
    for path in sorted(MIRROR.glob("*.py")):
        scanned += 1
        for module, lineno in _imported_modules(path):
            if not module:
                continue
            root = module.split(".")[0]
            if root in ALLOWED_ROOTS:
                continue
            match = next(
                (p for p in ALLOWED_IMPORT_PREFIXES if module == p or module.startswith(f"{p}.")),
                None,
            )
            if match is not None:
                used_prefixes.add(match)
                continue
            calculation = any(module.startswith(p) for p in CALCULATION_PREFIXES)
            fail(
                "imports",
                f"{path.name}:{lineno} imports {module!r}, which is "
                + (
                    "a calculation module. "
                    if calculation
                    else "outside the mirror's allowlist. "
                )
                + "The mirror owns no calculations: read tenant data through "
                "services.kyber.graph.scoped_gateway and call the existing "
                "shared code for anything derived.",
            )
    return scanned, used_prefixes


def check_stale_allowances(used_prefixes: set[str]) -> None:
    for prefix in SHRINK_ONLY_PREFIXES:
        if prefix not in used_prefixes:
            fail(
                "imports",
                f"allowlist entry {prefix!r} is not imported by any module in "
                f"services/kyber/mirror — a stale allowance is how the next "
                f"forbidden import gets waved through. Remove it.",
            )


# ── 3. Presentation keys ─────────────────────────────────────────────────────


def check_presentation_keys(keys: frozenset, reasons: dict) -> None:
    for key in sorted(keys):
        reason = str(reasons.get(key) or "").strip()
        if not reason:
            fail(
                "presentation_keys",
                f"{key!r} is stripped before digesting with no stated reason — "
                f"a key without a reason is a value someone decided to stop "
                f"comparing",
            )
    for key in sorted(set(reasons) - set(keys)):
        fail(
            "presentation_keys",
            f"{key!r} has a reason but is not in PRESENTATION_KEYS — the two "
            f"must be derived from one another",
        )
    for key in sorted(keys & NEVER_PRESENTATION):
        fail(
            "presentation_keys",
            f"{key!r} carries a tenant-observable value and must never be "
            f"stripped; doing so makes the digest agree while the tenant sees "
            f"a difference",
        )


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 70)
    print("  Kyber Tenant Mirror — parity invariant")
    print("=" * 70)

    try:
        from services.kyber.mirror.contracts import DIAGNOSTIC_SECTIONS
        from services.kyber.mirror.parity import (
            PRESENTATION_KEY_REASONS,
            PRESENTATION_KEYS,
        )
        from services.kyber.mirror.service import SURFACE_VERTEX_TYPES
    except ImportError as exc:
        print(f"  RESULT: FAIL — services/kyber/mirror is not importable: {exc}")
        print("=" * 70)
        return 1

    required = check_coverage(SURFACE_VERTEX_TYPES)
    check_augmentations(DIAGNOSTIC_SECTIONS)
    scanned, used = check_imports()
    check_stale_allowances(used)
    check_presentation_keys(PRESENTATION_KEYS, PRESENTATION_KEY_REASONS)

    print(
        f"  parity-required surfaces: {required}   resolvers: "
        f"{len(SURFACE_VERTEX_TYPES)}   modules scanned: {scanned}   "
        f"presentation keys: {len(PRESENTATION_KEYS)}"
    )
    print("-" * 70)

    if FAILURES:
        print(f"  RESULT: FAIL — {len(FAILURES)} problem(s)\n")
        for failure in FAILURES:
            print(f"    ✗ {failure}")
        print(
            "\n  The Tenant Mirror must return the same tenant-visible value Aether\n"
            "  returns. Add the missing resolver, remove the calculation import, or\n"
            "  justify the presentation key — do not relax this gate to make it pass."
        )
        print("=" * 70)
        return 1

    print("  RESULT: PASS — the mirror covers every parity surface and owns no calculations")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
