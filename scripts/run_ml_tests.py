#!/usr/bin/env python3
"""Run the ML test tree from its package root.

The ML tests intentionally import local helpers through the ``tests`` package
and import the ML packages (``common``, ``serving``, and friends) as top-level
modules.  Running them from the repository root lets the unrelated root
``tests`` package win module resolution, so the canonical runner must provide
the ML package root as both the working directory and an explicit import root.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ML_ROOT = ROOT / "services" / "ml"


def main() -> int:
    command = [sys.executable, "-m", "pytest", "tests", "-v", "--tb=short"]
    print("+", " ".join(command), flush=True)
    env = os.environ.copy()
    ml_root = str(ML_ROOT)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        path for path in (ml_root, existing_pythonpath) if path
    )
    return subprocess.run(command, cwd=ML_ROOT, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
