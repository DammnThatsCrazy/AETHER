"""WS-B3 consent-on-every-path regression harness.

Regression tests for the post-review enforcement rule: the MANDATORY
minimization layer (scrub + strip + T-class tenant data-policy) runs
UNCONDITIONALLY on every non-batch ingress seam; ONLY the per-subject (S)
server-receipt rejection is a per-path toggle (default OFF), and an OFF state
never bypasses the mandatory layer (imports fail closed).

The backend lives under ``Backend Architecture/aether-backend`` (note the
space) — ``tests/ingestion/conftest.py -> parents[2]`` is the repo root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("AETHER_ENV", "local")


@pytest.fixture(autouse=True)
def _clean_in_memory_stores():
    """Reset every JSONB in-memory store before each WS-B3 regression test.

    Receipts/profiles seeded by one test must never satisfy another test's
    fail-closed assertion. Each test also uses a unique tenant id (defense in
    depth under ``-n auto``). Mirrors tests/chaos/conftest.py.
    """
    from repositories.repos import reset_in_memory_stores

    reset_in_memory_stores()
    yield
    reset_in_memory_stores()
