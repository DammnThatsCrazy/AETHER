#!/usr/bin/env python3
"""Run the complete backend test tree with benchmark tests isolated.

The backend suite is intentionally parallel for ordinary tests, but the
performance guardrails measure wall-clock latency. Running those benchmarks
alongside thousands of xdist workers turns scheduler contention into a false
regression (and makes the canonical gate depend on worker count). Keep the
full tree covered while running the benchmark module in one process after the
parallel behavioral suite completes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BACKEND_TESTS = Path("Backend Architecture/aether-backend/tests")
PERFORMANCE_TESTS = BACKEND_TESTS / "performance"


def _run_pytest(*paths: str, serial: bool = False) -> int:
    command = [sys.executable, "-m", "pytest", *paths, "-v", "--tb=short"]
    if serial:
        # Override pyproject.toml's ``-n auto`` for wall-clock benchmarks.
        command.extend(["-n", "0"])
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT).returncode


def main() -> int:
    """Run behavior tests in parallel, then performance tests serially."""

    # ``--ignore`` keeps the first invocation's coverage disjoint from the
    # dedicated benchmark pass; the second invocation covers that exact path.
    behavior_rc = _run_pytest(str(BACKEND_TESTS), "--ignore", str(PERFORMANCE_TESTS))
    if behavior_rc:
        return behavior_rc
    return _run_pytest(str(PERFORMANCE_TESTS), serial=True)


if __name__ == "__main__":
    raise SystemExit(main())

