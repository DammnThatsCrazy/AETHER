#!/usr/bin/env python3
"""Shared helpers for Aether founding-tenant release/validation scripts.

Pure stdlib + PyYAML. Every check script imports this for a consistent
repo-root finder, YAML loader, and a small pass/fail reporter that exits 1 on
any failure — matching the plain-text ✓/✗ convention used across scripts/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a repo dependency
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    raise


def repo_root() -> Path:
    """Return the repository root (the dir containing this scripts/ tree)."""
    return Path(__file__).resolve().parents[2]


def load_yaml(rel_path: str) -> Any:
    """Load a YAML file relative to the repo root. Raises FileNotFoundError."""
    path = repo_root() / rel_path
    if not path.exists():
        raise FileNotFoundError(rel_path)
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class Reporter:
    """Accumulates check results and prints a consistent summary."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.failures: list[str] = []
        self.checks = 0
        print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")

    def ok(self, message: str) -> None:
        self.checks += 1
        print(f"  ✓ {message}")

    def warn(self, message: str) -> None:
        print(f"  ⚠ {message}")

    def fail(self, message: str) -> None:
        self.checks += 1
        self.failures.append(message)
        print(f"  ✗ {message}")

    def require(self, condition: bool, ok_msg: str, fail_msg: str) -> bool:
        if condition:
            self.ok(ok_msg)
        else:
            self.fail(fail_msg)
        return bool(condition)

    def finish(self) -> int:
        print("-" * 70)
        if self.failures:
            print(f"  RESULT: FAIL — {len(self.failures)} of {self.checks} checks failed")
            for f in self.failures:
                print(f"    - {f}")
            print("=" * 70)
            return 1
        print(f"  RESULT: PASS — {self.checks} checks passed")
        print("=" * 70)
        return 0


def main_guard(fn) -> None:
    """Run a check function returning an exit code, and sys.exit with it."""
    # Ensure the release dir is importable when run as `python scripts/release/x.py`
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(fn())
