#!/usr/bin/env python3
"""Frontend value-display guardrail.

Financial values must be rendered through the canonical frontend/shared value
formatter (formatUSD / formatAetherValue / ValueDisplay), never a per-file
currency formatter — that is how "$0.00 on unknown" and mislabeled-native bugs
creep in.

This gate fails when a frontend file defines its OWN currency formatter (a
`style: 'currency'` Intl.NumberFormat, or a local fmtUsd/formatUSD/formatCurrency
definition) outside the canonical `frontend/shared` value module — unless the
file is on the ALLOWLIST (a documented, shrinking adoption backlog). Migrating a
file means switching it to the shared formatter AND removing it from ALLOWLIST;
a stale allowlist entry also fails, keeping the backlog honest.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ["frontend/aether/src", "frontend/kyber/src", "frontend/demo/src"]
# The canonical home for value formatting — exempt from the guardrail.
CANONICAL_PREFIXES = ("frontend/shared/",)

# Documented adoption backlog: files that still roll their own currency
# formatter and are pending migration to the shared value components. Shrink
# this list as surfaces adopt ValueDisplay; do not grow it.
ALLOWLIST = {
    "frontend/aether/src/pages/billing/billing-page.tsx",
    "frontend/aether/src/pages/campaigns/campaign-360-page.tsx",
    "frontend/kyber/src/features/measurement/campaign360/campaign-360-overview.tsx",
}

_CURRENCY_INTL = re.compile(r"style:\s*['\"]currency['\"]")
_LOCAL_FORMATTER = re.compile(r"\b(?:function|const|let)\s+(?:fmtUsd|fmtUSD|formatUSD|formatCurrency)\b")


def defines_local_formatter(text: str) -> bool:
    return bool(_CURRENCY_INTL.search(text) or _LOCAL_FORMATTER.search(text))


def main() -> int:
    violations: list[str] = []
    matched_allowlisted: set[str] = set()

    for root in SCAN_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.tsx"):
            rel = str(path.relative_to(ROOT))
            if rel.startswith(CANONICAL_PREFIXES):
                continue
            if not defines_local_formatter(path.read_text(encoding="utf-8")):
                continue
            if rel in ALLOWLIST:
                matched_allowlisted.add(rel)
            else:
                violations.append(rel)
        for path in base.rglob("*.ts"):
            rel = str(path.relative_to(ROOT))
            if rel.startswith(CANONICAL_PREFIXES) or rel in ALLOWLIST:
                if rel in ALLOWLIST and defines_local_formatter(path.read_text(encoding="utf-8")):
                    matched_allowlisted.add(rel)
                continue
            if defines_local_formatter(path.read_text(encoding="utf-8")):
                violations.append(rel)

    stale = sorted(ALLOWLIST - matched_allowlisted)

    if violations or stale:
        print("frontend value-display guardrail FAILED:")
        for v in sorted(violations):
            print(f"  - {v}: defines a local currency formatter; render via frontend/shared ValueDisplay/formatUSD")
        for s in stale:
            print(f"  - {s}: on ALLOWLIST but no longer defines a local formatter — remove it from the allowlist")
        return 1

    print(
        f"frontend value-display guardrail OK "
        f"({len(matched_allowlisted)} allowlisted pending, 0 new violations)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
