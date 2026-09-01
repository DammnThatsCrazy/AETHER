#!/usr/bin/env python3
"""Reject duplicate concrete Make targets before GNU Make can override them."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):(?!=)")


def duplicate_targets(text: str) -> list[str]:
    names = [match.group(1) for line in text.splitlines() if (match := TARGET.match(line))]
    return sorted(name for name, count in Counter(names).items() if count > 1)


def main() -> int:
    duplicates = duplicate_targets((ROOT / "Makefile").read_text(encoding="utf-8"))
    if duplicates:
        print("duplicate Make targets: " + ", ".join(duplicates))
        return 1
    print("Makefile target registry OK: no duplicate concrete targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

