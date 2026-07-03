#!/usr/bin/env python3
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

REQUIRED = [
    "Backend Architecture/aether-backend/services/semantic_intelligence/models.py",
    "Backend Architecture/aether-backend/services/semantic_intelligence/engine.py",
    "Backend Architecture/aether-backend/services/semantic_intelligence/routes.py",
    "Backend Architecture/aether-backend/tests/semantic_intelligence/test_semantic_intelligence.py",
    "docs/semantic-sentiment/SEMANTIC-SENTIMENT-INTELLIGENCE.md",
    "docs/runbooks/semantic-sentiment/semantic-sentiment-operations.md",
    "Backend Architecture/aether-backend/alembic/versions/20260702_semantic_sentiment.py",
    "packages/shared/semantic-sentiment.ts",
]


def main() -> int:
    missing = [p for p in REQUIRED if not Path(p).exists()]
    if missing:
        print("missing required semantic-sentiment assets:", missing)
        return 1
    strict = "--strict" in sys.argv
    if strict:
        env = os.environ.copy()
        env["PYTEST_ADDOPTS"] = ""
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "pytest",
                "-o",
                "addopts=",
                "Backend Architecture/aether-backend/tests/semantic_intelligence",
                "-q",
            ],
            env=env,
        )
    print("semantic-sentiment release gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
