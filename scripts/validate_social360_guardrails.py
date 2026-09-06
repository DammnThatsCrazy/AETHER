#!/usr/bin/env python3
"""Social360 static guardrails (repo-doctor gate, M12).

Closes G058 ("Static CI guardrails: validate_social360_contracts /
relationship_predicates / relationship_fidelity / social_provider_runtime"):
a lightweight, statically-checked gate that would have caught the M4-era
legacy-social honesty defects and the M1/M6 predicate-registration drift
classes *before* they reached the graph.

Checks (all fail-closed, no fabricated-pass path):
  1. Predicate-registry internal consistency:
     - every REGISTERED predicate declares a non-empty graphEdgeType;
     - graphEdgeType strings are unique across the registry.
  2. Predicate-registry <-> live graph honesty (mirrors the M1 parity tests at
     CI-gate level): every REGISTERED graphEdgeType must exist as a live
     shared.graph.graph.EdgeType member AND be present in
     shared.graph.relationship_layers._EDGE_LAYER_MAP. A predicate may not
     name an edge that the traversal/relation substrate does not actually know.
  3. No legacy fabricated-default / fixed-overlap idioms in the social code:
     ``followers = 0``, ``following_count = 0``, ``engagement_rate = 0``,
     ``influence(_level) = "low"``, ``audience_overlap = <fixed numeric>``,
     fixed overlap constants 0.20/0.15/0.25. String/comment tokens are
     stripped before matching so honest documentation (e.g. routes.py's own
     rules docstring) never self-triggers the gate.

The predicate registry is the canonical source; generated twins are regenerated
by the unified-platform generator and are NOT edited by this gate.

Exit code 0 = all checks pass (prints PASSED summary).
Exit code 1 = one or more errors (prints ERRORS, intended to fail ci).
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "Backend Architecture", "aether-backend")
REGISTRY = os.path.join(
    ROOT, "packages", "shared", "contracts", "relationship-predicate-registry.json"
)

# Social/legacy roots scanned for fabricated defaults / fixed overlap constants.
SCAN_ROOTS = [
    os.path.join(BACKEND, "services", "social"),
    os.path.join(BACKEND, "services", "silver"),
    os.path.join(BACKEND, "services", "exploration", "adapters", "social360.py"),
    os.path.join(BACKEND, "services", "relationship_fidelity"),
    os.path.join(BACKEND, "shared", "social360"),
]

ERRORS: list[str] = []
NOTES: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def _walk_py_files() -> list[str]:
    files: list[str] = []
    for root in SCAN_ROOTS:
        if not os.path.exists(root):
            NOTES.append(f"scan root absent (skipped): {os.path.relpath(root, ROOT)}")
            continue
        if os.path.isfile(root):
            files.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in filenames:
                if fn.endswith(".py"):
                    files.append(os.path.join(dirpath, fn))
    # Exclude test files: honesty fixes are exercised by tests that may
    # legitimately reference the forbidden legacy idioms as fixtures.
    return [f for f in files if "/tests/" not in f.replace("\\", "/")]


def _strip_strings_and_comments(src: str) -> str:
    """Reconstruct source without STRING/COMMENT tokens.

    Keeps code tokens (NAME/OP/NUMBER/etc.) so real assignments survive, while
    docstrings/comments that merely *describe* the honesty rules do not.
    """
    try:
        toks = tokenize.generate_tokens(io.StringIO(src).readline)
        return "".join(
            t.string for t in toks if t.type not in (tokenize.COMMENT, tokenize.STRING)
        )
    except tokenize.TokenError:
        return src  # malformed source; let the real scan (below) fall through


# Assignment-level idioms that must never appear as real code in the governed
# social surfaces. Values are only ever assigned from a provider that is
# available, or the datum is left unknown / omitted -- never synthesized.
FORBIDDEN_READY = [
    re.compile(r"\bfollowers\s*=\s*0\b"),
    re.compile(r"\bfollowing_count\s*=\s*0\b"),
    re.compile(r"\bfollowing\s*=\s*0\b"),
    re.compile(r"\bengagement_rate\s*=\s*0\b"),
    re.compile(r"\binfluence_level\s*=\s*[\"']low[\"']"),
    re.compile(r"\binfluence\s*=\s*[\"']low[\"']"),
    re.compile(r"\baudience_overlap\s*=\s*0\.\d+"),
    re.compile(r"\boverlap\s*=\s*0\.(20|15|25)\b"),
]


def _check_legacy_honesty() -> None:
    offenders: list[str] = []
    for path in _walk_py_files():
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        stripped = _strip_strings_and_comments(src)
        for pat in FORBIDDEN_READY:
            if pat.search(stripped):
                rel = os.path.relpath(path, ROOT)
                offenders.append(f"{rel}: matches {pat.pattern!r}")
    if offenders:
        fail("legacy fabricated-default / fixed-overlap idiom(s) present:\n  "
             + "\n  ".join(sorted(set(offenders))))


def _load_registry() -> dict:
    with open(REGISTRY, encoding="utf-8") as fh:
        return json.load(fh)


def _check_registry() -> dict:
    reg = _load_registry()
    preds = reg.get("predicates", [])
    if not preds:
        fail("predicate registry declares no predicates")
        return {}
    by_state: dict[str, list[dict]] = {}
    for p in preds:
        by_state.setdefault(p.get("graphRegistrationState", "UNKNOWN"), []).append(p)

    registered = by_state.get("REGISTERED", [])
    if not registered:
        fail("predicate registry has no REGISTERED predicate")

    edge_names: list[str] = []
    for p in registered:
        edge = p.get("graphEdgeType")
        if not edge or not isinstance(edge, str) or not edge.strip():
            fail(f"REGISTERED predicate {p.get('predicate')!r} has empty graphEdgeType")
        elif not re.fullmatch(r"[A-Z][A-Z0-9_]*", edge):
            fail(f"REGISTERED predicate {p.get('predicate')!r} graphEdgeType {edge!r} "
                 "does not match live enum naming ([A-Z][A-Z0-9_]*)")
        else:
            edge_names.append(edge)

    dupes = sorted({e for e in edge_names if edge_names.count(e) > 1})
    if dupes:
        fail(f"duplicate REGISTERED graphEdgeType(s): {dupes}")

    # Every REGISTERED predicate must be honest about its family/validity/claim
    # flooring (a registered edge with an empty claim-type floor would imply
    # claims the spine does not enforce).
    for p in registered:
        for field in ("family", "directionality", "validitySemantics", "claimTypeFloor"):
            if not p.get(field):
                fail(f"REGISTERED predicate {p.get('predicate')!r} missing {field}")
    return {p.get("graphEdgeType"): p.get("predicate") for p in registered
            if p.get("graphEdgeType")}


def _check_live_graph_honesty(registered_edges: dict) -> None:
    """REGISTERED edges must be real, mapped edge kinds on the live spine."""
    try:
        sys.path.insert(0, BACKEND)
        from shared.graph import graph  # noqa: E402
        import shared.graph.relationship_layers as rl  # noqa: E402
    except Exception as exc:  # pragma: no cover - fail-closed when substrate unavailable
        fail(f"could not import live graph substrate for edge cross-check: "
             f"{type(exc).__name__}: {exc}")
        return

    live_members: set[str] = set()
    for name in dir(graph.EdgeType):
        if name.startswith("_"):
            continue
        val = getattr(graph.EdgeType, name)
        if isinstance(val, str):
            live_members.add(name)

    layer_map = getattr(rl, "_EDGE_LAYER_MAP", None)
    if not isinstance(layer_map, dict):
        fail("shared.graph.relationship_layers._EDGE_LAYER_MAP is not a populated dict")

    for edge, predicate in sorted(registered_edges.items()):
        if edge not in live_members:
            fail(f"REGISTERED predicate {predicate!r} names edge {edge!r} that is not a "
                 "live shared.graph.graph.EdgeType member")
        if layer_map is not None and edge not in layer_map:
            fail(f"REGISTERED predicate {predicate!r} names edge {edge!r} that is not "
                 "present in shared.graph.relationship_layers._EDGE_LAYER_MAP")
    if live_members:
        NOTES.append(f"live EdgeType members checked: {len(live_members)}; "
                     f"layer-map edges checked: {len(layer_map) if layer_map else 0}")


def main() -> int:
    if not os.path.exists(REGISTRY):
        fail(f"registry missing: {os.path.relpath(REGISTRY, ROOT)}")
        print("\n".join(["ERRORS"] + ERRORS))
        return 1
    registered_edges = _check_registry()
    if not ERRORS:
        _check_live_graph_honesty(registered_edges)
    if not ERRORS:
        _check_legacy_honesty()

    print("Social360 static guardrails"
          + (" (registry <-> live EdgeType + layer map + legacy-honesty scan)"))
    for note in NOTES:
        print(f"  note: {note}")
    if ERRORS:
        print("ERRORS:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    registered = len(registered_edges)
    print(f"PASSED -- {registered} REGISTERED predicates validated against live "
          "graph substrate; no fabricated-default/fixed-overlap idioms in "
          f"{len(_walk_py_files())} governed files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
