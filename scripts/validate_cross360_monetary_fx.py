#!/usr/bin/env python3
"""Cross-360 monetary/FX canonical-seam guard (Context Intelligence 360, Phase 5).

Standing rule (``docs/plans/CONTEXTUAL_360_PHASES.md`` §4 rule 4): every
measure uses ``shared/measurement`` and **monetary values consume the canonical
value contract / FX provenance only** — there is no geography- or
population-specific FX, and a cross-360 monetary metric is never computed by
re-pricing inside the context family.

In repository terms the three context-360 leaves (WHEN ``temporal360``, WHERE
``geographic360`` + its ``services/geo`` plane, WHO/cohort ``population360``),
the exploration surface path that routes them, and the cross-360 composition
seam (:mod:`shared.projection_engine.composition`) are **monetary-free**: money
lives in economic360 / ``services.value`` (the ``packages/shared/value.ts``
mirror), whose pre-priced section content already composes unchanged through
:mod:`shared.projection_engine.composition` — never a per-slice FX or money
class introduced beside it.

This gate scans those roots for monetary/FX handling vocabulary and fails on
any new occurrence (a committed SHRINK-ONLY allowlist under
``scripts/allowlists/`` records today's debt — empty). Introducing a monetary
metric into a context-360 provider, its service plane, the exploration path, or
the composition seam therefore fails CI with a pointer to the canonical seam.

Usage:
  python scripts/validate_cross360_monetary_fx.py             # validate (CI gate)
  python scripts/validate_cross360_monetary_fx.py --seed      # (re)write the allowlist from current state
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
ALLOWLIST = (
    ROOT / "scripts" / "allowlists" / "cross360_monetary_fx.json"
)

# Scanned roots: the context-360 leaves and the planes that serve/compose them.
_SCAN_ROOTS = (
    BACKEND / "services" / "temporal360",
    BACKEND / "services" / "geographic360",
    BACKEND / "services" / "geo",
    BACKEND / "services" / "population360",
    BACKEND / "services" / "exploration",
)
_SCAN_FILES = (BACKEND / "shared" / "projection_engine" / "composition.py",)

# Monetary/FX handling vocabulary. Deliberately excludes the canonical-seam
# names a legitimate cross-360 path would IMPORT (``services.value``,
# ``economic360_contracts``, ``shared.commerce_contracts.money``) — those live
# outside the scanned roots and are the sanctioned remediation, not an
# offender. Word boundaries keep ``usd``/``money``/``fx`` from false-matching
# inside innocuous identifiers.
_PATTERNS = (
    re.compile(r"currency"),
    re.compile(r"exchange_rate"),
    re.compile(r"conversion_rate"),
    re.compile(r"fx_rate"),
    re.compile(r"fx_provider"),
    re.compile(r"fx_snapshot"),
    re.compile(r"price_sources"),
    re.compile(r"price_provider"),
    re.compile(r"safe_rollup"),
    re.compile(r"safe_usd_total"),
    re.compile(r"native_currency"),
    re.compile(r"monetary"),
    re.compile(r"MonetaryAmount"),
    re.compile(r"money_from_cents"),
    re.compile(r"sum_money"),
    re.compile(r"valuation_method"),
    re.compile(r"AetherValue"),
    re.compile(r"USDValuation"),
    re.compile(r"NativeValue"),
    re.compile(r"\busd\b"),
    re.compile(r"\bmoney\b"),
    re.compile(r"\bfx\b"),
)


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _files() -> list[Path]:
    paths: list[Path] = []
    for root in _SCAN_ROOTS:
        paths.extend(root.rglob("*.py"))
    paths.extend(_SCAN_FILES)
    return paths


def scan() -> set[str]:
    offenders: set[str] = set()
    for path in sorted(_files()):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(p.search(text) for p in _PATTERNS):
            offenders.add(_rel(path))
    return offenders


def _load(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="rewrite the allowlist from current state")
    args = parser.parse_args()

    offenders = scan()

    if args.seed:
        ALLOWLIST.parent.mkdir(parents=True, exist_ok=True)
        ALLOWLIST.write_text(json.dumps(sorted(offenders), indent=2) + "\n")
        print(f"seeded cross360_monetary_fx allowlist: {len(offenders)} file(s)")
        return 0

    allowlist = _load(ALLOWLIST)
    errors: list[str] = []
    for path in sorted(offenders - allowlist):
        errors.append(f"NEW offender (route money through the canonical value seam): {path}")
    for path in sorted(allowlist - offenders):
        errors.append(
            f"allowlist entry is clean — REMOVE it (shrink-only): {path}"
        )

    if errors:
        print("CROSS-360 MONETARY/FX VIOLATIONS:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "The context-360 family (temporal360/geographic360/population360), "
            "its services/geo plane, the exploration path, and the cross-360 "
            "composition seam are monetary-free by doctrine. A monetary metric "
            "must come pre-priced from economic360 / services.value (the "
            "packages/shared/value.ts mirror) with canonical FX provenance — "
            "see docs/source-of-truth/FINANCIAL_VALUE_SEMANTICS.md. Never add a "
            "geography- or population-specific FX/money path beside them.",
            file=sys.stderr,
        )
        return 1

    print(
        f"cross-360 monetary/FX OK: {len(offenders)} offender(s) across "
        f"{len(_files())} file(s); allowlist debt={len(allowlist)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
