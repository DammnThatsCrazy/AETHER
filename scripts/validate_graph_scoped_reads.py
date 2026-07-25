#!/usr/bin/env python3
"""Graph scoped-read gate.

``GraphClient.get_all_vertices(limit=N)`` applies the cap to the WHOLE graph.
A service that fetches such a page and filters it by tenant afterwards gets
silent truncation: a tenant whose vertices sort past the cap receives a partial
result or none at all, and it reads to the caller as "you have no data" rather
than as an error. Per-tenant questions must use
``GraphClient.get_vertices_for_tenant(tenant_id, limit=N)``, which pushes the
tenant predicate into the query so the cap bounds that tenant's own rows.

This gate freezes the blast radius: the committed allowlist
(``scripts/allowlists/graph_global_reads.json``) names every file under
``services/`` that legitimately performs a cross-tenant read today. A NEW
global reader fails CI; a migrated reader must be removed from the allowlist
(shrink-only).

Usage:
  python scripts/validate_graph_scoped_reads.py           # validate (CI gate)
  python scripts/validate_graph_scoped_reads.py --seed    # rewrite allowlist
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
ALLOWLIST = ROOT / "scripts" / "allowlists" / "graph_global_reads.json"

_GLOBAL_READ_METHODS = frozenset({"get_all_vertices"})
# Conservative fallback used only when a file fails to tokenize.
_GLOBAL_READ_CALL = re.compile(r"\.(get_all_vertices)\s*\(")


def _reads_globally(text: str) -> bool:
    """Return True iff the source contains a real ``.get_all_vertices(`` call.

    Tokenizing (rather than a bare regex) means references to the method inside
    docstrings, comments, or string literals — e.g. the "prefer
    ``get_vertices_for_tenant``" note in module documentation — are not
    mistaken for global readers. A genuine attribute call still trips the gate.
    If a file cannot be tokenized we fall back to the regex so a parse error
    can never hide a real global read.
    """
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return bool(_GLOBAL_READ_CALL.search(text))
    for i in range(len(toks) - 2):
        dot, name, paren = toks[i], toks[i + 1], toks[i + 2]
        if (
            dot.type == tokenize.OP
            and dot.string == "."
            and name.type == tokenize.NAME
            and name.string in _GLOBAL_READ_METHODS
            and paren.type == tokenize.OP
            and paren.string == "("
        ):
            return True
    return False


def scan() -> set[str]:
    offenders: set[str] = set()
    for path in (BACKEND / "services").rglob("*.py"):
        rel = str(path.relative_to(ROOT))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _reads_globally(text):
            offenders.add(rel)
    return offenders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="rewrite the allowlist from current state")
    args = parser.parse_args()

    actual = scan()

    if args.seed:
        ALLOWLIST.parent.mkdir(parents=True, exist_ok=True)
        ALLOWLIST.write_text(json.dumps(sorted(actual), indent=2) + "\n")
        print(f"seeded graph global-read allowlist: {len(actual)} cross-tenant readers")
        return 0

    allowlist = set(json.loads(ALLOWLIST.read_text())) if ALLOWLIST.exists() else set()
    errors: list[str] = []
    for f in sorted(actual - allowlist):
        errors.append(
            f"NEW global graph read (use get_vertices_for_tenant for a per-tenant question): {f}"
        )
    for f in sorted(allowlist - actual):
        errors.append(f"allowlist entry no longer reads globally — REMOVE it (shrink-only): {f}")

    if errors:
        print("GRAPH SCOPED-READ VIOLATIONS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"graph scoped reads OK: {len(actual)} legitimately global readers frozen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
