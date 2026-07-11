#!/usr/bin/env python3
"""Validate that consent-purpose documentation stays registry-derived.

Canonical source of truth: ``packages/shared/contracts/consent-registry.json``.

This gate fails if an authoritative doc hardcodes a consent-purpose *count* that
can silently drift from the registry (e.g. "five consent purposes", "Eight
canonical purposes", "all 8 purposes"), instead of using registry-derived
language. It also asserts the generated consent-registry table's stated count
matches the registry.

Deliberately NOT scanned (historical or machine-managed records):
generated docs (``docs/_generated/``), changelogs, ``docs/archive/``,
``docs/plans/``, and point-in-time ``reports/``. Those legitimately describe a
count at a moment in time and must not be rewritten to erase history.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "packages/shared/contracts/consent-registry.json"
GENERATED_TABLE = ROOT / "docs/_generated/consent-registry-table.md"

# Authoritative, currently-maintained docs that must use registry-derived
# language and never hardcode a consent-purpose count.
SCANNED_DOCS = [
    "README.md",
    "docs/source-of-truth/CONSENT_MODEL.md",
    "docs/source-of-truth/SDK_SCOPE.md",
    "docs/source-of-truth/README.md",
    "docs/COMPLIANCE.md",
    "docs/PRODUCTIZATION.md",
    "docs/SDK-WEB.md",
    "docs/SDK-IOS.md",
    "docs/SDK-ANDROID.md",
    "docs/SDK-REACT-NATIVE.md",
]

_NUM = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)"

# Phrases that assert a fixed consent-purpose count.
COUNT_PATTERNS = [
    re.compile(rf"\b{_NUM}\s+(?:canonical\s+|distinct\s+|total\s+)?consent\s+purposes\b", re.I),
    re.compile(rf"\b{_NUM}\s+canonical\s+purposes\b", re.I),
    re.compile(rf"\ball\s+{_NUM}\s+purposes\b", re.I),
    re.compile(rf"\bsame\s+{_NUM}\s+purposes\b", re.I),
    re.compile(rf"\b{_NUM}\s+consent\s+purposes\b", re.I),
]


def registry_count() -> int:
    data = json.loads(REGISTRY.read_text())
    return len(data["purposes"])


def check_generated_table(expected: int) -> list[str]:
    if not GENERATED_TABLE.exists():
        return []
    text = GENERATED_TABLE.read_text()
    m = re.search(r"(\d+)\s+purposes", text)
    if m and int(m.group(1)) != expected:
        return [
            f"{GENERATED_TABLE.relative_to(ROOT)}: generated table states {m.group(1)} "
            f"purposes but the registry has {expected}. "
            f"Run: python scripts/generate_contracts.py"
        ]
    return []


def scan_docs() -> list[str]:
    errors: list[str] = []
    for rel in SCANNED_DOCS:
        p = ROOT / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text().splitlines(), start=1):
            for pat in COUNT_PATTERNS:
                m = pat.search(line)
                if m:
                    errors.append(
                        f"{rel}:{i}: hardcoded consent-purpose count "
                        f"'{m.group(0).strip()}'."
                    )
    return errors


def main() -> int:
    if not REGISTRY.exists():
        print(f"consent-registry doc validation FAILED: missing {REGISTRY}")
        return 1
    expected = registry_count()
    errors = check_generated_table(expected) + scan_docs()
    if errors:
        print("consent-registry doc validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        print(
            "\nConsent behavior is registry-derived. Do not hardcode a purpose "
            "count in authoritative docs; reference "
            "packages/shared/contracts/consent-registry.json (canonical) and the "
            "generated table docs/_generated/consent-registry-table.md instead."
        )
        return 1
    print(
        f"consent-registry doc validation OK "
        f"({expected} purposes, registry-derived, no hardcoded counts)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
