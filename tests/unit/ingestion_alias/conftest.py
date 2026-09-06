"""Path setup for the WS-B2 deprecated-alias convergence unit tests.

The canonical backend (config/settings, services/ingestion/batch.py,
services/ingestion/routes.py, repositories/lake.py) lives under the backend
root, so it must sit on sys.path while these tests run (same pattern as
tests/unit/observation/conftest.py and tests/unit/temporal/conftest.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
